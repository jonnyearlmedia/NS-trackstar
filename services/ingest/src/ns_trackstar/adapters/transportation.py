from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, LocationAccuracy, NormalizedRecord

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
RETRY_DELAYS_SECONDS = (2.0, 10.0, 30.0)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _valid_geometry(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        return False
    if value["type"] == "GeometryCollection":
        return isinstance(value.get("geometries"), list)
    return isinstance(value.get("coordinates"), list)


def _schema_paths(value: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths.update(_schema_paths(child, path))
    elif isinstance(value, list) and value:
        paths.update(_schema_paths(value[0], f"{prefix}[]"))
    return paths


def _schema_fingerprint(payload: dict[str, Any], records_key: str) -> str:
    records = payload.get(records_key)
    sample = records[:25] if isinstance(records, list) else []
    schema = {
        "top_level": sorted(payload),
        "record_paths": sorted(
            {path for record in sample for path in _schema_paths(record) if isinstance(record, dict)}
        ),
    }
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


class _JsonTransportAdapter(CollectorAdapter):
    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.endpoint_url = str(config.options.get("endpoint_url") or config.base_url)
        self.api_key_env = config.options.get("api_key_env")
        self.api_key_param = str(config.options.get("api_key_param", "api_key"))
        self.timeout_seconds = float(config.options.get("timeout_seconds", 30))

    def _api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        value = os.environ.get(str(self.api_key_env))
        if not value:
            raise SourceBlockedError(
                f"Required API token environment variable {self.api_key_env} is not set"
            )
        return value

    async def _get_json(self, params: dict[str, Any]) -> dict[str, Any]:
        request_params = dict(params)
        api_key = self._api_key()
        if api_key is not None:
            request_params[self.api_key_param] = api_key

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "NS-Trackstar/0.1"},
        )
        try:
            for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
                try:
                    response = await client.get(self.endpoint_url, params=request_params)
                except httpx.RequestError as exc:
                    if attempt >= len(RETRY_DELAYS_SECONDS):
                        raise RuntimeError(
                            f"Public transportation request failed: {type(exc).__name__}"
                        ) from None
                    await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt] + random.random())
                    continue

                if response.status_code in {401, 403}:
                    raise SourceBlockedError(
                        f"Public transportation endpoint rejected access with HTTP "
                        f"{response.status_code}"
                    )
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt >= len(RETRY_DELAYS_SECONDS):
                        raise RuntimeError(
                            f"Public transportation endpoint failed with HTTP "
                            f"{response.status_code}"
                        )
                    delay = _retry_after_seconds(response)
                    if delay is None:
                        delay = RETRY_DELAYS_SECONDS[attempt] + random.random()
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Public transportation endpoint failed with HTTP {response.status_code}"
                    )

                try:
                    payload = response.json()
                except ValueError as exc:
                    raise TypeError("Public transportation endpoint returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise TypeError("Public transportation endpoint returned non-object JSON")
                return payload
        finally:
            if owns_client:
                await client.aclose()

        raise RuntimeError("Public transportation request exhausted retries")


class WzdxAdapter(_JsonTransportAdapter):
    """Collect a WZDx RoadEventFeed while retaining its complete GeoJSON features."""

    def _request_params(self) -> dict[str, Any]:
        params = self.config.options.get("request_params") or {}
        if not isinstance(params, dict):
            raise TypeError("WZDx request_params must be an object")
        return dict(params)

    @staticmethod
    def _valid_feed(payload: dict[str, Any]) -> bool:
        feed_info = payload.get("road_event_feed_info")
        features = payload.get("features")
        if (
            payload.get("type") != "FeatureCollection"
            or not isinstance(feed_info, dict)
            or not isinstance(feed_info.get("version"), str)
            or not isinstance(feed_info.get("data_sources"), list)
            or not isinstance(features, list)
        ):
            return False
        if not features:
            return True
        sample = features[0]
        if not isinstance(sample, dict) or sample.get("type") != "Feature":
            return False
        properties = sample.get("properties")
        core = properties.get("core_details") if isinstance(properties, dict) else None
        return (
            sample.get("id") is not None
            and _valid_geometry(sample.get("geometry"))
            and isinstance(core, dict)
            and core.get("event_type") is not None
            and core.get("data_source_id") is not None
        )

    async def canary(self) -> bool:
        payload = await self._get_json(self._request_params())
        return self._valid_feed(payload)

    def _record(self, feature: dict[str, Any]) -> NormalizedRecord | None:
        external_id = feature.get("id")
        properties = feature.get("properties")
        if external_id is None or not isinstance(properties, dict):
            return None
        core = properties.get("core_details")
        if not isinstance(core, dict) or core.get("event_type") is None:
            return None

        geometry = feature.get("geometry")
        valid_geometry = geometry if _valid_geometry(geometry) else None
        normalized = dict(properties)
        normalized.update(
            {
                "record_kind": "work_zone_road_event",
                "event_id": str(external_id),
                "event_type": core.get("event_type"),
                "data_source_id": core.get("data_source_id"),
                "road_names": core.get("road_names") or [],
                "direction": core.get("direction"),
                "description": core.get("description"),
                "creation_date": core.get("creation_date"),
                "update_date": core.get("update_date"),
                "event_status": properties.get("event_status"),
                "start_date": properties.get("start_date"),
                "end_date": properties.get("end_date"),
                "vehicle_impact": properties.get("vehicle_impact"),
                "beginning_cross_street": properties.get("beginning_cross_street"),
                "ending_cross_street": properties.get("ending_cross_street"),
                "project_id": properties.get("project_id") or properties.get("work_zone_id"),
                "route": properties.get("route") or properties.get("route_id"),
                "begin_postmile": properties.get("begin_postmile")
                or properties.get("beginning_postmile")
                or properties.get("start_milepost"),
                "end_postmile": properties.get("end_postmile")
                or properties.get("ending_postmile")
                or properties.get("end_milepost"),
                "geometry_method": "source_provided_wzdx_geometry",
                "location_accuracy_detail": {
                    "beginning": properties.get("beginning_accuracy"),
                    "ending": properties.get("ending_accuracy"),
                    "method": properties.get("location_method"),
                },
            }
        )
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=str(external_id),
            canonical_url=self.endpoint_url,
            source_created_at=_parse_datetime(core.get("creation_date")),
            source_updated_at=_parse_datetime(core.get("update_date")),
            raw_payload=feature,
            normalized_payload=normalized,
            geometry_geojson=valid_geometry,
            geometry_source=self.endpoint_url if valid_geometry else None,
            location_accuracy=(
                LocationAccuracy.EXACT_SOURCE_GEOMETRY if valid_geometry else None
            ),
        )

    async def collect(self) -> CollectorResult:
        payload = await self._get_json(self._request_params())
        if not self._valid_feed(payload):
            raise TypeError("WZDx response failed required RoadEventFeed invariants")
        features = payload["features"]
        records = [
            record
            for feature in features
            if isinstance(feature, dict)
            if (record := self._record(feature)) is not None
        ]
        feed_info = payload["road_event_feed_info"]
        return CollectorResult(
            records=records,
            schema_fingerprint=_schema_fingerprint(payload, "features"),
            parser_yield=len(records) / len(features) if features else 1.0,
            metadata={
                "feed_version": feed_info.get("version"),
                "feed_updated_at": feed_info.get("update_date"),
                "publisher": feed_info.get("publisher"),
                "data_sources": len(feed_info.get("data_sources") or []),
                "features_seen": len(features),
            },
        )


class BayArea511TrafficAdapter(_JsonTransportAdapter):
    """Collect the token-gated 511 SF Bay Open511 Traffic Events API."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config, client=client)
        self.page_size = min(max(int(config.options.get("page_size", 500)), 1), 1000)
        self.max_pages = max(int(config.options.get("max_pages", 10)), 1)

    def _base_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "format": "json",
            "limit": self.page_size,
        }
        for key in ("status", "event_type", "updated", "bbox"):
            value = self.config.options.get(key)
            if value is not None:
                params[key] = ",".join(str(item) for item in value) if isinstance(value, list) else value
        return params

    @staticmethod
    def _valid_payload(payload: dict[str, Any]) -> bool:
        events = payload.get("events")
        if not isinstance(events, list):
            return False
        if not events:
            return isinstance(payload.get("meta"), dict)
        sample = events[0]
        return (
            isinstance(sample, dict)
            and sample.get("id") is not None
            and sample.get("status") is not None
            and sample.get("event_type") is not None
        )

    async def canary(self) -> bool:
        params = self._base_params()
        params["limit"] = 1
        params["offset"] = 0
        payload = await self._get_json(params)
        return self._valid_payload(payload)

    def _canonical_url(self, event: dict[str, Any]) -> str:
        raw_url = event.get("url")
        if not isinstance(raw_url, str) or not raw_url:
            return self.endpoint_url
        candidate = urljoin(self.endpoint_url, raw_url)
        endpoint_host = urlparse(self.endpoint_url).hostname
        parsed = urlparse(candidate)
        if parsed.hostname != endpoint_host:
            return self.endpoint_url
        return urlunparse(parsed._replace(query="", fragment=""))

    def _record(self, event: dict[str, Any]) -> NormalizedRecord | None:
        event_id = event.get("id")
        if event_id is None:
            return None
        closure_geometry = (
            event.get("+closure_geography")
            or event.get("closure_geography")
            or event.get("+closure_geometry")
            or event.get("closure_geometry")
        )
        point_geometry = event.get("geography")
        geometry = (
            closure_geometry
            if _valid_geometry(closure_geometry)
            else point_geometry
            if _valid_geometry(point_geometry)
            else None
        )
        roads = event.get("roads") if isinstance(event.get("roads"), list) else []
        road_names = [
            road.get("name")
            for road in roads
            if isinstance(road, dict) and road.get("name")
        ]
        first_road = next((road for road in roads if isinstance(road, dict)), {})
        normalized = {
            "record_kind": "traffic_event",
            "event_id": str(event_id),
            "status": event.get("status"),
            "headline": event.get("headline"),
            "event_type": event.get("event_type"),
            "event_subtypes": event.get("event_subtypes") or [],
            "severity": event.get("severity"),
            "created": event.get("created"),
            "updated": event.get("updated"),
            "roads": roads,
            "road_names": road_names,
            "areas": event.get("areas") or [],
            "schedules": event.get("schedules") or [],
            "source_id": event.get("+source_id") or event.get("source_id"),
            "source_name": event.get("+source_name") or event.get("source_name"),
            "route": event.get("+route")
            or event.get("route")
            or first_road.get("route")
            or first_road.get("name"),
            "begin_postmile": event.get("+begin_postmile")
            or event.get("begin_postmile")
            or first_road.get("begin_postmile"),
            "end_postmile": event.get("+end_postmile")
            or event.get("end_postmile")
            or first_road.get("end_postmile"),
            "road_state": first_road.get("state"),
            "lane_status": first_road.get("+lane_status") or first_road.get("lane_status"),
            "lane_type": first_road.get("+lane_type") or first_road.get("lane_type"),
            "geometry_method": (
                "source_provided_closure_geometry"
                if geometry is closure_geometry
                else "source_provided_event_geography"
                if geometry
                else None
            ),
        }
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=str(event_id),
            canonical_url=self._canonical_url(event),
            source_created_at=_parse_datetime(event.get("created")),
            source_updated_at=_parse_datetime(event.get("updated")),
            raw_payload=event,
            normalized_payload=normalized,
            geometry_geojson=geometry,
            geometry_source=self.endpoint_url if geometry else None,
            location_accuracy=(
                LocationAccuracy.EXACT_SOURCE_GEOMETRY if geometry else None
            ),
        )

    async def collect(self) -> CollectorResult:
        events: list[dict[str, Any]] = []
        last_payload: dict[str, Any] | None = None
        pages_fetched = 0

        for page in range(self.max_pages):
            params = self._base_params()
            params["offset"] = page * self.page_size
            payload = await self._get_json(params)
            if not self._valid_payload(payload):
                raise TypeError("511 Traffic Events response failed required schema invariants")
            last_payload = payload
            pages_fetched += 1
            batch = [event for event in payload["events"] if isinstance(event, dict)]
            events.extend(batch)
            pagination = payload.get("pagination")
            next_url = pagination.get("next_url") if isinstance(pagination, dict) else None
            if not next_url or len(payload["events"]) < self.page_size:
                break
        else:
            if last_payload:
                pagination = last_payload.get("pagination")
                if isinstance(pagination, dict) and pagination.get("next_url"):
                    raise RuntimeError("511 Traffic Events pagination exceeded configured max_pages")

        records = [
            record
            for event in events
            if (record := self._record(event)) is not None
        ]
        schema_payload = dict(last_payload) if last_payload is not None else {"events": []}
        schema_payload["events"] = events
        return CollectorResult(
            records=records,
            schema_fingerprint=(
                _schema_fingerprint(schema_payload, "events") if last_payload is not None else None
            ),
            parser_yield=len(records) / len(events) if events else 1.0,
            metadata={
                "events_seen": len(events),
                "status_filter": self.config.options.get("status", "ACTIVE"),
                "pages_fetched": pages_fetched,
            },
        )
