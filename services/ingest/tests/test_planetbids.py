import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.planetbids import PlanetBidsAdapter

_AGENCY = {
    "data": {
        "type": "agencies",
        "id": "42510",
        "attributes": {"companyName": "City of Vallejo", "moduleBo": True},
    }
}

_BID_ROW = {
    "type": "bids",
    "id": "144506",
    "attributes": {
        "bidId": 144506,
        "title": "Lake Curry Dam Maintenance Construction Services",
        "invitationNum": "",
        "issueDate": "2026-08-11 11:04:35.363",
        "bidDueDate": "2026-09-17 14:00:00.000",
        "stageId": 3,
        "stageStr": "Bidding",
        "bidTypeId": 1,
        "bidResponseFormatStr": "Paper",
        "byInvitation": False,
        "categoryIds": "236210, 236220, 237990",
        "companyId": 42510,
    },
}

_DETAIL = {
    "data": {
        "type": "bid-details",
        "id": "144506",
        "attributes": {
            "bidId": 144506,
            "title": "Lake Curry Dam Maintenance Construction Services",
            "address1": "555 Santa Clara St.",
            "address2": "3FL - Public Works",
            "city": "Vallejo",
            "legacyCounty": "Solano",
            "zipCode": "94590",
            "contactNameAndPhone": "Ivette Iraheta",
            "contactEmail": "ivette.iraheta@cityofvallejo.net",
            "scope": "  Maintenance   of the dam  ",
            "awardDate": "",
        },
    }
}

_FILES = {
    "data": [
        {
            "type": "bid-downloadable-files",
            "id": "635494",
            "attributes": {
                "fileTitle": "Attachment C",
                "filename": "plans.pdf",
                "fileSize": 9639662,
                "uploadedDate": "2026-07-29 08:42:02.280",
                "publiclyVisible": False,
                "recalled": False,
                "serverFullPath": "files-prod01.planetbids.com/Vallejo/BMfiles/",
                "serverFilename": "20260729084202280 plans.pdf",
            },
        }
    ]
}


def _config(**options: object) -> SourceConfig:
    base: dict[str, object] = {
        "agency_id": "42510",
        "min_request_interval_seconds": 0,
        "per_page": 30,
    }
    base.update(options)
    return SourceConfig(
        key="vallejo.planetbids",
        name="Vallejo PlanetBids",
        jurisdiction="City of Vallejo",
        base_url="https://vendors.planetbids.com/portal/42510",
        poll_minutes=360,
        options=base,
    )


def _handler(*, pages: int = 1, throttle_files: int = 0):
    state = {"throttled": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/papi/agencies/42510"):
            return httpx.Response(200, json=_AGENCY)
        if path == "/papi/bids":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(
                200,
                json={"data": [_BID_ROW], "meta": {"totalBids": pages, "totalPages": pages}}
                if page <= pages
                else {"data": [], "meta": {"totalBids": pages, "totalPages": pages}},
            )
        if path.endswith("/papi/bid-details/144506"):
            return httpx.Response(200, json=_DETAIL)
        if path == "/papi/bid-downloadable-files":
            if state["throttled"] < throttle_files:
                state["throttled"] += 1
                return httpx.Response(202, content=b"")
            return httpx.Response(200, json=_FILES)
        return httpx.Response(404)

    return handle


@pytest.mark.asyncio
async def test_collect_reads_the_portals_own_query_and_keeps_the_agencys_stage_word() -> None:
    seen: list[httpx.Request] = []

    handle = _handler()

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
        adapter = PlanetBidsAdapter(_config(), client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 1
    assert result.parser_yield == 1.0
    record_one = result.records[0]
    assert record_one.external_id == "planetbids:42510:144506"
    assert record_one.canonical_url.endswith("/portal/42510/bo/bo-detail/144506")

    payload = record_one.normalized_payload
    # The agency's own word for the stage is kept, not folded into a lifecycle guess.
    assert payload["stage"] == "Bidding"
    assert payload["naics_codes"] == ["236210", "236220", "237990"]
    assert payload["city"] == "Vallejo"
    assert payload["county"] == "Solano"
    assert payload["address"] == "555 Santa Clara St. 3FL - Public Works"
    assert payload["scope"] == "Maintenance of the dam"
    assert payload["document_count"] == 1

    # Documents are recorded by name; no download URL is stitched together from the
    # server path the API happens to expose.
    assert "serverFullPath" not in str(payload["documents"])

    listing = next(r for r in seen if r.url.path == "/papi/bids")
    assert listing.url.params["cid"] == "42510"
    assert listing.url.params["stage_id"] == "0"
    assert listing.headers["referer"] == "https://vendors.planetbids.com/"

    detail = next(r for r in seen if "bid-details" in r.url.path)
    # The detail endpoint answers 400 without this header while the list answers fine.
    assert detail.headers["company-id"] == "42510"


@pytest.mark.asyncio
async def test_empty_202_is_waited_out_rather_than_read_as_no_documents(monkeypatch) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("ns_trackstar.adapters.planetbids.asyncio.sleep", fake_sleep)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(throttle_files=2))) as client:
        adapter = PlanetBidsAdapter(_config(), client=client)
        result = await adapter.collect()

    assert result.records[0].normalized_payload["document_count"] == 1
    assert slept == [2.0, 5.0]
    assert result.metadata["throttled_waits"] == 2


@pytest.mark.asyncio
async def test_a_throttle_that_never_clears_is_raised_not_reported_as_empty(monkeypatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("ns_trackstar.adapters.planetbids.asyncio.sleep", fake_sleep)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(throttle_files=99))) as client:
        adapter = PlanetBidsAdapter(_config(), client=client)
        with pytest.raises(RuntimeError, match="kept throttling"):
            await adapter.collect()


@pytest.mark.asyncio
async def test_direct_access_refusal_is_a_broken_collector_not_an_empty_source() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"errors": [{"code": "DIRECT_ACCESS", "detail": "Could not process the request"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = PlanetBidsAdapter(_config(), client=client)
        with pytest.raises(RuntimeError, match="DIRECT_ACCESS"):
            await adapter.canary()


@pytest.mark.asyncio
async def test_agency_with_the_module_switched_off_is_blocked_not_failed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "type": "agencies",
                    "id": "9",
                    "attributes": {"companyName": "Town of Nowhere", "moduleBo": False},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = PlanetBidsAdapter(_config(agency_id="9"), client=client)
        with pytest.raises(SourceBlockedError, match="switched off"):
            await adapter.canary()


@pytest.mark.asyncio
async def test_a_capped_run_says_it_is_capped() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(pages=5))) as client:
        adapter = PlanetBidsAdapter(_config(max_pages=2, fetch_details=False, fetch_documents=False), client=client)
        result = await adapter.collect()

    assert result.metadata["pages_capped"] is True
    assert result.metadata["bids_reported_by_agency"] == 5
