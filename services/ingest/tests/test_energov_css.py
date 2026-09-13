import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.energov_css import EnerGovCivicAccessAdapter

_BASE = "https://dixonca-energovweb.tylerhost.net/apps/selfservice"

_TEMPLATE = {
    "Keyword": "",
    "ExactMatch": False,
    "SearchModule": 1,
    "FilterModule": 0,
    "PlanCriteria": {"PlanNumber": None, "PageNumber": 0, "PageSize": 0},
    "PermitCriteria": {"PermitNumber": None, "PageNumber": 0, "PageSize": 0},
    "CodeCaseCriteria": {"CodeCaseNumber": None, "PageNumber": 0, "PageSize": 0},
    "PageNumber": 0,
    "PageSize": 0,
    "SortBy": None,
    "SortAscending": False,
}

_CENSUS = {
    "PermitsFound": 17192,
    "PlansFound": 142,
    "InspectionsFound": 59980,
    "CodeCasesFound": 269,
    "LicensesFound": 14817,
    "ProjectsFound": 5,
    "TotalFound": 92405,
}


def _now(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).replace(tzinfo=None).isoformat()


def _permit(number: str, *, days_ago: float) -> dict:
    return {
        "CaseId": f"guid-{number}",
        "CaseNumber": number,
        "CaseType": "Fire Sprinkler System Permit",
        "CaseWorkclass": "Fire Sprinkler System",
        "CaseStatus": "Submitted - Online",
        "ProjectName": None,
        "ApplyDate": _now(days_ago),
        "IssueDate": None,
        "ExpireDate": None,
        "ModuleName": 2,
        "MainParcel": "0114012100",
        "Description": "  New   sprinkler riser ",
        "AddressDisplay": "1450 RED TRUMPET AVENUE Dixon CA 95620",
        "Address": {
            "AddressLine1": "1450 RED TRUMPET AVENUE",
            "UnitOrSuite": "",
            "City": "Dixon",
            "StateName": "CA",
            "PostalCode": "95620",
            "FullAddress": "1450 RED TRUMPET AVENUE Dixon CA 95620",
        },
    }


def _code_case(number: str, *, days_ago: float) -> dict:
    return {
        "CaseId": f"guid-{number}",
        "CaseNumber": number,
        "CaseType": "Code Enforcement (Police)",
        "CaseWorkclass": None,
        "CaseStatus": "Complaint Received",
        # Code cases sort on OpenedDate and then report that moment in ApplyDate,
        # leaving OpenedDate null on every row.
        "OpenedDate": None,
        "ApplyDate": _now(days_ago),
        "ModuleName": 5,
        "MainParcel": "0111200030",
        "Address": {"FullAddress": "148 VAUGHN ROAD Dixon CA 95620", "City": "Dixon"},
    }


def _config(**options: object) -> SourceConfig:
    base: dict[str, object] = {
        "tenant_name": "dixoncaprod",
        "record_types": ["permit", "code_case"],
        "page_size": 2,
        "min_request_interval_seconds": 0,
        "recency_days": 30,
    }
    base.update(options)
    return SourceConfig(
        key="dixon.energov-smoke",
        name="Dixon Civic Access",
        jurisdiction="City of Dixon",
        base_url=_BASE,
        poll_minutes=720,
        options=base,
    )


def _ok(result: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "Result": result,
            "Success": True,
            "ErrorMessage": "",
            "StatusCode": 200,
            "BrokenRules": [],
        },
    )


def _handler(pages: dict[int, list[list[dict]]], *, seen: list[httpx.Request] | None = None):
    """Serve the criteria template and one page list per FilterModule."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/api/energov/search/criteria"):
            return _ok(dict(_TEMPLATE))
        body = request.read()
        payload = json.loads(body) if body else {}
        module = payload.get("FilterModule")
        page = payload.get("PageNumber", 1)
        if module == 1:
            return _ok({**_CENSUS, "EntityResults": [], "TotalPages": 1})
        rows_by_page = pages.get(module, [])
        rows = rows_by_page[page - 1] if 0 < page <= len(rows_by_page) else []
        return _ok({"EntityResults": rows, "TotalFound": sum(len(p) for p in rows_by_page)})

    return handle


@pytest.mark.asyncio
async def test_collect_scopes_by_filter_module_and_keeps_the_agencys_own_words() -> None:
    seen: list[httpx.Request] = []
    pages = {
        2: [[_permit("FIREC-004257-2026", days_ago=1), _permit("FIREC-004151-2026", days_ago=2)]],
        5: [[_code_case("CE26-0255", days_ago=1)]],
    }
    transport = httpx.MockTransport(_handler(pages, seen=seen))

    async with httpx.AsyncClient(transport=transport) as client:
        adapter = EnerGovCivicAccessAdapter(_config(), client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 3
    assert result.parser_yield == 1.0

    permit = result.records[0]
    assert permit.external_id == "energov:dixoncaprod:permit:guid-FIREC-004257-2026"
    assert permit.canonical_url == f"{_BASE}/#/permit/guid-FIREC-004257-2026"
    payload = permit.normalized_payload
    # Tyler and the agency's own vocabulary, stored as written.
    assert payload["case_status"] == "Submitted - Online"
    assert payload["case_type"] == "Fire Sprinkler System Permit"
    assert payload["case_workclass"] == "Fire Sprinkler System"
    assert "lifecycle_state" not in payload
    assert payload["parcel_number"] == "0114012100"
    assert payload["address"] == "1450 RED TRUMPET AVENUE Dixon CA 95620"
    assert payload["description"] == "New sprinkler riser"
    # The raw row is preserved alongside the normalized one.
    assert permit.raw_payload["result"]["CaseId"] == "guid-FIREC-004257-2026"

    code_case = result.records[-1]
    assert code_case.canonical_url == f"{_BASE}/#/code/guid-CE26-0255"
    assert code_case.normalized_payload["record_kind"] == "code_case"

    searches = [r for r in seen if r.url.path.endswith("/search/search")]
    bodies = [json.loads(r.read()) for r in searches]
    # SearchModule scoped to one module answers HTTP 500; FilterModule is what
    # actually narrows the search, and SearchModule stays 1 throughout.
    assert {b["SearchModule"] for b in bodies} == {1}
    assert {b["FilterModule"] for b in bodies} >= {1, 2, 5}
    # Each module sorts on the field its own index will accept, newest first.
    by_module = {b["FilterModule"]: b for b in bodies}
    assert by_module[2]["SortBy"] == "ApplyDate"
    assert by_module[5]["SortBy"] == "OpenedDate"
    assert by_module[2]["SortAscending"] is False

    headers = searches[0].headers
    assert headers["tenantid"] == "1"
    assert headers["tenantname"] == "dixoncaprod"
    assert headers["tyler-tenanturl"] == "dixoncaprod"
    assert headers["tyler-tenant-culture"] == "en-US"
    assert headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_metadata_reports_the_agencys_census_next_to_what_was_kept() -> None:
    pages = {2: [[_permit("A", days_ago=1)]], 5: [[_code_case("B", days_ago=1)]]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await EnerGovCivicAccessAdapter(_config(), client=client).collect()

    meta = result.metadata
    # What the agency says exists, including the modules this run does not collect.
    assert meta["agency_reports"]["TotalFound"] == 92405
    assert meta["agency_reports"]["InspectionsFound"] == 59980
    assert meta["agency_reports"]["LicensesFound"] == 14817
    # And what was actually kept.
    assert meta["records_kept"] == 2
    assert meta["record_types"] == ["permit", "code_case"]
    assert meta["case_statuses"] == {"Submitted - Online": 1, "Complaint Received": 1}
    assert meta["modules"]["permit"]["rows_kept"] == 1
    assert meta["modules"]["code_case"]["sort_by"] == "OpenedDate"


@pytest.mark.asyncio
async def test_recency_window_stops_the_walk_and_is_not_counted_as_a_parse_failure() -> None:
    pages = {
        2: [
            [_permit("NEW-1", days_ago=1), _permit("NEW-2", days_ago=2)],
            [_permit("OLD-1", days_ago=400), _permit("OLD-2", days_ago=500)],
            [_permit("NEVER-READ", days_ago=600)],
        ],
        5: [[]],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await EnerGovCivicAccessAdapter(_config(), client=client).collect()

    numbers = [r.normalized_payload["record_number"] for r in result.records]
    assert numbers == ["NEW-1", "NEW-2"]

    permit = result.metadata["modules"]["permit"]
    assert permit["rows_fetched"] == 4
    assert permit["rows_outside_window"] == 2
    assert permit["stopped_at_recency_window"] is True
    assert permit["pages_walked"] == 2
    # parser_yield measures parse success over the rows in scope. Two rows were
    # filtered out by the window and neither is a parse failure, so a run that
    # read everything it meant to read reads 1.0.
    assert result.metadata["rows_in_scope"] == 2
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_unparsable_row_lowers_parser_yield_below_one() -> None:
    broken = _permit("X", days_ago=1)
    broken["CaseNumber"] = "   "
    pages = {2: [[_permit("GOOD", days_ago=1), broken]], 5: [[]]}

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await EnerGovCivicAccessAdapter(_config(), client=client).collect()

    assert len(result.records) == 1
    assert result.metadata["rows_in_scope"] == 2
    assert result.metadata["rows_unparsed"] == 1
    assert result.parser_yield == 0.5


@pytest.mark.asyncio
async def test_a_page_cap_short_of_the_agencys_count_is_reported_not_hidden() -> None:
    pages = {2: [[_permit(f"P{i}", days_ago=1), _permit(f"Q{i}", days_ago=1)] for i in range(5)]}
    config = _config(record_types=["permit"], max_pages_per_module=2, recency_days=None)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await EnerGovCivicAccessAdapter(config, client=client).collect()

    permit = result.metadata["modules"]["permit"]
    assert permit["pages_walked"] == 2
    assert permit["pages_capped"] is True
    assert permit["rows_fetched"] == 4
    assert permit["reported_by_agency"] == 10
    assert result.metadata["modules_incompletely_walked"] == ["permit"]
    assert result.metadata["window_walked_to_completion"] is False
    # A truncated walk is still a clean parse.
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_deep_paging_ceiling_is_named_rather_than_read_as_the_end_of_the_data() -> None:
    # The index serves no offset past 10,000 rows; at page_size 100 that is page 100.
    full = [[_permit(f"R{p}-{i}", days_ago=1) for i in range(100)] for p in range(200)]
    config = _config(record_types=["permit"], page_size=100, max_pages_per_module=500,
                     max_pages_per_run=500, recency_days=None)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler({2: full}))) as client:
        result = await EnerGovCivicAccessAdapter(config, client=client).collect()

    permit = result.metadata["modules"]["permit"]
    assert permit["pages_walked"] == 100
    assert permit["deep_paging_ceiling_reached"] is True
    assert permit["pages_capped"] is False
    assert result.metadata["window_walked_to_completion"] is False


@pytest.mark.asyncio
async def test_missing_tenant_headers_surface_as_the_header_trap_not_a_dead_route() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"Message": "An error has occurred."})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EnerGovCivicAccessAdapter(_config(), client=client)
        with pytest.raises(RuntimeError, match="tenantName"):
            await adapter.canary()


@pytest.mark.asyncio
async def test_a_refused_sort_is_raised_rather_than_recorded_as_an_empty_jurisdiction() -> None:
    """HTTP 200 with a null Result is a refusal, and must never read as zero records."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search/criteria"):
            return _ok(dict(_TEMPLATE))
        return httpx.Response(
            200,
            json={
                "Result": None,
                "Success": False,
                "ErrorMessage": "There was an unexpected error. ErrorId: 4ac5e774",
                "StatusCode": 200,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EnerGovCivicAccessAdapter(_config(), client=client)
        with pytest.raises(RuntimeError, match="null Result"):
            await adapter.collect()


@pytest.mark.asyncio
async def test_canary_asserts_payload_shape_not_merely_an_http_200() -> None:
    """A 200 carrying the wrong shape must fail the canary."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search/criteria"):
            return _ok(dict(_TEMPLATE))
        return _ok(
            {
                "TotalFound": 3,
                "PermitsFound": 3,
                "EntityResults": [{"CaseId": "g", "CaseNumber": "P-1", "ModuleName": 2}],
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EnerGovCivicAccessAdapter(_config(), client=client)
        # CaseType and CaseStatus are missing, so the shape contract is broken.
        assert await adapter.canary() is False


@pytest.mark.asyncio
async def test_canary_fails_when_filter_module_stops_filtering() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search/criteria"):
            return _ok(dict(_TEMPLATE))
        row = _permit("P-1", days_ago=1)
        row["ModuleName"] = 8  # a licence answered a permit-scoped request
        return _ok({"PermitsFound": 1, "TotalFound": 1, "EntityResults": [row]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await EnerGovCivicAccessAdapter(_config(), client=client).canary() is False


@pytest.mark.asyncio
async def test_a_row_from_the_wrong_module_is_excluded_and_counted() -> None:
    stray = _permit("STRAY", days_ago=1)
    stray["ModuleName"] = 8
    pages = {2: [[_permit("REAL", days_ago=1), stray]], 5: [[]]}

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages))) as client:
        result = await EnerGovCivicAccessAdapter(_config(), client=client).collect()

    assert [r.normalized_payload["record_number"] for r in result.records] == ["REAL"]
    assert result.metadata["modules"]["permit"]["rows_wrong_module"] == 1
    # Not a parse failure either.
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_forbidden_is_reported_as_blocked_rather_than_broken() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SourceBlockedError):
            await EnerGovCivicAccessAdapter(_config(), client=client).canary()


def test_an_unknown_record_type_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="no such Civic Access module"):
        EnerGovCivicAccessAdapter(_config(record_types=["permit", "parking_ticket"]))


def test_tenant_name_is_required_because_it_is_sent_as_three_headers() -> None:
    with pytest.raises(ValueError, match="tenant_name"):
        EnerGovCivicAccessAdapter(_config(tenant_name=""))
