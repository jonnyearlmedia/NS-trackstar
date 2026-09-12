from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord


def _wall_clock_datetime(value: Any) -> datetime | None:
    """Parse CivicClerk's local wall-clock datetime without trusting its Z suffix."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.year in {1, 1900}:
        return None
    return parsed.replace(tzinfo=None)


def _walk_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value.get("sortOrder") or 0):
        flattened.append(item)
        children = item.get("childItems") or []
        if isinstance(children, list):
            flattened.extend(_walk_items(children))
    return flattened


class CivicClerkAdapter(CollectorAdapter):
    """Read Vallejo-style CivicClerk public OData and structured agendas."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.api_base = str(config.options.get("api_base") or config.base_url).rstrip("/")
        self.portal_url = config.options.get("portal_url")
        self.lookback_days = int(config.options.get("lookback_days", 30))
        self.lookahead_days = int(config.options.get("lookahead_days", 120))
        self.fetch_agendas = bool(config.options.get("fetch_agendas", True))
        self.min_interval = float(config.options.get("min_request_interval_seconds", 1.0))
        self._client = client
        self._last_request_at: float | None = None

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self._last_request_at is None:
            return
        loop = asyncio.get_running_loop()
        delay = self.min_interval - (loop.time() - self._last_request_at)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        await self._pace()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            response = await client.get(url, params=params, headers={"User-Agent": "NS-Trackstar/0.1"})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("CivicClerk returned a non-object JSON payload")
            return payload
        finally:
            self._last_request_at = asyncio.get_running_loop().time()
            if owns_client:
                await client.aclose()

    def _safe_next_link(self, value: Any) -> str | None:
        if not value:
            return None
        if not isinstance(value, str):
            raise RuntimeError("CivicClerk @odata.nextLink is not a string")
        base = urlparse(self.api_base)
        target = urlparse(value)
        if target.scheme != "https" or target.hostname != base.hostname:
            raise RuntimeError("CivicClerk continuation link left the configured public API host")
        return value

    async def canary(self) -> bool:
        payload = await self._get_json(f"{self.api_base}/EventCategories")
        return isinstance(payload.get("value"), list)

    async def _events(self) -> list[dict[str, Any]]:
        today = date.today()
        from_date = today - timedelta(days=self.lookback_days)
        to_date = today + timedelta(days=self.lookahead_days)
        filters = (
            f"eventDate ge {from_date.isoformat()}T00:00:00Z and "
            f"eventDate le {to_date.isoformat()}T23:59:59Z"
        )
        url = f"{self.api_base}/Events"
        params: dict[str, str] | None = {"$orderby": "eventDate asc", "$filter": filters}
        events: list[dict[str, Any]] = []

        while url:
            payload = await self._get_json(url, params=params)
            values = payload.get("value") or []
            if not isinstance(values, list):
                raise RuntimeError("CivicClerk Events.value is not a list")
            events.extend(value for value in values if isinstance(value, dict))
            url = self._safe_next_link(payload.get("@odata.nextLink")) or ""
            params = None
        return events

    def _event_record(self, event: dict[str, Any]) -> NormalizedRecord | None:
        event_id = event.get("id")
        event_date = _wall_clock_datetime(event.get("eventDate"))
        if event_id is None or event_date is None:
            return None
        normalized = {
            "record_kind": "meeting",
            "event_id": event_id,
            "meeting_date_local": event_date.isoformat(),
            "name": event.get("eventName"),
            "description": event.get("eventDescription"),
            "category_id": event.get("categoryId"),
            "category_name": event.get("categoryName"),
            "agenda_id": event.get("agendaId") or None,
            "agenda_name": event.get("agendaName"),
            "location": event.get("eventLocation"),
            "published_files": event.get("publishedFiles") or [],
            "virtual_meeting_url": event.get("externalMediaUrl"),
            "youtube_video_id": event.get("youtubeVideoId"),
            "media_stream_url": event.get("mediaStreamPath"),
        }
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"event:{event_id}",
            canonical_url=str(self.portal_url) if self.portal_url else None,
            source_created_at=event_date,
            raw_payload=event,
            normalized_payload=normalized,
        )

    async def _agenda_records(
        self,
        *,
        event: dict[str, Any],
        event_date: datetime,
    ) -> list[NormalizedRecord]:
        agenda_id = event.get("agendaId")
        if not agenda_id:
            return []
        payload = await self._get_json(f"{self.api_base}/Meetings/{int(agenda_id)}")
        if not payload.get("id"):
            return []
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise RuntimeError("CivicClerk agenda items is not a list")

        records: list[NormalizedRecord] = []
        for item in _walk_items([value for value in items if isinstance(value, dict)]):
            item_id = item.get("id")
            if item_id is None:
                continue
            normalized = {
                "record_kind": "agenda_item",
                "event_id": event.get("id"),
                "agenda_id": agenda_id,
                "meeting_date_local": event_date.isoformat(),
                "body": event.get("categoryName"),
                "meeting_name": event.get("eventName"),
                "item_id": item_id,
                "title": item.get("agendaObjectItemName"),
                "is_section": bool(item.get("isSection")),
                "sort_order": item.get("sortOrder"),
                "attachments": item.get("attachmentsList") or [],
            }
            records.append(
                NormalizedRecord(
                    source_key=self.config.key,
                    external_id=f"event:{event.get('id')}:agenda:{agenda_id}:item:{item_id}",
                    canonical_url=str(self.portal_url) if self.portal_url else None,
                    source_created_at=event_date,
                    raw_payload=item,
                    normalized_payload=normalized,
                )
            )
        return records

    async def collect(self) -> CollectorResult:
        events = await self._events()
        records: list[NormalizedRecord] = []
        skipped = 0
        agendas_fetched = 0

        for event in events:
            event_record = self._event_record(event)
            if event_record is None:
                skipped += 1
                continue
            records.append(event_record)

            agenda_id = event.get("agendaId")
            if self.fetch_agendas and agenda_id:
                event_date = _wall_clock_datetime(event.get("eventDate"))
                if event_date is not None:
                    records.extend(await self._agenda_records(event=event, event_date=event_date))
                    agendas_fetched += 1

        attempted = len(events)
        event_yield = (attempted - skipped) / attempted if attempted else 1.0
        return CollectorResult(
            records=records,
            parser_yield=event_yield,
            metadata={
                "events_seen": attempted,
                "events_skipped": skipped,
                "agendas_fetched": agendas_fetched,
            },
        )
