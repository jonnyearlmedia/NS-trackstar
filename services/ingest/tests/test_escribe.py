from __future__ import annotations

import json
from datetime import date
from itertools import pairwise
from zoneinfo import ZoneInfo

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.escribe import EScribeAdapter, parse_moment

PLANNING = {
    "ID": "30975001-455e-4c76-8975-35cb1f9e2055",
    "MeetingName": "Planning Commission",
    "MeetingType": "Planning Commission",
    "StartDate": "2026/09/15 18:00:21",
    "FormattedStart": "Tuesday, September 15, 2026 @ 6:00 PM",
    "Description": (
        "Vacaville City Hall Council Chamber<br/>650 Merchant Street<br/>Vacaville, CA 95688"
    ),
    "Location": "Vacaville City Hall Council Chamber",
    "Url": "https://pub-example.escribemeetings.com/MeetingsCalendarView.aspx/Meeting?Id=3097",
    "HasAgenda": True,
    "MeetingDocumentLink": [
        {
            "Title": "Agenda (PDF)",
            "Type": "AgendaCover",
            "Url": "/FileStream.ashx?DocumentId=2504",
        },
        {
            "Title": "Agenda Full Package",
            "Type": "AgendaPackage",
            "Url": "/FileStream.ashx?DocumentId=2505",
        },
    ],
}

COUNCIL = {
    "ID": "aaaa-2",
    "MeetingName": "Regular Meeting of the City Council",
    "MeetingType": "Regular Meeting of the City Council",
    "StartDate": "2026/06/09 17:00:00",
    "Description": "",
    "Location": "",
    "HasAgenda": False,
    "MeetingDocumentLink": [],
}

# The portal has no ID for this one. A record must not be invented for it.
UNIDENTIFIED = {"MeetingName": "Unidentified", "StartDate": "2026/06/10 17:00:00"}

CALENDAR = [PLANNING, COUNCIL, UNIDENTIFIED]


def build(*, status: int = 200, payload_key: str = "d", **options) -> EScribeAdapter:
    """An adapter talking to a portal that answers each calendar slice honestly.

    The fake filters by the requested range the way the real portal does, so an
    overlapping-slice bug shows up here as a duplicate rather than being hidden by a
    handler that returns the same fixture for every call.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="blocked")
        body = json.loads(request.content.decode())
        start = date.fromisoformat(body["calendarStartDate"])
        end = date.fromisoformat(body["calendarEndDate"])
        inside = [
            meeting
            for meeting in CALENDAR
            if start <= date.fromisoformat(meeting["StartDate"][:10].replace("/", "-")) <= end
        ]
        return httpx.Response(200, json={payload_key: inside})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EScribeAdapter(
        SourceConfig(
            key="vacaville.escribe",
            name="Vacaville eScribe",
            jurisdiction="City of Vacaville",
            base_url="https://pub-example.escribemeetings.com",
            poll_minutes=120,
            options={
                "portal_url": "https://pub-example.escribemeetings.com",
                "min_request_interval_seconds": 0,
                "min_expected_meetings": 1,
                "lookback_days": 365,
                "lookahead_days": 365,
                "slice_days": 90,
                **options,
            },
        ),
        client=client,
    )


def test_a_wall_clock_is_read_in_the_city_s_own_zone():
    zone = ZoneInfo("America/Los_Angeles")
    moment = parse_moment("2026/09/15 18:00:21", timezone=zone)

    assert moment is not None
    assert moment.tzinfo is not None
    assert moment.isoformat() == "2026-09-15T18:00:21-07:00"
    assert parse_moment("", timezone=zone) is None
    assert parse_moment("not a date", timezone=zone) is None


def test_the_window_is_requested_in_slices_that_cover_the_whole_range():
    adapter = build(lookback_days=100, lookahead_days=100, slice_days=60)
    windows = adapter._windows(today=date(2026, 6, 1))

    assert windows[0][0] == date(2026, 2, 21)
    assert windows[-1][1] == date(2026, 9, 9)
    # Slices meet end to end, so no day of the range goes unrequested.
    for earlier, later in pairwise(windows):
        assert earlier[1] == later[0]


@pytest.mark.asyncio
async def test_meetings_are_deduplicated_across_overlapping_windows():
    result = await build(lookback_days=200, lookahead_days=200, slice_days=120).collect()

    identities = [record.external_id for record in result.records]
    assert len(identities) == len(set(identities))
    # The meeting with no ID is not invented into a record.
    assert "Unidentified" not in [r.normalized_payload["meeting_title"] for r in result.records]


@pytest.mark.asyncio
async def test_the_venue_address_is_kept_separate_from_the_venue_name():
    result = await build().collect()
    planning = next(r for r in result.records if r.external_id.startswith("30975001"))
    payload = planning.normalized_payload

    assert payload["meeting_location"] == "Vacaville City Hall Council Chamber"
    assert payload["meeting_address"] == "650 Merchant Street Vacaville, CA 95688"
    assert payload["meeting_date"] == "2026-09-15"
    assert payload["agenda_url"].endswith("/FileStream.ashx?DocumentId=2504")
    assert len(payload["documents"]) == 2


@pytest.mark.asyncio
async def test_a_blocked_portal_is_reported_as_blocked_not_as_an_empty_run():
    with pytest.raises(SourceBlockedError):
        await build(status=403).collect()
    assert await build(status=403).canary() is False


@pytest.mark.asyncio
async def test_a_response_without_a_meeting_list_fails_the_canary():
    assert await build(payload_key="meetings").canary() is False
