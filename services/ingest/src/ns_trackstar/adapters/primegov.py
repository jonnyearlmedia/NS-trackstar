"""PrimeGov public meeting portals.

A PrimeGov town publishes two anonymous JSON endpoints that its own portal page
calls: upcoming meetings, and an archive requested one year at a time. Both are
read here with the same anonymous request the portal makes for any visitor.

The archive is requested year by year rather than as a range, because that is the
shape the endpoint takes. Requesting a span it does not understand would return
whatever the server defaulted to, and a default that silently means "this year"
would look like a town that stopped meeting in every earlier year.

Document links are deliberately not synthesised. The portal builds them from a
compiled-file identifier that these endpoints do not return, and a guessed
identifier resolves to the portal's own "document not published" page. So the
documents a meeting has are recorded by name, type and publish date, and the
canonical link stays the portal itself rather than a URL that would 404 for a
resident who tapped it.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_UPCOMING = "api/v2/PublicPortal/ListUpcomingMeetings"
_ARCHIVED = "api/v2/PublicPortal/ListArchivedMeetings"


def parse_moment(value: Any, *, timezone: ZoneInfo) -> datetime | None:
    """Read PrimeGov's `YYYY-MM-DDTHH:MM:SS` local wall clock as an aware moment."""

    text = " ".join(str(value or "").split())
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone)


class PrimeGovAdapter(CollectorAdapter):
    """Collect published meetings from a town's public PrimeGov portal."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.portal_url = str(config.options.get("portal_url") or config.base_url).rstrip("/")
        self.timezone = ZoneInfo(str(config.options.get("timezone", "America/Los_Angeles")))
        self.archive_years = max(1, int(config.options.get("archive_years", 2)))
        self.min_expected_meetings = int(config.options.get("min_expected_meetings", 1))
        # A town's own portal occasionally carries a vendor test record. Excluding one
        # is a curation decision, so it lives in config where it can be read and
        # argued with, never in adapter code, and the count of what was excluded is
        # reported so a broad pattern cannot quietly hollow the source out.
        self.exclude_title_patterns = [
            re.compile(str(pattern), re.IGNORECASE)
            for pattern in (config.options.get("exclude_title_patterns") or [])
        ]
        self.timeout_seconds = float(config.options.get("timeout_seconds", 45))
        self.min_request_interval_seconds = float(
            config.options.get("min_request_interval_seconds", 0.5)
        )

    def _years(self, *, today: datetime | None = None) -> list[int]:
        current = (today or datetime.now(self.timezone)).year
        return [current - offset for offset in range(self.archive_years)]

    async def _get(self, client: httpx.AsyncClient, path: str, **params: Any) -> list[Any]:
        response = await client.get(
            urljoin(f"{self.portal_url}/", path),
            params=params or None,
            headers={"User-Agent": "NS-Trackstar/0.1"},
        )
        if response.status_code in {401, 403, 429}:
            raise SourceBlockedError(
                "PrimeGov public portal request is explicitly blocked: "
                f"status={response.status_code} url={response.request.url}"
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise TypeError(
                f"PrimeGov portal response was not a meeting list; got {type(payload).__name__}"
            )
        return payload

    async def _fetch_all(
        self, *, today: datetime | None = None
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        found: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = {}
        try:
            for meeting in await self._get(client, _UPCOMING):
                if isinstance(meeting, dict) and meeting.get("id") is not None:
                    found[str(meeting["id"])] = meeting
            counts["upcoming"] = len(found)

            for year in self._years(today=today):
                if self.min_request_interval_seconds:
                    await asyncio.sleep(self.min_request_interval_seconds)
                meetings = await self._get(client, _ARCHIVED, year=year)
                counts[f"archive_{year}"] = len(meetings)
                for meeting in meetings:
                    if isinstance(meeting, dict) and meeting.get("id") is not None:
                        found.setdefault(str(meeting["id"]), meeting)
        finally:
            if owns:
                await client.aclose()
        return found, counts

    def _record(self, meeting: dict[str, Any]) -> NormalizedRecord | None:
        identity = str(meeting.get("id") or "").strip()
        title = " ".join(str(meeting.get("title") or "").split())
        if not identity or not title:
            return None

        start = parse_moment(meeting.get("dateTime"), timezone=self.timezone)
        documents = [
            {
                "name": " ".join(str(doc.get("templateName") or "").split()),
                "published_at": doc.get("publishDate"),
                # The API carries a link field for documents it publishes directly.
                # When it is null there is no public URL, and none is invented.
                "url": doc.get("link") or None,
            }
            for doc in (meeting.get("documentList") or [])
            if isinstance(doc, dict)
        ]

        normalized: dict[str, Any] = {
            "record_kind": "government_meeting",
            "meeting_title": title,
            "meeting_body": title,
            "meeting_date": start.date().isoformat() if start else None,
            "meeting_time_text": " ".join(
                f"{meeting.get('date') or ''} {meeting.get('time') or ''}".split()
            )
            or None,
            "meeting_location": " ".join(str(meeting.get("location") or "").split()) or None,
            "documents": documents,
            "document_names": sorted({doc["name"] for doc in documents if doc["name"]}),
            "video_url": meeting.get("videoUrl") or None,
            "project_page": self.portal_url,
        }

        return NormalizedRecord(
            source_key=self.config.key,
            external_id=identity,
            canonical_url=self.portal_url,
            source_updated_at=start,
            raw_payload=meeting,
            normalized_payload=normalized,
        )

    async def canary(self) -> bool:
        """Both endpoints must still answer with identified meetings.

        A town does not stop meeting, so an empty or reshaped response is a moved
        endpoint rather than a quiet zero-result run.
        """

        try:
            found, _ = await self._fetch_all()
        except (httpx.HTTPError, SourceBlockedError, TypeError, ValueError):
            return False
        return len(found) >= self.min_expected_meetings

    def _excluded(self, record: NormalizedRecord) -> bool:
        title = str(record.normalized_payload["meeting_title"])
        return any(pattern.search(title) for pattern in self.exclude_title_patterns)

    async def collect(self) -> CollectorResult:
        found, counts = await self._fetch_all()
        parsed = [record for record in map(self._record, found.values()) if record is not None]
        records = [record for record in parsed if not self._excluded(record)]
        excluded = [
            str(record.normalized_payload["meeting_title"])
            for record in parsed
            if self._excluded(record)
        ]

        keys = sorted({key for meeting in found.values() for key in meeting})
        fingerprint = hashlib.sha256("|".join(keys).encode()).hexdigest() if keys else None
        return CollectorResult(
            records=records,
            schema_fingerprint=fingerprint,
            # Yield measures parsing, not curation, so it is computed before exclusion.
            parser_yield=(len(parsed) / len(found)) if found else 0.0,
            metadata={
                "portal_url": self.portal_url,
                "meetings_seen": len(found),
                "meetings_excluded": sorted(set(excluded)),
                "meetings_by_request": counts,
                "meeting_titles_seen": sorted(
                    {str(record.normalized_payload["meeting_title"]) for record in records}
                ),
            },
        )
