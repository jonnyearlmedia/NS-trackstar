import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.civicclerk import CivicClerkAdapter, _wall_clock_datetime


@pytest.fixture
def source_config() -> SourceConfig:
    return SourceConfig(
        key="vallejo.civicclerk",
        name="Vallejo CivicClerk",
        jurisdiction="City of Vallejo",
        base_url="https://vallejoca.api.civicclerk.com/v1",
        poll_minutes=120,
        options={
            "api_base": "https://vallejoca.api.civicclerk.com/v1",
            "portal_url": "https://vallejoca.portal.civicclerk.com",
            "lookback_days": 30,
            "lookahead_days": 120,
            "fetch_agendas": True,
            "min_request_interval_seconds": 0,
            "retry_backoff_seconds": 0,
        },
    )


def test_wall_clock_datetime_does_not_shift_civicclerk_local_time() -> None:
    parsed = _wall_clock_datetime("2026-09-08T19:00:00Z")
    assert parsed is not None
    assert parsed.hour == 19
    assert parsed.tzinfo is None


@pytest.mark.asyncio
async def test_collects_events_and_flattens_structured_agenda(source_config: SourceConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/EventCategories"):
            return httpx.Response(200, json={"value": [{"id": 1, "categoryDesc": "Council"}]})
        if request.url.path.endswith("/Events"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": 42,
                            "eventDate": "2026-09-08T19:00:00Z",
                            "eventName": "Regular City Council Meeting",
                            "categoryId": 1,
                            "categoryName": "City Council",
                            "agendaId": 900,
                            "agendaName": "Agenda",
                            "publishedFiles": [{"fileId": 12001, "type": "Agenda"}],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/Meetings/900"):
            return httpx.Response(
                200,
                json={
                    "id": 900,
                    "items": [
                        {
                            "id": 10,
                            "agendaObjectItemName": "Consent Calendar",
                            "isSection": True,
                            "sortOrder": 1,
                            "childItems": [
                                {
                                    "id": 11,
                                    "agendaObjectItemName": "Approve development agreement",
                                    "isSection": False,
                                    "sortOrder": 2,
                                    "attachmentsList": [{"id": 77, "fileName": "Staff Report"}],
                                }
                            ],
                        }
                    ],
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CivicClerkAdapter(source_config, client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert result.metadata["events_seen"] == 1
    assert result.metadata["agendas_fetched"] == 1
    assert [record.external_id for record in result.records] == [
        "event:42",
        "event:42:agenda:900:item:10",
        "event:42:agenda:900:item:11",
    ]
    child = result.records[-1]
    assert child.normalized_payload["body"] == "City Council"
    assert child.normalized_payload["title"] == "Approve development agreement"
    assert child.normalized_payload["attachments"][0]["fileName"] == "Staff Report"


@pytest.mark.asyncio
async def test_retries_transient_read_timeout(source_config: SourceConfig) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path.endswith("/EventCategories"):
            attempts += 1
            if attempts == 1:
                raise httpx.ReadTimeout("temporary CivicClerk timeout", request=request)
            return httpx.Response(200, json={"value": []})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CivicClerkAdapter(source_config, client=client)
        assert await adapter.canary() is True

    assert attempts == 2


@pytest.mark.asyncio
async def test_rejects_cross_host_odata_continuation(source_config: SourceConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Events"):
            return httpx.Response(
                200,
                json={"value": [], "@odata.nextLink": "https://evil.example/v1/Events?$skip=15"},
            )
        return httpx.Response(200, json={"value": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CivicClerkAdapter(source_config, client=client)
        with pytest.raises(RuntimeError, match="left the configured public API host"):
            await adapter.collect()