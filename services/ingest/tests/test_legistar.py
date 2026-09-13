import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.legistar import LegistarAdapter


@pytest.fixture
def config() -> SourceConfig:
    return SourceConfig(
        key="solano.legistar",
        name="Solano County Legistar",
        jurisdiction="Solano County",
        base_url="https://solano.legistar.com",
        poll_minutes=120,
        options={
            "api_base": "https://webapi.legistar.com/v1",
            "client_name": "solano",
            "portal_url": "https://solano.legistar.com",
            "lookback_days": 30,
            "lookahead_days": 120,
            "page_size": 100,
            "fetch_event_items": True,
            "min_request_interval_seconds": 0,
        },
    )


@pytest.mark.asyncio
async def test_collects_legistar_events_and_items(config: SourceConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/solano/Events/55/EventItems"):
            return httpx.Response(
                200,
                json=[
                    {
                        "EventItemId": 501,
                        "EventItemLastModifiedUtc": "2026-09-10T18:00:00-07:00",
                        "EventItemAgendaNumber": "12",
                        "EventItemAgendaSequence": 12,
                        "EventItemTitle": "Consider development agreement",
                        "EventItemActionName": "Approved",
                        "EventItemPassedFlagName": "Pass",
                        "EventItemMatterId": 9001,
                        "EventItemMatterFile": "26-123",
                        "EventItemMatterName": "Development Agreement",
                        "EventItemMatterType": "Resolution",
                        "EventItemMatterStatus": "Passed",
                        "EventItemMatterAttachments": [
                            {"MatterAttachmentId": 777, "MatterAttachmentName": "Staff Report"}
                        ],
                    }
                ],
            )
        if request.url.path.endswith("/solano/Events"):
            return httpx.Response(
                200,
                json=[
                    {
                        "EventId": 55,
                        "EventLastModifiedUtc": "2026-09-10T17:00:00-07:00",
                        "EventBodyId": 2,
                        "EventBodyName": "Board of Supervisors",
                        "EventDate": "2026-09-15T00:00:00-07:00",
                        "EventTime": "9:00 AM",
                        "EventAgendaStatusName": "Final",
                        "EventMinutesStatusName": "Draft",
                        "EventLocation": "675 Texas St",
                        "EventAgendaFile": "https://example.test/agenda.pdf",
                        "EventInSiteURL": "https://solano.legistar.com/MeetingDetail.aspx?ID=55",
                    }
                ],
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LegistarAdapter(config, client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert result.metadata["events_seen"] == 1
    assert len(result.records) == 2
    event = result.records[0]
    item = result.records[1]
    assert event.external_id == "event:55"
    assert event.normalized_payload["body_name"] == "Board of Supervisors"
    assert item.external_id == "event:55:item:501"
    assert item.normalized_payload["matter_file"] == "26-123"
    assert item.normalized_payload["action"] == "Approved"
    assert item.normalized_payload["attachments"][0]["MatterAttachmentName"] == "Staff Report"


@pytest.mark.asyncio
async def test_legistar_paginates_with_top_and_skip(config: SourceConfig) -> None:
    small_page_config = SourceConfig(
        key=config.key,
        name=config.name,
        jurisdiction=config.jurisdiction,
        base_url=config.base_url,
        poll_minutes=config.poll_minutes,
        options={**config.options, "page_size": 1, "fetch_event_items": False},
    )
    skips: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        skips.append(request.url.params.get("$skip"))
        skip = request.url.params.get("$skip")
        if skip is None:
            return httpx.Response(
                200,
                json=[{"EventId": 1, "EventDate": "2026-09-10T00:00:00-07:00"}],
            )
        if skip == "0":
            return httpx.Response(
                200,
                json=[{"EventId": 1, "EventDate": "2026-09-10T00:00:00-07:00"}],
            )
        if skip == "1":
            return httpx.Response(
                200,
                json=[{"EventId": 2, "EventDate": "2026-09-11T00:00:00-07:00"}],
            )
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LegistarAdapter(small_page_config, client=client)
        result = await adapter.collect()

    assert [record.external_id for record in result.records] == ["event:1", "event:2"]
    assert "0" in skips and "1" in skips and "2" in skips
