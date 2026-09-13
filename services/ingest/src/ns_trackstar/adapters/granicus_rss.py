"""Granicus meeting feeds.

Granicus publishes a city's meeting archive twice: as a ViewPublisher HTML page and
as an RSS feed of the same events. Dixon's HTML page is 20 MB and its markup is a
presentation detail that can change with a template update. The RSS feed carries the
same events in 80 KB with a stable, documented shape, so that is what this reads.

One record per meeting. The feed mixes bodies, and a city view often carries the school
district alongside the council, so the meeting body is extracted and kept rather than
assumed. A config can narrow to particular bodies, but the default is to keep
everything the agency chose to publish in its own view.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

# Granicus titles read "<Body> - <Date>", but a body name can itself contain a dash
# and a location ("Dixon USD Board Meeting - Tremont Elementary, MPR, 355 Pheasant").
# So only split on the final dash, and only when what follows actually parses as a date.
_TITLE_SPLIT = re.compile(r"^(?P<body>.+)\s+-\s+(?P<tail>[^-]+)$")
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y")


def _meeting_date(value: str) -> datetime | None:
    cleaned = " ".join(str(value or "").replace("\xa0", " ").split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def split_title(title: str) -> tuple[str, str | None]:
    """Return (meeting body, meeting date text). The date is None when it is not a date."""

    clean = " ".join(str(title or "").replace("\xa0", " ").split())
    match = _TITLE_SPLIT.match(clean)
    if not match:
        return clean, None
    tail = match.group("tail").strip()
    if _meeting_date(tail) is None:
        return clean, None
    return match.group("body").strip(), tail


def _strip_markup(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(text.replace("\xa0", " ").split())


class GranicusRssAdapter(CollectorAdapter):
    """Public Granicus agenda/minutes RSS feed for one published view."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        base = str(config.options.get("base_url") or config.base_url).rstrip("/")
        self.view_id = str(config.options.get("view_id", "")).strip()
        self.mode = str(config.options.get("mode", "agendas"))
        explicit = config.options.get("feed_url")
        if explicit:
            self.feed_url = str(explicit)
        else:
            if not self.view_id:
                raise ValueError("Granicus config needs either feed_url or view_id")
            self.feed_url = f"{base}/ViewPublisherRSS.php?view_id={self.view_id}&mode={self.mode}"
        bodies = config.options.get("meeting_bodies") or []
        self.meeting_bodies = {str(name).casefold() for name in bodies}
        self.min_expected_items = int(config.options.get("min_expected_items", 1))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 30))

    async def _fetch(self) -> str:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.get(
                self.feed_url, headers={"User-Agent": "NS-Trackstar/0.1"}
            )
            response.raise_for_status()
            return response.text
        finally:
            if owns:
                await client.aclose()

    @staticmethod
    def _items(raw: str) -> list[ElementTree.Element]:
        return ElementTree.fromstring(raw).findall(".//item")

    async def canary(self) -> bool:
        """The feed must parse as RSS and still carry identified, linked meetings.

        A city view that suddenly reports no meetings at all is a broken feed, not a
        city that stopped meeting, so an empty feed fails rather than passing quietly.
        """

        try:
            items = self._items(await self._fetch())
        except ElementTree.ParseError:
            return False
        if len(items) < self.min_expected_items:
            return False
        first = items[0]
        return all(first.findtext(field) for field in ("guid", "title", "link"))

    async def collect(self) -> CollectorResult:
        raw = await self._fetch()
        items = self._items(raw)

        records: list[NormalizedRecord] = []
        bodies_seen: set[str] = set()
        for item in items:
            guid = (item.findtext("guid") or "").strip()
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not guid or not title or not link:
                continue

            body, date_text = split_title(title)
            bodies_seen.add(body)
            if self.meeting_bodies and body.casefold() not in self.meeting_bodies:
                continue

            published = item.findtext("pubDate")
            try:
                occurred = parsedate_to_datetime(published) if published else None
            except (TypeError, ValueError):
                occurred = None

            normalized: dict[str, Any] = {
                "meeting_title": title,
                "meeting_body": body,
                "meeting_date_text": date_text,
                "granicus_view_id": self.view_id,
                "feed_mode": self.mode,
                "agenda_url": link,
                "summary": _strip_markup(item.findtext("description") or "")[:2000],
            }
            meeting_date = _meeting_date(date_text or "")
            if meeting_date is not None:
                normalized["meeting_date"] = meeting_date.date().isoformat()

            records.append(
                NormalizedRecord(
                    source_key=self.config.key,
                    external_id=guid,
                    canonical_url=link,
                    source_updated_at=occurred,
                    raw_payload={
                        "title": title,
                        "link": link,
                        "pubDate": published,
                        "guid": guid,
                    },
                    normalized_payload=normalized,
                )
            )

        fingerprint = hashlib.sha256(
            ",".join(sorted({child.tag for item in items for child in item})).encode()
        ).hexdigest()
        return CollectorResult(
            records=records,
            schema_fingerprint=fingerprint,
            parser_yield=len(records) / len(items) if items else 1.0,
            metadata={
                "feed_url": self.feed_url,
                "items_in_feed": len(items),
                "meeting_bodies_seen": sorted(bodies_seen),
                "meeting_bodies_kept": sorted(self.meeting_bodies) or "all",
            },
        )
