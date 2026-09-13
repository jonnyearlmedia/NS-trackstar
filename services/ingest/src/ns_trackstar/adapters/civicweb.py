"""CivicWeb meeting portals.

A CivicWeb city publishes its meetings as one list page per portal, where each
entry links to a meeting page by numeric id and the link text carries the body and
the meeting date: "City Council - Regular Meeting - Sep 15 2026". Clerks prefix
status notes onto the same text ("*Amended Agenda*", "*** CANCELLED***"), so the
prefix is separated and kept rather than being left to corrupt the body name.

The portal exposes no JSON API. Its `/api/meetings` route answers 500 for an
anonymous caller, so this reads the same list page a visitor reads.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_MEETING_LINK = re.compile(r"MeetingInformation\.aspx", re.IGNORECASE)
# A clerk sometimes appends a parenthetical after the date ("- Jul 27 2026
# (Rescheduling of Jul 20 2026))". The date still has to parse, so the tail is
# allowed for and kept as a note rather than blocking the match.
_TRAILING_DATE = re.compile(
    r"^(?P<head>.*?)[\s-]+(?P<date>[A-Z][a-z]{2} \d{1,2},? \d{4})(?:\s*\((?P<tail>.*?)\)*)?$"
)
# Clerks mark a meeting's state by wrapping it in asterisks at either end of the
# title. That is status, not identity, so it is lifted off the body name.
_STATUS_NOTE = re.compile(r"\*+\s*([^*]+?)\s*\*+")
_DATE_FORMATS = ("%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y")


def _clean(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _trim_separators(value: str) -> str:
    """Drop the dash a removed status prefix leaves behind on a body name."""

    return _clean(value).strip(" -\u2013\u2014")


def _meeting_date(value: str) -> date | None:
    """Return the calendar date a title carries.

    The title gives a date with no time and no zone. UTC is attached only to satisfy
    the repository's no-naive-datetime rule and is discarded by ``.date()``, so no
    timezone ever reaches the stored value.
    """

    text = _clean(value)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    return None


def split_title(title: str) -> tuple[str, str | None, date | None]:
    """Return (meeting body, status note, meeting date) for one portal link."""

    text = _clean(title)
    notes = [_clean(note) for note in _STATUS_NOTE.findall(text)]
    body_text = _clean(_STATUS_NOTE.sub(" ", text))

    match = _TRAILING_DATE.match(body_text)
    if match:
        when = _meeting_date(match.group("date"))
        if when is not None:
            body_text = _clean(match.group("head"))
            tail = _clean(match.group("tail") or "")
            if tail:
                notes.append(tail)
            return _trim_separators(body_text), "; ".join(notes) or None, when
    return _trim_separators(body_text), "; ".join(notes) or None, None


def meeting_id_of(url: str) -> str | None:
    query = parse_qs(urlsplit(url).query)
    values = query.get("Id") or query.get("id") or []
    return str(values[0]) if values else None


class CivicWebAdapter(CollectorAdapter):
    """Collect published meetings from a city's public CivicWeb portal list page."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.portal_url = str(config.options.get("portal_url") or config.base_url).rstrip("/")
        self.list_path = str(config.options.get("list_path", "/Portal/MeetingTypeList.aspx"))
        self.min_expected_meetings = int(config.options.get("min_expected_meetings", 1))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 45))

    @property
    def list_url(self) -> str:
        return urljoin(f"{self.portal_url}/", self.list_path.lstrip("/"))

    async def _fetch(self) -> str:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        )
        try:
            response = await client.get(
                self.list_url, headers={"User-Agent": "NS-Trackstar/0.1"}
            )
            if response.status_code in {401, 403, 429}:
                raise SourceBlockedError(
                    "CivicWeb portal request is explicitly blocked: "
                    f"status={response.status_code} url={self.list_url}"
                )
            response.raise_for_status()
            return response.text
        finally:
            if owns:
                await client.aclose()

    def _entries(self, html_text: str) -> dict[str, dict[str, Any]]:
        soup = BeautifulSoup(html_text, "html.parser")
        found: dict[str, dict[str, Any]] = {}
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "")
            if not _MEETING_LINK.search(href):
                continue
            url = urljoin(self.list_url, href)
            identity = meeting_id_of(url)
            title = _clean(anchor.get_text(" ", strip=True))
            if not identity or not title:
                continue
            found.setdefault(identity, {"url": url, "title": title})
        return found

    def _record(self, identity: str, entry: dict[str, Any]) -> NormalizedRecord:
        body, note, when = split_title(entry["title"])
        normalized: dict[str, Any] = {
            "record_kind": "government_meeting",
            "meeting_title": entry["title"],
            "meeting_body": body,
            "meeting_status_note": note,
            "meeting_date": when.isoformat() if when else None,
            "project_page": entry["url"],
        }
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=identity,
            canonical_url=entry["url"],
            raw_payload=dict(entry),
            normalized_payload=normalized,
        )

    async def canary(self) -> bool:
        """The list page must still resolve to identified, dated meetings.

        A city does not stop meeting, and a portal template change that leaves the
        page loading but the links unreadable would otherwise pass as a quiet run.
        """

        try:
            entries = self._entries(await self._fetch())
        except (httpx.HTTPError, SourceBlockedError):
            return False
        if len(entries) < self.min_expected_meetings:
            return False
        dated = sum(1 for entry in entries.values() if split_title(entry["title"])[2] is not None)
        return dated > 0

    async def collect(self) -> CollectorResult:
        entries = self._entries(await self._fetch())
        records = [self._record(identity, entry) for identity, entry in sorted(entries.items())]

        bodies = sorted({str(record.normalized_payload["meeting_body"]) for record in records})
        undated = [
            record.external_id
            for record in records
            if record.normalized_payload["meeting_date"] is None
        ]
        fingerprint = hashlib.sha256("|".join(bodies).encode()).hexdigest() if bodies else None
        return CollectorResult(
            records=records,
            schema_fingerprint=fingerprint,
            parser_yield=(len(records) / len(entries)) if entries else 0.0,
            metadata={
                "list_url": self.list_url,
                "meetings_in_list": len(entries),
                "meeting_bodies_seen": bodies,
                # A meeting whose title carries no parseable date is reported rather
                # than dropped, because a clerk's typo and a template change look the
                # same from here and only one of them is the source breaking.
                "meetings_without_a_parsed_date": undated,
            },
        )
