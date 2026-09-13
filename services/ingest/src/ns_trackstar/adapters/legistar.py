from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _schema_fingerprint(events: list[dict[str, Any]]) -> str | None:
    if not events:
        return None
    keys = sorted({key for event in events[:25] for key in event})
    return hashlib.sha256(json.dumps(keys, separators=(",", ":")).encode()).hexdigest()


class LegistarAdapter(CollectorAdapter):
    """Read the public Granicus Legistar Web API for meetings and agenda items."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.api_base = str(
            config.options.get("api_base") or "https://webapi.legistar.com/v1"
        ).rstrip("/")
        self.client_name = str(config.options["client_name"])
        self.portal_url = str(config.options.get("portal_url") or config.base_url)
        self.lookback_days = int(config.options.get("lookback_days", 30))
        self.lookahead_days = int(config.options.get("lookahead_days", 120))
        self.page_size = min(int(config.options.get("page_size", 100)), 1000)
        self.fetch_event_items = bool(config.options.get("fetch_event_items", True))
        self.min_interval = float(config.options.get("min_request_interval_seconds", 0.5))
        self.timezone = ZoneInfo(str(config.options.get("timezone", "America/Los_Angeles")))
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
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        await self._pace()
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            response = await client.get(
                f"{self.api_base}/{self.client_name}/{path.lstrip('/')}",
                params=params,
                headers={"User-Agent": "NS-Trackstar/0.1", "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        finally:
            self._last_request_at = asyncio.get_running_loop().time()
            if owns_client:
                await client.aclose()

    async def canary(self) -> bool:
        payload = await self._get_json("Events", params={"$top": "1"})
        if not isinstance(payload, list):
            return False
        if not payload:
            return True
        sample = payload[0]
        return isinstance(sample, dict) and "EventId" in sample and "EventDate" in sample

    async def _events(self) -> list[dict[str, Any]]:
        today = datetime.now(self.timezone).date()
        start = today - timedelta(days=self.lookback_days)
        end = today + timedelta(days=self.lookahead_days + 1)
        date_filter = (
            f"EventDate ge datetime'{start.isoformat()}' and "
            f"EventDate lt datetime'{end.isoformat()}'"
        )
        events: list[dict[str, Any]] = []
        skip = 0

        while True:
            payload = await self._get_json(
                "Events",
                params={
                    "$filter": date_filter,
                    "$orderby": "EventDate asc",
                    "$top": str(self.page_size),
                    "$skip": str(skip),
                },
            )
            if not isinstance(payload, list):
                raise TypeError("Legistar Events response is not a list")
            batch = [item for item in payload if isinstance(item, dict)]
            events.extend(batch)
            if len(payload) < self.page_size:
                break
            skip += self.page_size
        return events

    def _event_record(self, event: dict[str, Any]) -> NormalizedRecord | None:
        event_id = event.get("EventId")
        event_date = _parse_datetime(event.get("EventDate"))
        if event_id is None or event_date is None:
            return None
        normalized = {
            "record_kind": "meeting",
            "event_id": event_id,
            "body_id": event.get("EventBodyId"),
            "body_name": event.get("EventBodyName"),
            "meeting_date": event_date.isoformat(),
            "meeting_time": event.get("EventTime"),
            "location": event.get("EventLocation"),
            "agenda_status": event.get("EventAgendaStatusName"),
            "minutes_status": event.get("EventMinutesStatusName"),
            "agenda_file": event.get("EventAgendaFile"),
            "minutes_file": event.get("EventMinutesFile"),
            "video_path": event.get("EventVideoPath"),
            "comment": event.get("EventComment"),
        }
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"event:{event_id}",
            canonical_url=event.get("EventInSiteURL") or self.portal_url,
            source_created_at=event_date,
            source_updated_at=_parse_datetime(event.get("EventLastModifiedUtc")),
            raw_payload=event,
            normalized_payload=normalized,
        )

    async def _event_item_records(
        self,
        *,
        event: dict[str, Any],
    ) -> list[NormalizedRecord]:
        event_id = event.get("EventId")
        event_date = _parse_datetime(event.get("EventDate"))
        if event_id is None or event_date is None:
            return []
        payload = await self._get_json(
            f"Events/{int(event_id)}/EventItems",
            params={"AgendaNote": "1", "MinutesNote": "1", "Attachments": "1"},
        )
        if not isinstance(payload, list):
            raise TypeError("Legistar EventItems response is not a list")

        records: list[NormalizedRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_id = item.get("EventItemId")
            if item_id is None:
                continue
            normalized = {
                "record_kind": "agenda_item",
                "event_id": event_id,
                "meeting_date": event_date.isoformat(),
                "body": event.get("EventBodyName"),
                "item_id": item_id,
                "agenda_number": item.get("EventItemAgendaNumber"),
                "agenda_sequence": item.get("EventItemAgendaSequence"),
                "title": item.get("EventItemTitle"),
                "agenda_note": item.get("EventItemAgendaNote"),
                "minutes_note": item.get("EventItemMinutesNote"),
                "action": item.get("EventItemActionName"),
                "action_text": item.get("EventItemActionText"),
                "passed": item.get("EventItemPassedFlagName"),
                "tally": item.get("EventItemTally"),
                "matter_id": item.get("EventItemMatterId"),
                "matter_file": item.get("EventItemMatterFile"),
                "matter_name": item.get("EventItemMatterName"),
                "matter_type": item.get("EventItemMatterType"),
                "matter_status": item.get("EventItemMatterStatus"),
                "attachments": item.get("EventItemMatterAttachments") or [],
                "accela_record_id": item.get("EventItemAccelaRecordId"),
            }
            records.append(
                NormalizedRecord(
                    source_key=self.config.key,
                    external_id=f"event:{event_id}:item:{item_id}",
                    canonical_url=self.portal_url,
                    source_created_at=event_date,
                    source_updated_at=_parse_datetime(item.get("EventItemLastModifiedUtc")),
                    raw_payload=item,
                    normalized_payload=normalized,
                )
            )
        return records

    async def collect(self) -> CollectorResult:
        events = await self._events()
        records: list[NormalizedRecord] = []
        skipped = 0
        item_events = 0

        for event in events:
            event_record = self._event_record(event)
            if event_record is None:
                skipped += 1
                continue
            records.append(event_record)
            if self.fetch_event_items:
                records.extend(await self._event_item_records(event=event))
                item_events += 1

        parser_yield = (len(events) - skipped) / len(events) if events else 1.0
        return CollectorResult(
            records=records,
            schema_fingerprint=_schema_fingerprint(events),
            parser_yield=parser_yield,
            metadata={
                "events_seen": len(events),
                "events_skipped": skipped,
                "events_with_item_fetch": item_events,
                "client_name": self.client_name,
            },
        )
