from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, LocationAccuracy, NormalizedRecord


class OpenCitiesMapAdapter(CollectorAdapter):
    """Collect public OpenCities map layers and their structured marker details."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        parsed = urlsplit(config.base_url)
        self.origin = str(config.options.get("origin") or f"{parsed.scheme}://{parsed.netloc}")
        self.map_id = str(config.options["map_id"])
        self.bounds = str(config.options["bounds"])
        self.language_code = str(config.options.get("language_code", "en-US"))
        self.expected_map_name = config.options.get("expected_map_name")
        self.expected_layer_names = {
            str(value) for value in config.options.get("expected_layer_names", [])
        }
        self.expected_project_count = int(config.options.get("expected_project_count", 1))
        self.min_request_interval = float(
            config.options.get("min_request_interval_seconds", 0.05)
        )
        self._client = client
        self._cached_map: dict[str, Any] | None = None

    async def _request_json(
        self, method: str, path: str, *, json_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            response = await client.request(
                method,
                f"{self.origin}{path}",
                json=json_payload,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"OpenCities endpoint reported failure: {path}")
            return payload
        finally:
            if owns_client:
                await client.aclose()

    async def _map_definition(self) -> dict[str, Any]:
        if self._cached_map is None:
            payload = await self._request_json("GET", f"/ocmaps/get/{self.map_id}")
            self._cached_map = dict(payload.get("map") or {})
        return self._cached_map

    async def canary(self) -> bool:
        map_definition = await self._map_definition()
        actual_layers = {str(layer.get("Name")) for layer in map_definition.get("layer", [])}
        return (
            str(map_definition.get("id")) == self.map_id
            and (not self.expected_map_name or map_definition.get("Name") == self.expected_map_name)
            and self.expected_layer_names.issubset(actual_layers)
        )

    async def collect(self) -> CollectorResult:
        map_definition = await self._map_definition()
        layers = list(map_definition.get("layer") or [])
        layer_ids = [str(layer["Id"]) for layer in layers if layer.get("Id")]
        payload = await self._request_json(
            "POST",
            "/ocmaps/layer",
            json_payload={
                "MapId": self.map_id,
                "LanguageCode": self.language_code,
                "IdList": layer_ids,
                "Bounds": self.bounds,
                "RefreshResults": True,
                "UniqueId": None,
            },
        )
        layer_items = list(payload.get("layerItems") or [])
        if int(payload.get("resultsLeft") or 0) > 0:
            raise RuntimeError("OpenCities map response was truncated; refine configured bounds")

        records: list[NormalizedRecord] = []
        for index, layer_item in enumerate(layer_items):
            content_id = layer_item.get("ContentId")
            if not content_id:
                continue
            if index and self.min_request_interval:
                await asyncio.sleep(self.min_request_interval)
            main_content_id = str(
                layer_item.get("MainContentId") or "00000000-0000-0000-0000-000000000000"
            )
            detail_payload = await self._request_json(
                "GET",
                f"/ocapi/get/markerinfo/{content_id}/{self.language_code}"
                f"?mainContentId={main_content_id}",
            )
            detail = dict(detail_payload.get("markerInfo") or {})
            title = detail.get("Title") or layer_item.get("ContentTitle")
            if not title:
                continue

            lat = float(str(layer_item["Lat"]).strip())
            lng = float(str(layer_item["Lng"]).strip())
            address = dict(detail.get("Address") or {})
            normalized = {
                "record_kind": "curated_project",
                "name": str(title),
                "tracker_stage": layer_item.get("Name"),
                "description": detail.get("Description"),
                "address": address.get("Formatted"),
                "address_components": address,
                "additional_info": detail.get("AdditionalInfo") or [],
                "layer_id": layer_item.get("Id"),
                "project_url": detail.get("Link"),
            }
            records.append(
                NormalizedRecord(
                    source_key=self.config.key,
                    external_id=str(content_id),
                    canonical_url=detail.get("Link"),
                    raw_payload={"layer_item": layer_item, "marker_info": detail},
                    normalized_payload=normalized,
                    geometry_geojson={"type": "Point", "coordinates": [lng, lat]},
                    geometry_source=f"{self.origin}/ocmaps/layer",
                    location_accuracy=LocationAccuracy.EXACT_SOURCE_GEOMETRY,
                )
            )

        if len(records) < self.expected_project_count:
            raise RuntimeError(
                "OpenCities map parser yield fell below expected project count: "
                f"{len(records)} < {self.expected_project_count}"
            )
        schema = {
            "map_fields": sorted(map_definition),
            "layer_fields": sorted(layer_items[0]) if layer_items else [],
            "marker_fields": sorted(records[0].raw_payload["marker_info"]) if records else [],
        }
        return CollectorResult(
            records=records,
            schema_fingerprint=hashlib.sha256(
                json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            parser_yield=len(records) / len(layer_items) if layer_items else 0.0,
            metadata={
                "map_id": self.map_id,
                "map_name": map_definition.get("Name"),
                "layers": [{"id": layer.get("Id"), "name": layer.get("Name")} for layer in layers],
                "projects_parsed": len(records),
            },
        )
