import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.maintstar_public import MaintStarPublicAdapter, parse_point

_CONFIG_PATH = "/RioVista/mvc/Public/Configuration/portal"
_SEARCH_PATH = "/RioVista/api/Public/Record/Search"

_PORTAL_CONFIG = {
    "agency": "riovista",
    "showMap": False,
    "search": {"disableAnonymousSearch": False},
}

_SOLAR_ROW = {
    "id": 269562,
    "createdDate": "2026-09-11T11:59:11Z",
    "msValue": "Project:269562",
    "projectMsValue": "Project:269562",
    "projectNumber": "PS+26-0469",
    "msType": "SolarApp+",
    "projectType": "ProjectType:903",
    "number": "PS+26-0469",
    "type": "SolarApp+",
    "typeId": 157,
    "dateVal": "2026-09-11T00:00:00Z",
    "datePrefix": "Issued on",
    "addressId": 63736,
    "address": "2240 Espana Ln, Rio Vista, CA 94571",
    "status": "Issued and Paid",
    "statusBackColor": "LemonChiffon",
    "description": "(Confidential)",
    "lat": 38.18924843594601,
    "lng": -121.71859175780776,
    "canAddPublicComment": False,
    "isSentToDocStorage": False,
}

_CODE_ROW = {
    "id": 269540,
    "createdDate": "2026-09-10T16:04:00Z",
    "msValue": "Project:269540",
    "number": "CS26-0056",
    "msType": "Code Enf.",
    "type": "Code Enf.",
    "typeId": 143,
    "dateVal": "2026-09-10T00:00:00Z",
    "datePrefix": "Applied on",
    "addressId": 51022,
    "address": "1007 Flores Way",
    "status": "Open",
    "description": "(Confidential)",
    # An unset coordinate, which must leave the record unlocated rather than
    # putting a Rio Vista code case in the Gulf of Guinea.
    "lat": 0,
    "lng": 0,
}

_LICENSE_ROW = {
    "id": 269501,
    "createdDate": "2026-09-09T09:15:00Z",
    "msValue": "Project:269501",
    "number": "26-1834",
    "msType": "Business License/Brick and Mortar",
    "type": "Business License/Brick and Mortar",
    "typeId": 22,
    "dateVal": "2026-09-09T00:00:00Z",
    "datePrefix": "Issued on",
    "status": "Issued and paid",
    "description": "(Confidential)",
    "lat": None,
    "lng": None,
}


def _config(**options: object) -> SourceConfig:
    base: dict[str, object] = {
        "host": "https://h8.maintstar.co",
        "tenant": "RioVista",
        "queries": ["26-"],
        "take": 2,
        "max_pages_per_query": 10,
        "min_request_interval_seconds": 0,
    }
    base.update(options)
    return SourceConfig(
        key="rio-vista.maintstar",
        name="Rio Vista MaintStar Permit Portal",
        jurisdiction="City of Rio Vista",
        base_url="https://h8.maintstar.co/riovista/portal/",
        poll_minutes=1440,
        options=base,
    )


def _pages(*batches: list[dict]) -> dict[int, list[dict]]:
    return {index * 2: batch for index, batch in enumerate(batches)}


def _handler(
    pages_by_query: dict[str, dict[int, list[dict]]],
    *,
    portal_config: dict | None = None,
    calls: list[httpx.Request] | None = None,
):
    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path == _CONFIG_PATH:
            return httpx.Response(200, json=portal_config or _PORTAL_CONFIG)
        if request.url.path == _SEARCH_PATH:
            query = request.url.params["query"]
            skip = int(request.url.params["skip"])
            batch = pages_by_query.get(query, {}).get(skip, [])
            # "total" is always -1 on this API; the adapter must not read it.
            return httpx.Response(
                200,
                json={"data": batch, "total": -1, "showMoreMode": len(batch) == 2},
            )
        return httpx.Response(404, json={})

    return handle


async def _collect(adapter: MaintStarPublicAdapter):
    return await adapter.collect()


def test_parse_point_rejects_unset_and_out_of_range() -> None:
    assert parse_point(38.189, -121.718) == (38.189, -121.718)
    assert parse_point(0, 0) is None
    assert parse_point(None, -121.7) is None
    assert parse_point(38.1, None) is None
    assert parse_point("nope", "nope") is None
    assert parse_point(91.0, -121.7) is None
    assert parse_point(38.1, -181.0) is None


def test_queries_are_required() -> None:
    with pytest.raises(ValueError):
        MaintStarPublicAdapter(_config(queries=[]))


async def test_collect_normalizes_rows_and_stops_on_a_short_page() -> None:
    pages = {"26-": _pages([_SOLAR_ROW, _CODE_ROW], [_LICENSE_ROW])}
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler(pages, calls=calls))
    ) as client:
        result = await MaintStarPublicAdapter(_config(), client=client).collect()

    assert [record.normalized_payload["record_number"] for record in result.records] == [
        "PS+26-0469",
        "CS26-0056",
        "26-1834",
    ]
    # One config read plus two search pages: the short second page ends the walk
    # rather than a third request going out to find out.
    assert len(calls) == 3
    assert result.parser_yield == 1.0

    solar = result.records[0]
    assert solar.external_id == "maintstar:riovista:269562"
    assert solar.canonical_url == "https://h8.maintstar.co/riovista/portal/"
    assert solar.source_created_at is not None
    assert solar.source_created_at.isoformat() == "2026-09-11T11:59:11+00:00"
    assert solar.normalized_payload["source_record_type"] == "SolarApp+"
    assert solar.normalized_payload["source_status"] == "Issued and Paid"
    assert solar.normalized_payload["address"] == "2240 Espana Ln, Rio Vista, CA 94571"
    assert solar.normalized_payload["source_date_label"] == "Issued on"
    # The raw row is preserved alongside the normalized one.
    assert solar.raw_payload["search_row"]["statusBackColor"] == "LemonChiffon"


async def test_confidential_description_is_recorded_as_absent() -> None:
    pages = {"26-": _pages([_SOLAR_ROW])}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await MaintStarPublicAdapter(_config(), client=client).collect()

    payload = result.records[0].normalized_payload
    assert "description" not in payload
    assert payload["description_withheld"] is True
    assert result.metadata["descriptions_withheld"] == 1


async def test_geometry_is_used_only_when_the_coordinate_is_usable() -> None:
    pages = {"26-": _pages([_SOLAR_ROW, _CODE_ROW], [_LICENSE_ROW])}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await MaintStarPublicAdapter(_config(), client=client).collect()

    solar, code, license_ = result.records
    assert solar.geometry_geojson == {
        "type": "Point",
        "coordinates": [-121.71859175780776, 38.18924843594601],
    }
    assert solar.location_accuracy == "exact_source_geometry"
    assert solar.geometry_source is not None
    # 0,0 and null are both unlocated, and neither carries a geometry source.
    assert code.geometry_geojson is None
    assert code.location_accuracy is None
    assert code.geometry_source is None
    assert license_.geometry_geojson is None

    assert result.metadata["records_with_coordinates"] == 1
    assert result.metadata["coordinates_offered"] == 2
    assert result.metadata["coordinates_rejected"] == 1


async def test_overlapping_queries_deduplicate_and_report_their_own_yield() -> None:
    pages = {
        "26-": _pages([_SOLAR_ROW, _CODE_ROW], [_LICENSE_ROW]),
        "CS": _pages([_CODE_ROW]),
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        adapter = MaintStarPublicAdapter(_config(queries=["26-", "CS"]), client=client)
        result = await adapter.collect()

    assert len(result.records) == 3
    assert result.metadata["duplicate_rows_across_queries"] == 1
    walked = result.metadata["queries_walked"]
    assert [report["query"] for report in walked] == ["26-", "CS"]
    assert walked[0] == {
        "query": "26-",
        "pages": 2,
        "rows_returned": 3,
        "page_cap_hit": False,
        "show_more_mode": False,
        "records_new": 3,
    }
    # The overlapping query contributed nothing new, and says so.
    assert walked[1]["rows_returned"] == 1
    assert walked[1]["records_new"] == 0
    # Duplicates from deliberate overlap are not parse failures.
    assert result.parser_yield == 1.0


async def test_parser_yield_counts_parse_failures_not_duplicates() -> None:
    numberless = dict(_LICENSE_ROW, number="", projectNumber="")
    pages = {"26-": _pages([_SOLAR_ROW, numberless])}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await MaintStarPublicAdapter(_config(), client=client).collect()

    assert len(result.records) == 1
    assert result.metadata["rows_in_scope"] == 2
    assert result.metadata["rows_unparsed"] == 1
    assert result.parser_yield == 0.5


async def test_a_capped_run_does_not_look_like_a_complete_one() -> None:
    pages = {"26-": {0: [_SOLAR_ROW, _CODE_ROW], 2: [_SOLAR_ROW, _LICENSE_ROW]}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        adapter = MaintStarPublicAdapter(_config(max_pages_per_query=2), client=client)
        result = await adapter.collect()

    assert result.metadata["page_cap_hit"] is True
    assert result.metadata["capped_queries"] == ["26-"]
    assert result.metadata["queries_walked"][0]["pages"] == 2


async def test_disabled_anonymous_search_blocks_instead_of_hammering() -> None:
    calls: list[httpx.Request] = []
    handler = _handler(
        {"26-": _pages([_SOLAR_ROW])},
        portal_config={"agency": "riovista", "search": {"disableAnonymousSearch": True}},
        calls=calls,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = MaintStarPublicAdapter(_config(), client=client)
        with pytest.raises(SourceBlockedError):
            await adapter.collect()
        with pytest.raises(SourceBlockedError):
            await adapter.canary()

    # No search ever went out.
    assert all(request.url.path == _CONFIG_PATH for request in calls)


async def test_a_portal_that_stops_stating_the_flag_is_a_schema_change() -> None:
    handler = _handler(
        {"26-": _pages([_SOLAR_ROW])},
        portal_config={"agency": "riovista", "search": {}},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="disableAnonymousSearch"):
            await MaintStarPublicAdapter(_config(), client=client).collect()


async def test_canary_asserts_payload_shape_not_just_http_200() -> None:
    pages = {"26-": _pages([_SOLAR_ROW])}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        assert await MaintStarPublicAdapter(_config(), client=client).canary() is True

    stripped = dict(_SOLAR_ROW)
    for field in ("msType", "status"):
        stripped.pop(field)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler({"26-": _pages([stripped])}))
    ) as client:
        assert await MaintStarPublicAdapter(_config(), client=client).canary() is False

    # A search that answers 200 with no rows is not a healthy source either.
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler({}))) as client:
        adapter = MaintStarPublicAdapter(_config(min_expected_records=1), client=client)
        assert await adapter.canary() is False


async def test_anonymous_rejection_is_surfaced_as_blocked() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == _CONFIG_PATH:
            return httpx.Response(200, json=_PORTAL_CONFIG)
        return httpx.Response(403, text="no")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SourceBlockedError):
            await MaintStarPublicAdapter(_config(), client=client).collect()


async def test_requests_stay_on_the_configured_host() -> None:
    calls: list[httpx.Request] = []
    pages = {"26-": _pages([_SOLAR_ROW])}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler(pages, calls=calls))
    ) as client:
        await MaintStarPublicAdapter(_config(), client=client).collect()

    assert {request.url.host for request in calls} == {"h8.maintstar.co"}
    assert {request.headers["user-agent"] for request in calls} == {
        "Mozilla/5.0 (compatible; NS-Trackstar/0.1; +https://github.com/jonnyearlmedia/NS-trackstar)"
    }
