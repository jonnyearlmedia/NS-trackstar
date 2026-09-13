from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.primegov import PrimeGovAdapter, parse_moment

UPCOMING = [
    {
        "id": 1330,
        "title": "Zoning and Design Review Board (ZDRB) Regular Meeting",
        "dateTime": "2026-09-14T14:00:00",
        "date": "Sep 14, 2026",
        "time": "02:00 PM",
        "location": "Vintage House Board Room 6541 Washington Street",
        "videoUrl": "https://yountvilleca.new.swagit.com/events/49137",
        "documentList": [
            {"templateName": "Agenda", "publishDate": "2026-09-11T21:52:05.383", "link": None},
            {"templateName": "Agenda Packet", "publishDate": "2026-09-11T21:52:06", "link": "/x.pdf"},
        ],
    },
    {"id": 1331, "title": "PRIMEGOV FORM SUBMISSION TEST OD", "dateTime": "2026-09-01T09:00:00"},
    {"title": "No identity", "dateTime": "2026-09-02T09:00:00"},
]

ARCHIVE = {
    2026: [
        {"id": 1232, "title": "Town Council Regular Meeting", "dateTime": "2026-01-05T16:00:00"},
        # Also present in the upcoming list. One record, not two.
        {"id": 1330, "title": "Zoning and Design Review Board (ZDRB) Regular Meeting",
         "dateTime": "2026-09-14T14:00:00"},
    ],
    2025: [{"id": 900, "title": "Town Council Regular Meeting", "dateTime": "2025-03-04T16:00:00"}],
}


def build(*, status: int = 200, archive_payload: object | None = None, **options):
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="blocked")
        if request.url.path.endswith("ListUpcomingMeetings"):
            return httpx.Response(200, json=UPCOMING)
        if archive_payload is not None:
            return httpx.Response(200, json=archive_payload)
        year = int(request.url.params.get("year", 0))
        return httpx.Response(200, json=ARCHIVE.get(year, []))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PrimeGovAdapter(
        SourceConfig(
            key="yountville.primegov",
            name="Yountville PrimeGov",
            jurisdiction="Town of Yountville",
            base_url="https://town.primegov.example",
            poll_minutes=120,
            options={
                "portal_url": "https://town.primegov.example",
                "min_request_interval_seconds": 0,
                "min_expected_meetings": 1,
                "archive_years": 2,
                **options,
            },
        ),
        client=client,
    )


def test_a_wall_clock_is_read_in_the_town_s_own_zone():
    zone = ZoneInfo("America/Los_Angeles")
    moment = parse_moment("2026-09-14T14:00:00", timezone=zone)

    assert moment is not None
    assert moment.isoformat() == "2026-09-14T14:00:00-07:00"
    assert parse_moment(None, timezone=zone) is None


def test_the_archive_is_requested_one_year_at_a_time():
    adapter = build(archive_years=3)
    assert adapter._years(today=datetime(2026, 9, 13, tzinfo=ZoneInfo("America/Los_Angeles"))) == [
        2026,
        2025,
        2024,
    ]


@pytest.mark.asyncio
async def test_a_meeting_in_both_lists_becomes_one_record():
    result = await build().collect()

    identities = [record.external_id for record in result.records]
    assert sorted(identities) == ["1232", "1330", "1331", "900"]
    assert result.metadata["meetings_by_request"] == {
        "upcoming": 2,
        "archive_2026": 2,
        "archive_2025": 1,
    }


@pytest.mark.asyncio
async def test_a_document_without_a_published_link_never_gets_an_invented_one():
    result = await build().collect()
    zdrb = next(record for record in result.records if record.external_id == "1330")
    documents = zdrb.normalized_payload["documents"]

    assert [doc["name"] for doc in documents] == ["Agenda", "Agenda Packet"]
    assert documents[0]["url"] is None
    assert documents[1]["url"] == "/x.pdf"
    assert zdrb.canonical_url == "https://town.primegov.example"


@pytest.mark.asyncio
async def test_an_excluded_vendor_test_record_is_named_rather_than_silently_dropped():
    result = await build(exclude_title_patterns=["^PRIMEGOV FORM SUBMISSION TEST"]).collect()

    assert "1331" not in {record.external_id for record in result.records}
    assert result.metadata["meetings_excluded"] == ["PRIMEGOV FORM SUBMISSION TEST OD"]
    # Exclusion is curation, so it must not read as a parser that started failing.
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_a_blocked_portal_is_reported_as_blocked_not_as_an_empty_run():
    with pytest.raises(SourceBlockedError):
        await build(status=403).collect()
    assert await build(status=403).canary() is False


@pytest.mark.asyncio
async def test_a_reshaped_archive_response_fails_the_canary():
    assert await build(archive_payload={"meetings": []}).canary() is False
