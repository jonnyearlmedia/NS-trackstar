from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, LocationAccuracy, NormalizedRecord


def _arcgis_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def coded_value_domains(metadata: dict[str, Any]) -> dict[str, dict[Any, str]]:
    """Return {field: {code: label}} for every coded-value domain the layer declares.

    An agency often stores a category, a status or a city as an integer or a short
    code and keeps the human wording in the layer's domain. Publishing the raw code
    would put "Category 4" in front of a resident, which is the bureaucratic
    vocabulary this product exists to remove, so the domains are read and applied.
    """

    domains: dict[str, dict[Any, str]] = {}
    for field in metadata.get("fields", []):
        domain = field.get("domain") or {}
        if domain.get("type") != "codedValue":
            continue
        name = field.get("name")
        values = {
            entry.get("code"): str(entry.get("name"))
            for entry in domain.get("codedValues", [])
            if entry.get("code") is not None and entry.get("name") is not None
        }
        if name and values:
            domains[str(name)] = values
    return domains


def apply_domains(
    properties: dict[str, Any], domains: dict[str, dict[Any, str]]
) -> dict[str, Any]:
    """Replace coded values with the agency's own wording for them.

    Only an exact code match is translated. A value the domain does not list is left
    as it is rather than guessed at, because an unlisted code means the layer changed
    and that should look like the anomaly it is instead of quietly becoming a label.
    The raw feature is preserved separately, so nothing is lost.
    """

    if not domains:
        return properties
    decoded = dict(properties)
    for field, values in domains.items():
        if field not in decoded:
            continue
        current = decoded[field]
        if current in values:
            decoded[field] = values[current]
    return decoded


class ArcGISRestAdapter(CollectorAdapter):
    """Generic ArcGIS FeatureServer/MapServer layer collector.

    Jurisdictions supply layer and field configuration. Complete feature properties are
    retained so a reusable transport layer never flattens city-specific fields.
    """

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.layer_url = str(config.options["layer_url"]).rstrip("/")
        self.id_field = str(config.options.get("id_field", "OBJECTID"))
        self.where = str(config.options.get("where", "1=1"))
        self.out_fields = config.options.get("out_fields", "*")
        self.page_size = int(config.options.get("page_size", 1000))
        self.created_at_field = config.options.get("created_at_field")
        self.updated_at_field = config.options.get("updated_at_field")
        self.canonical_url_field = config.options.get("canonical_url_field")
        self.canary_fields = {str(value) for value in config.options.get("canary_fields", [])}
        self.expected_geometry_type = config.options.get("expected_geometry_type")
        self.min_expected_records = int(config.options.get("min_expected_records", 0))
        self.max_expected_records = config.options.get("max_expected_records")

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
        """Fingerprint the fields and their coded-value domains.

        The domain belongs in the fingerprint because it carries meaning: an agency
        that renumbers a status list changes what every stored record says without
        changing a single field name, and that has to read as a schema change rather
        than as a quiet relabelling of history.
        """

        fields = [
            (
                field.get("name"),
                field.get("type"),
                field.get("length"),
                sorted(
                    (str(entry.get("code")), str(entry.get("name")))
                    for entry in ((field.get("domain") or {}).get("codedValues") or [])
                ),
            )
            for field in metadata.get("fields", [])
        ]
        encoded = json.dumps(fields, separators=(",", ":"), sort_keys=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def canary(self) -> bool:
        metadata = await self._get_json(self.layer_url, {"f": "json"})
        field_names = {field.get("name") for field in metadata.get("fields", [])}
        metadata_ok = (
            bool(metadata.get("type"))
            and self.id_field in field_names
            and self.canary_fields.issubset(field_names)
            and (
                self.expected_geometry_type is None
                or metadata.get("geometryType") == self.expected_geometry_type
            )
        )
        if not metadata_ok:
            return False
        if self.min_expected_records <= 0 and self.max_expected_records is None:
            return True

        count_payload = await self._get_json(
            f"{self.layer_url}/query",
            {"f": "json", "where": self.where, "returnCountOnly": "true"},
        )
        count = count_payload.get("count")
        if not isinstance(count, int) or count < self.min_expected_records:
            return False
        return self.max_expected_records is None or count <= int(self.max_expected_records)

    @staticmethod
    def _canonical_url(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized or normalized.casefold() in {"n/a", "none", "null"}:
            return None
        return normalized

    async def collect(self) -> CollectorResult:
        metadata = await self._get_json(self.layer_url, {"f": "json"})
        schema_fingerprint = self._schema_fingerprint(metadata)
        domains = coded_value_domains(metadata)
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
                properties = apply_domains(feature.get("properties") or {}, domains)
                external_id = properties.get(self.id_field)
                if external_id is None:
                    continue

                geometry = feature.get("geometry")
                records.append(
                    NormalizedRecord(
                        source_key=self.config.key,
                        external_id=str(external_id),
                        canonical_url=self._canonical_url(
                            properties.get(self.canonical_url_field)
                            if self.canonical_url_field
                            else None
                        ),
                        source_created_at=(
                            _arcgis_datetime(properties.get(self.created_at_field))
                            if self.created_at_field
                            else None
                        ),
                        source_updated_at=(
                            _arcgis_datetime(properties.get(self.updated_at_field))
                            if self.updated_at_field
                            else None
                        ),
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
                "decoded_domain_fields": sorted(domains),
                "layer_name": metadata.get("name"),
                "layer_type": metadata.get("type"),
                "max_record_count": max_record_count,
            },
        )
