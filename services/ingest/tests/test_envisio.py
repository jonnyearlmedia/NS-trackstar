import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.envisio import EnvisioAdapter

_GRAPHQL = "https://envisio-pdv2-s-production.herokuapp.com/graphql"

# The dashboard document's own runtime config, as served.
_DASHBOARD_HTML = (
    '<!doctype html><html><body><div id="root"></div><script>window.token="",'
    'window.corporationId="",'
    f'window.serverUri="{_GRAPHQL}",'
    'window.userId="__USER_ID__",window.stage="__STAGE__"</script></body></html>'
)

_WATER = {
    "title": "Water",
    "planNodeId": "Strategy-104696",
    "numberWithLabel": "Strategy 1.3",
    "parentPlanNodeId": "",
    "description": "<p><strong>Water</strong></p>",
}

_TANK = {
    "planNodeId": "Activity-272888",
    "parentPlanNodeId": "Strategy-104696",
    "numberWithLabel": "Projects 1.3.1",
    "title": "Project Name: W-101 Tank 2 Rehabilitation",
    "description": (
        "<p>Project Name:<strong> W-101 Tank 2 Rehabilitation</strong></p>"
        "<p>Description: <p>&nbsp;Rehabilitate Tank 2 at Lower Reservoir. &nbsp;Rehabilitation "
        "includes sandblasting, coating of interior, and sanitization of tank.</p></p>"
        "<p>Budget: $1,045,809.00</p><p>Expenditure: $100,184.00</p>"
        "<p>Project Phase: Early Design</p>"
    ),
    "latestUpdate": "<p>Test Update&nbsp;</p>",
    "startDate": "Jun 30, 2024",
    "endDate": "Dec 31, 2025",
    "tags": [],
    "customFieldRecords": [],
}

# A real St. Helena project with no expenditure figure published yet.
_PUMP = {
    "planNodeId": "Activity-272910",
    "parentPlanNodeId": "Strategy-104696",
    "numberWithLabel": "Projects 1.3.9",
    "title": "Project Name: S18-71 Crinella Pump Station Upgrades",
    "description": (
        "<p>Project Name:<strong> S18-71 Crinella Pump Station Upgrades</strong></p>"
        "<p>Description: <p>Upgrade the Crinella pump station.</p></p>"
        "<p>Budget: $2,500,000.00</p><p>Expenditure: </p>"
        "<p>Project Phase: Future Fiscal Year Project</p>"
    ),
    "latestUpdate": "",
    "startDate": "Jul 1, 2026",
    "endDate": "Jun 30, 2027",
    "tags": [],
}

# The trap: a performance measure keyed with a compound id that starts "Activity-".
# It carries no project fields at all and is not a project.
_MEASURE = {
    "measureId": "Activity-272997-Activity-272997-Outcome-41738",
    "planNodeId": "Activity-272997",
    "position": 1,
    "tags": [],
    "description": "",
    "title": "Water Meter Manual Re-Reads, By Month",
}

_HOME = {"name": "5219a3b1-p-4607", "columns": 3, "children": [dict(_WATER, children=[])]}

_SETTINGS = {
    "name": "City of St. Helena, CA",
    "planName": "NEW Capital Improvement Plan",
    "subDomain": "cityofsthelena",
    "onTrackCount": 1,
    "upcomingCount": 1,
    "completedCount": 0,
    "someDisruptionCount": 0,
    "majorDisruptionCount": 0,
    "discontinuedCount": 0,
    "statusPendingCount": 0,
}

_PAGES = {
    "home": _HOME,
    "Strategy-104696": _WATER,
    "Activity-272888": _TANK,
    "Activity-272910": _PUMP,
    "Activity-272997-Activity-272997-Outcome-41738": _MEASURE,
}


def _config(**options: object) -> SourceConfig:
    base: dict[str, object] = {"sub_domain": "cityofsthelena4607"}
    base.update(options)
    return SourceConfig(
        key="st-helena.capital-improvement-projects",
        name="St. Helena Capital Improvement Projects",
        jurisdiction="City of St. Helena",
        base_url="https://www.cityofsthelena.gov/490/CIP-Interactive-Dashboard",
        poll_minutes=1440,
        options=base,
    )


def _handler(*, pages: dict | None = None, dashboard_html: str = _DASHBOARD_HTML):
    payload = {"pages": _PAGES if pages is None else pages, "generalSettings": _SETTINGS}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.host == "performance.envisio.com":
            return httpx.Response(200, text=dashboard_html)
        if request.method == "POST" and str(request.url) == _GRAPHQL:
            return httpx.Response(200, json={"data": {"publishData": payload}})
        return httpx.Response(404)

    return handle


async def test_collect_reads_the_dashboards_own_graphql_query_and_keeps_the_citys_words() -> None:
    seen: list[httpx.Request] = []

    handle = _handler()

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 2

    tank = next(r for r in result.records if r.external_id.endswith("Activity-272888"))
    assert tank.external_id == "envisio:cityofsthelena4607:Activity-272888"
    assert tank.canonical_url == (
        "https://performance.envisio.com/dashboard-brandoff/cityofsthelena4607/Activity-272888"
    )

    payload = tank.normalized_payload
    assert payload["name"] == "W-101 Tank 2 Rehabilitation"
    assert payload["project_number"] == "W-101"
    # The city's own phase and category words, stored as written.
    assert payload["project_phase"] == "Early Design"
    assert payload["category"] == "Water"
    assert payload["budget_amount"] == 1045809.0
    assert payload["expenditure_amount"] == 100184.0
    assert payload["start_date"] == "2024-06-30"
    assert payload["end_date"] == "2025-12-31"
    assert payload["latest_update"] == "Test Update"
    assert payload["description"].startswith("Rehabilitate Tank 2 at Lower Reservoir.")

    # The raw payload survives alongside the normalized one, parent included.
    assert tank.raw_payload["page"]["description"] == _TANK["description"]
    assert tank.raw_payload["parent"]["planNodeId"] == "Strategy-104696"

    posted = next(r for r in seen if r.method == "POST")
    assert str(posted.url) == _GRAPHQL
    body = posted.read().decode()
    # The query is the vendor's own text, not a reconstruction.
    assert "query publishData($subDomain: String, $pageId: String)" in body
    assert '"subDomain": "cityofsthelena4607"' in body


async def test_parser_yield_divides_by_project_pages_not_by_everything_fetched() -> None:
    """Five pages come back and only two of them are projects.

    The payload also carries the home page, the plan's categories and a performance
    measure whose id starts "Activity-". Dividing by all five would report 0.4 on a
    run where every project parsed perfectly.
    """
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler())) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        result = await adapter.collect()

    assert result.parser_yield == 1.0
    assert result.metadata["pages_returned"] == 5
    assert result.metadata["project_pages"] == 2
    assert result.metadata["rows_unparsed"] == 0
    assert [r.normalized_payload["plan_node_id"] for r in result.records] == [
        "Activity-272888",
        "Activity-272910",
    ]


async def test_a_project_whose_labels_vanish_drags_the_yield_down_rather_than_going_quiet() -> None:
    broken = dict(_TANK, description="<p>W-101 Tank 2 Rehabilitation</p>")
    pages = dict(_PAGES, **{"Activity-272888": broken})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages=pages))) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        result = await adapter.collect()

    assert len(result.records) == 1
    assert result.parser_yield == 0.5
    assert result.metadata["rows_unparsed"] == 1
    assert result.metadata["unparsed_plan_node_ids"] == ["Activity-272888"]


async def test_a_field_the_agency_left_blank_is_recorded_as_unsaid_not_as_zero() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler())) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        result = await adapter.collect()

    pump = next(r for r in result.records if r.external_id.endswith("Activity-272910"))
    assert pump.normalized_payload["budget_amount"] == 2500000.0
    assert "expenditure_amount" not in pump.normalized_payload
    assert "latest_update" not in pump.normalized_payload
    assert result.metadata["projects_missing_expenditure"] == 1
    assert result.metadata["projects_without_latest_update"] == 1
    assert result.metadata["projects_counted_by_agency"] == 2


async def test_an_unknown_subdomain_answers_200_with_nothing_and_fails_the_canary() -> None:
    """Envisio does not error on a bad subdomain; it returns an empty object."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=_DASHBOARD_HTML)
        return httpx.Response(200, json={"data": {"publishData": {}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EnvisioAdapter(_config(sub_domain="nosuchagency0000"), client=client)
        assert await adapter.canary() is False


async def test_canary_fails_when_the_dashboard_stops_carrying_the_agencys_labels() -> None:
    stripped = {"Activity-272888": dict(_TANK, description="<p>Just a sentence.</p>")}

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages=stripped))) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        assert await adapter.canary() is False


async def test_the_endpoint_is_followed_from_the_pages_own_config() -> None:
    moved = "https://envisio-pdv2-s-production.herokuapp.com/graphql"
    html = _DASHBOARD_HTML.replace(_GRAPHQL, moved)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler(dashboard_html=html))
    ) as client:
        adapter = EnvisioAdapter(
            _config(graphql_endpoint="https://envisio-pdv2-s-production.herokuapp.com/stale"),
            client=client,
        )
        result = await adapter.collect()

    assert result.metadata["graphql_endpoint"] == moved
    assert result.metadata["graphql_endpoint_discovered"] is True


async def test_an_endpoint_outside_the_allowed_hosts_is_not_followed() -> None:
    """A tampered page must not be able to point the collector somewhere else."""
    hijacked = _DASHBOARD_HTML.replace(_GRAPHQL, "https://evil.example.com/graphql")
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.method == "GET":
            return httpx.Response(200, text=hijacked)
        if str(request.url) == _GRAPHQL:
            return httpx.Response(
                200, json={"data": {"publishData": {"pages": _PAGES, "generalSettings": _SETTINGS}}}
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        result = await adapter.collect()

    assert result.metadata["graphql_endpoint"] == _GRAPHQL
    assert not any("evil.example.com" in url for url in seen)
    assert len(result.records) == 2


async def test_a_bot_challenge_is_reported_as_blocked_not_worked_around() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"cf-mitigated": "challenge"},
            text="<html><body>Attention Required! | Cloudflare</body></html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        with pytest.raises(SourceBlockedError, match="blocked"):
            await adapter.collect()


async def test_a_graphql_error_is_raised_rather_than_reported_as_an_empty_source() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=_DASHBOARD_HTML)
        return httpx.Response(200, json={"errors": [{"message": "Cannot query field"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EnvisioAdapter(_config(), client=client)
        with pytest.raises(RuntimeError, match="Cannot query field"):
            await adapter.collect()


def test_a_sub_domain_is_required() -> None:
    with pytest.raises(ValueError, match="sub_domain"):
        EnvisioAdapter(_config(sub_domain=""))
