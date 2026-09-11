from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, LocationAccuracy, NormalizedRecord


class ArcGISRestAdapter(CollectorAdapter):
    """Generic ArcGIS FeatureServer layer collector.

    Jurisdictions supply the layer URL and field configuration. The adapter keeps the
    complete feature payload so source-specific fields are never lost just because the
    transport is shared.
    """

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.layer_url = str(config.options["layer_url"]).rstrip("/")
        self.id_field = str(config.options.get("id_field", "OBJECTID"))
        self.where = str(config.options.get("where", "1=1"))
        self.out_fields = config.options.get("out_fields", "*")
        self.page_size = int(config.options.get("page_size", 1000))

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(f"ArcGIS error: {payload['error']}")
            return payload
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _schema_fingerprint(metadata: dict[str, Any]) -> str:
        fields = [
            (field.get("name"), field.get("type"), field.get("length"))
            for field in metadata.get("fields", [])
        ]
        encoded = json.dumps(fields, separators=(",", ":"), sort_keys=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def canary(self) -> bool:
        metadata = await self._get_json(self.layer_url, {"f": "json"})
        field_names = {field.get("name") for field in metadata.get("fields", [])}
        return bool(metadata.get("type")) and self.id_field in field_names

    async def collect(self) -> CollectorResult:
        metadata = await self._get_json(self.layer_url, {"f": "json"})
        schema_fingerprint = self._schema_fingerprint(metadata)
        max_record_count = int(metadata.get("maxRecordCount") or self.page_size)
        page_size = min(self.page_size, max_record_count)

        if isinstance(self.out_fields, list):
            out_fields = ",".join(str(field) for field in self.out_fields)
        else:
            out_fields = str(self.out_fields)

        records: list[NormalizedRecord] = []
        attempted = 0
        offset = 0

        while True:
            payload = await self._get_json(
                f"{self.layer_url}/query",
                {
                    "f": "geojson",
                    "where": self.where,
                    "outFields": out_fields,
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultOffset": offset,
                    "resultRecordCount": page_size,
                },
            )
            features = payload.get("features", [])
            attempted += len(features)

            for feature in features:
                properties = feature.get("properties") or {}
                external_id = properties.get(self.id_field)
                if external_id is None:
                    continue

                geometry = feature.get("geometry")
                records.append(
                    NormalizedRecord(
                        source_key=self.config.key,
                        external_id=str(external_id),
                        raw_payload=feature,
                        normalized_payload=properties,
                        geometry_geojson=geometry,
                        geometry_source=self.layer_url if geometry else None,
                        location_accuracy=(
                            LocationAccuracy.EXACT_SOURCE_GEOMETRY if geometry else None
                        ),
                    )
                )

            if len(features) < page_size:
                break
            offset += page_size

        parser_yield = len(records) / attempted if attempted else 1.0
        return CollectorResult(
            records=records,
            schema_fingerprint=schema_fingerprint,
            parser_yield=parser_yield,
            metadata={
                "layer_name": metadata.get("name"),
                "layer_type": metadata.get("type"),
                "max_record_count": max_record_count,
            },
        )
