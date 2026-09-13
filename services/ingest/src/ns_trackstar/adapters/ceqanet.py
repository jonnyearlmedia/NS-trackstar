from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, LocationAccuracy, NormalizedRecord

REQUIRED_COLUMNS = {
    "SCH Number",
    "Lead Agency Name",
    "Document Title",
    "Document Type",
    "Received",
    "Document Description",
    "Document Portal URL",
    "Project Title",
    "Location Coordinates",
    "Cities",
    "Counties",
}

_DMS_COORDINATES = re.compile(
    r"(?P<lat_deg>\d{1,2})\s*[°º]\s*(?P<lat_min>\d{1,2})\s*['’]\s*"
    r"(?P<lat_sec>\d+(?:\.\d+)?)\s*[\"”]?\s*(?P<lat_dir>[NS])\s+"
    r"(?P<lon_deg>\d{1,3})\s*[°º]\s*(?P<lon_min>\d{1,2})\s*['’]\s*"
    r"(?P<lon_sec>\d+(?:\.\d+)?)\s*[\"”]?\s*(?P<lon_dir>[EW])",
    re.IGNORECASE,
)
_DECIMAL_COORDINATES = re.compile(
    r"^\s*(?P<lat>-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*"
    r"(?P<lon>-?\d{1,3}(?:\.\d+)?)\s*$"
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split()).strip()
    return cleaned or None


def _date(value: Any, timezone: ZoneInfo) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone)
        except ValueError:
            continue
    return None


def _split_values(value: Any) -> list[str]:
    text = _text(value)
    return [item.strip() for item in text.split(",") if item.strip()] if text else []


def _latest_nonempty(rows: list[dict[str, str]], field: str) -> str | None:
    """Return the newest published value for a field across one SCH project's documents."""
    for row in rows:
        if value := _text(row.get(field)):
            return value
    return None


def parse_coordinates(value: Any) -> dict[str, Any] | None:
    """Parse source coordinates without claiming that a project centroid is an exact site."""
    text = _text(value)
    if not text:
        return None

    dms = _DMS_COORDINATES.search(text)
    if dms:
        latitude = float(dms["lat_deg"]) + float(dms["lat_min"]) / 60 + float(dms["lat_sec"]) / 3600
        longitude = (
            float(dms["lon_deg"]) + float(dms["lon_min"]) / 60 + float(dms["lon_sec"]) / 3600
        )
        if dms["lat_dir"].upper() == "S":
            latitude *= -1
        if dms["lon_dir"].upper() == "W":
            longitude *= -1
    else:
        decimal = _DECIMAL_COORDINATES.match(text)
        if not decimal:
            return None
        latitude = float(decimal["lat"])
        longitude = float(decimal["lon"])

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return {"type": "Point", "coordinates": [longitude, latitude]}


def _decode_csv(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # CEQAnet currently returns Windows-1252 CSV without a charset header.
        return content.decode("cp1252")


def _document_identity(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        _text(row.get("SCH Number")) or "",
        _text(row.get("Document Portal URL")) or "",
        _text(row.get("Document Type")) or "",
        _text(row.get("Received")) or "",
    )


def _row_preference(row: dict[str, str]) -> tuple[int, str]:
    """Select duplicate CSV rows deterministically even if portal ordering changes."""
    populated = sum(1 for value in row.values() if _text(value))
    serialized = json.dumps(row, sort_keys=True, separators=(",", ":"))
    return populated, serialized


class CeqanetAdapter(CollectorAdapter):
    """Collect CEQAnet's public search CSV and preserve document lineage by SCH number."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.search_url = str(config.options.get("search_url") or config.base_url).rstrip("/")
        self.project_url_base = str(
            config.options.get("project_url_base") or "https://ceqanet.lci.ca.gov/Project"
        ).rstrip("/")
        self.queries = [dict(query) for query in config.options.get("queries") or []]
        self.canary_sch = str(config.options.get("canary_sch") or "2021010044")
        self.min_records = int(config.options.get("min_records", 1))
        self.max_counties = int(config.options.get("max_counties_per_record", 4))
        self.timezone = ZoneInfo(str(config.options.get("timezone", "America/Los_Angeles")))
        self._client = client

    async def _csv_rows(self, params: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=90, follow_redirects=True)
        try:
            response = await client.get(
                self.search_url,
                params={**params, "OutputFormat": "CSV"},
                headers={"User-Agent": "NS-Trackstar/0.1", "Accept": "text/csv"},
            )
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(_decode_csv(response.content), newline=""))
            rows = [dict(row) for row in reader]
            return rows, list(reader.fieldnames or [])
        finally:
            if owns_client:
                await client.aclose()

    async def canary(self) -> bool:
        rows, columns = await self._csv_rows({"Sch": self.canary_sch})
        return REQUIRED_COLUMNS.issubset(columns) and any(
            _text(row.get("SCH Number")) == self.canary_sch for row in rows
        )

    def _document(self, row: dict[str, str]) -> dict[str, Any]:
        received = _date(row.get("Received"), self.timezone)
        posted = _date(row.get("Posted"), self.timezone)
        return {
            "document_type": _text(row.get("Document Type")),
            "document_title": _text(row.get("Document Title")),
            "portal_url": _text(row.get("Document Portal URL")),
            "received_at": received.isoformat() if received else None,
            "posted_at": posted.isoformat() if posted else None,
            "review_start_at": _text(row.get("NOC State Review Start Date")),
            "review_end_at": _text(row.get("NOC State Review End Date")),
        }

    def _record(self, sch_number: str, rows: list[dict[str, str]]) -> NormalizedRecord:
        rows.sort(
            key=lambda row: (
                _date(row.get("Received"), self.timezone)
                or datetime.min.replace(tzinfo=self.timezone)
            ),
            reverse=True,
        )
        latest = rows[0]
        received_dates = [
            parsed
            for row in rows
            if (parsed := _date(row.get("Received"), self.timezone)) is not None
        ]
        documents = [self._document(row) for row in rows]
        latest_type = _text(latest.get("Document Type"))
        project_title = _text(latest.get("Project Title")) or _text(latest.get("Document Title"))

        # CEQAnet amendments often omit location fields that were present in an older
        # document for the same SCH project. Current document/status data should come
        # from the newest row, while each location field uses the newest non-empty
        # authoritative value in the project's document history. This preserves source
        # truth instead of turning a later sparse filing into a location regression.
        location_coordinates = _latest_nonempty(rows, "Location Coordinates")
        normalized = {
            "record_kind": "environmental_review",
            "sch_number": sch_number,
            "project_title": project_title,
            "lead_agency": _text(latest.get("Lead Agency Name")),
            "lead_agency_title": _text(latest.get("Lead Agency Title")),
            "lead_agency_acronym": _text(latest.get("Lead Agency Acronym")),
            "description": _text(latest.get("Document Description")),
            "environmental_status": f"document_type_{latest_type.casefold()}"
            if latest_type
            else None,
            "latest_document_type": latest_type,
            "latest_document_title": _text(latest.get("Document Title")),
            "latest_document_received": _text(latest.get("Received")),
            "cities": _split_values(_latest_nonempty(rows, "Cities")),
            "counties": _split_values(_latest_nonempty(rows, "Counties")),
            "location_coordinates": location_coordinates,
            "location_cross_streets": _latest_nonempty(rows, "Location Cross Streets"),
            "location_zip": _latest_nonempty(rows, "Location Zip Code"),
            "location_acres": _latest_nonempty(rows, "Location Total Acres"),
            "apn": _latest_nonempty(rows, "Location Parcel Number"),
            "state_highways": _latest_nonempty(rows, "Location State Highways"),
            "waterways": _latest_nonempty(rows, "Location Waterways"),
            "development_type": _latest_nonempty(rows, "NOC Development Type"),
            "local_action": _latest_nonempty(rows, "NOC Local Action"),
            "project_issues": _latest_nonempty(rows, "NOC Project Issues"),
            "documents": documents,
            "document_count": len(documents),
            "document_events": [
                {
                    "identity": document.get("portal_url")
                    or ":".join(
                        filter(
                            None,
                            [document.get("document_type"), document.get("received_at")],
                        )
                    ),
                    "event_type": "ceqa_document_received",
                    "occurred_at": document.get("received_at") or document.get("posted_at"),
                    "title": (
                        f"{document['document_type']} received by State Clearinghouse"
                        if document.get("document_type")
                        else "Environmental document received by State Clearinghouse"
                    ),
                    "summary": document.get("document_title"),
                    "metadata": {
                        "sch_number": sch_number,
                        "document_type": document.get("document_type"),
                        "portal_url": document.get("portal_url"),
                        "review_start_at": document.get("review_start_at"),
                        "review_end_at": document.get("review_end_at"),
                    },
                }
                for document in documents
            ],
        }
        geometry = parse_coordinates(location_coordinates)
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=sch_number,
            canonical_url=f"{self.project_url_base}/{sch_number}",
            source_created_at=min(received_dates) if received_dates else None,
            source_updated_at=max(received_dates) if received_dates else None,
            raw_payload={"sch_number": sch_number, "documents": rows},
            normalized_payload=normalized,
            geometry_geojson=geometry,
            geometry_source=(
                f"{self.project_url_base}/{sch_number} location coordinates" if geometry else None
            ),
            location_accuracy=LocationAccuracy.APPROXIMATE_AREA if geometry else None,
        )

    async def collect(self) -> CollectorResult:
        if not self.queries:
            raise RuntimeError("CEQAnet requires at least one configured search query")

        unique_rows: dict[tuple[str, str, str, str], dict[str, str]] = {}
        headers: list[str] = []
        attempted = 0
        invalid_rows = 0
        excluded_broad_geographies = 0
        for query in self.queries:
            rows, current_headers = await self._csv_rows(query)
            attempted += len(rows)
            headers.extend(current_headers)
            for row in rows:
                sch_number = _text(row.get("SCH Number"))
                if not sch_number:
                    invalid_rows += 1
                    continue
                if len(_split_values(row.get("Counties"))) > self.max_counties:
                    excluded_broad_geographies += 1
                    continue
                identity = _document_identity(row)
                existing = unique_rows.get(identity)
                if existing is None or _row_preference(row) > _row_preference(existing):
                    unique_rows[identity] = row

        if not REQUIRED_COLUMNS.issubset(headers):
            missing = sorted(REQUIRED_COLUMNS.difference(headers))
            raise RuntimeError(f"CEQAnet CSV schema is missing required columns: {missing}")

        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in unique_rows.values():
            sch_number = _text(row.get("SCH Number"))
            if sch_number:
                grouped[sch_number].append(row)
        records = [self._record(sch_number, rows) for sch_number, rows in sorted(grouped.items())]
        if len(records) < self.min_records:
            raise RuntimeError(
                f"CEQAnet parser produced fewer records than expected: {len(records)} < {self.min_records}"
            )

        schema_fingerprint = hashlib.sha256(
            json.dumps(sorted(set(headers)), separators=(",", ":")).encode()
        ).hexdigest()
        valid_rows = len(unique_rows)
        return CollectorResult(
            records=records,
            schema_fingerprint=schema_fingerprint,
            parser_yield=(attempted - invalid_rows) / attempted if attempted else 0.0,
            metadata={
                "queries": len(self.queries),
                "rows_seen": attempted,
                "unique_documents": valid_rows,
                "projects_by_sch": len(records),
                "invalid_rows": invalid_rows,
                "excluded_broad_geographies": excluded_broad_geographies,
            },
        )
