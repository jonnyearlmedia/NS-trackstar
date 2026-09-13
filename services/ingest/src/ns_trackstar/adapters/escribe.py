"""eScribe public meeting portals.

An eScribe city publishes its meetings twice. The staff-facing app at
`<client>.escribemeetings.com` is a single-page application whose API is not
anonymous, and the public portal at `pub-<client>.escribemeetings.com` is an
ordinary server-rendered page whose own calendar widget reads a plain JSON
endpoint. This adapter calls that same public endpoint, with the same anonymous
request the portal makes for any visitor.

The window is requested in explicit slices rather than as one open-ended range,
because the portal answers a calendar range and a city that publishes years of
archive would otherwise return whatever the server felt like capping at. Slicing
also means a single slow year cannot silently truncate the rest.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_MARKUP = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"(?i)<br\s*/?>")


def _lines(value: str) -> list[str]:
    """Return a portal description as its rendered lines.

    The portal writes a meeting's venue as one string with `<br/>` separators, so the
    breaks carry the address structure and must not be flattened away.
    """

    parts = [_MARKUP.sub(" ", part) for part in _BREAK.split(str(value or ""))]
    return [" ".join(part.replace("\xa0", " ").split()) for part in parts if part.strip()]


def parse_moment(value: Any, *, timezone: ZoneInfo) -> datetime | None:
    """Parse the portal's `YYYY/MM/DD HH:MM:SS` local wall clock into an aware moment."""

    text = " ".join(str(value or "").split())
    if not text:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            # The portal states a local wall clock with no offset, so the city's own
            # zone is attached here rather than guessed later.
            return datetime.strptime(text, fmt).replace(tzinfo=timezone)
        except ValueError:
            continue
    return None


class EScribeAdapter(CollectorAdapter):
    """Collect published meetings from a city's public eScribe portal."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.portal_url = str(config.options.get("portal_url") or config.base_url).rstrip("/")
        self.timezone = ZoneInfo(str(config.options.get("timezone", "America/Los_Angeles")))
        self.lookback_days = int(config.options.get("lookback_days", 365))
        self.lookahead_days = int(config.options.get("lookahead_days", 180))
        self.slice_days = max(1, int(config.options.get("slice_days", 120)))
        self.min_expected_meetings = int(config.options.get("min_expected_meetings", 1))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 45))
        self.min_request_interval_seconds = float(
            config.options.get("min_request_interval_seconds", 0.5)
        )

    def _windows(self, *, today: date | None = None) -> list[tuple[date, date]]:
        reference = today or datetime.now(self.timezone).date()
        start = reference - timedelta(days=self.lookback_days)
        end = reference + timedelta(days=self.lookahead_days)
        windows: list[tuple[date, date]] = []
        cursor = start
        while cursor < end:
            stop = min(cursor + timedelta(days=self.slice_days), end)
            windows.append((cursor, stop))
            cursor = stop
        return windows

    async def _post(self, client: httpx.AsyncClient, window: tuple[date, date]) -> list[Any]:
        start, end = window
        response = await client.post(
            urljoin(f"{self.portal_url}/", "MeetingsCalendarView.aspx/GetCalendarMeetings"),
            json={"calendarStartDate": start.isoformat(), "calendarEndDate": end.isoformat()},
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NS-Trackstar/0.1",
            },
        )
        if response.status_code in {401, 403, 429}:
            raise SourceBlockedError(
                "eScribe public calendar request is explicitly blocked: "
                f"status={response.status_code} url={response.request.url}"
            )
        response.raise_for_status()
        payload = response.json()
        meetings = payload.get("d")
        if not isinstance(meetings, list):
            raise TypeError(
                "eScribe calendar response did not carry a meeting list; "
                f"got {type(meetings).__name__}"
            )
        return meetings

    async def _fetch_all(self, *, today: date | None = None) -> dict[str, dict[str, Any]]:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        found: dict[str, dict[str, Any]] = {}
        try:
            for index, window in enumerate(self._windows(today=today)):
                if index and self.min_request_interval_seconds:
                    await asyncio.sleep(self.min_request_interval_seconds)
                for meeting in await self._post(client, window):
                    if not isinstance(meeting, dict):
                        continue
                    identity = meeting.get("ID")
                    if identity:
                        found[str(identity)] = meeting
        finally:
            if owns:
                await client.aclose()
        return found

    def _record(self, meeting: dict[str, Any]) -> NormalizedRecord | None:
        identity = str(meeting.get("ID") or "").strip()
        name = " ".join(str(meeting.get("MeetingName") or "").split())
        if not identity or not name:
            return None

        start = parse_moment(meeting.get("StartDate"), timezone=self.timezone)
        venue_lines = _lines(meeting.get("Description"))
        documents = [
            {
                "title": " ".join(str(link.get("Title") or "").split()),
                "type": link.get("Type"),
                "url": urljoin(f"{self.portal_url}/", str(link.get("Url") or "").lstrip("/")),
            }
            for link in (meeting.get("MeetingDocumentLink") or [])
            if isinstance(link, dict) and link.get("Url")
        ]

        normalized: dict[str, Any] = {
            "record_kind": "government_meeting",
            "meeting_title": name,
            "meeting_body": " ".join(str(meeting.get("MeetingType") or name).split()),
            "meeting_date": start.date().isoformat() if start else None,
            "meeting_time_text": " ".join(str(meeting.get("FormattedStart") or "").split()) or None,
            "meeting_location": " ".join(str(meeting.get("Location") or "").split()) or None,
            # The first line repeats the venue name the portal already gives as
            # Location, so the street address is what follows it.
            "meeting_address": " ".join(venue_lines[1:]) or None,
            "has_agenda": bool(meeting.get("HasAgenda")),
            "documents": documents,
            "agenda_url": next(
                (doc["url"] for doc in documents if str(doc.get("type")) == "AgendaCover"),
                None,
            ),
        }

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=identity,
            canonical_url=str(meeting.get("Url") or self.portal_url),
            source_updated_at=start,
            raw_payload=meeting,
            normalized_payload=normalized,
        )

    async def canary(self) -> bool:
        """The portal must still answer its own calendar call with identified meetings.

        A city does not stop meeting. An empty or unparseable calendar is a moved
        endpoint or a blocked request, so it fails rather than passing as a quiet run.
        """

        try:
            found = await self._fetch_all()
        except (httpx.HTTPError, SourceBlockedError, TypeError, ValueError):
            return False
        return len(found) >= self.min_expected_meetings

    async def collect(self) -> CollectorResult:
        found = await self._fetch_all()
        records = [record for record in map(self._record, found.values()) if record is not None]

        keys = sorted({key for meeting in found.values() for key in meeting})
        fingerprint = hashlib.sha256("|".join(keys).encode()).hexdigest() if keys else None
        bodies = sorted({str(record.normalized_payload["meeting_body"]) for record in records})
        return CollectorResult(
            records=records,
            schema_fingerprint=fingerprint,
            parser_yield=(len(records) / len(found)) if found else 0.0,
            metadata={
                "portal_url": self.portal_url,
                "meetings_in_calendar": len(found),
                "windows_requested": len(self._windows()),
                "meeting_bodies_seen": bodies,
            },
        )
