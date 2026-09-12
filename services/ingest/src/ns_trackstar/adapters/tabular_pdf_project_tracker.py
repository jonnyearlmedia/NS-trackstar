from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pypdf import PdfReader

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

Fragment = tuple[float, float, str]


def _clean(value: str) -> str:
    return " ".join(value.split()).strip()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")


def parse_tabular_page(
    fragments: list[Fragment],
    *,
    columns: dict[str, tuple[float, float]],
    row_labels: set[str],
    page_top: float,
    page_bottom: float,
    anchor_max_x: float,
    external_id_pattern: re.Pattern[str],
) -> list[dict[str, Any]]:
    """Parse positioned PDF text while keeping every extracted column value intact."""
    anchors = sorted(
        (
            (y, text)
            for x, y, text in fragments
            if x < anchor_max_x
            and page_bottom < y < page_top
            and text in row_labels
        ),
        reverse=True,
    )
    rows: list[dict[str, Any]] = []
    number_bounds = columns["project_numbers"]

    for index, (anchor_y, _) in enumerate(anchors):
        top = page_top if index == 0 else (anchors[index - 1][0] + anchor_y) / 2
        bottom = (
            page_bottom
            if index == len(anchors) - 1
            else (anchor_y + anchors[index + 1][0]) / 2
        )
        row: dict[str, Any] = {"record_kind": "curated_project"}
        for field, (left, right) in columns.items():
            values = [
                (y, x, text)
                for x, y, text in fragments
                if left <= x < right and bottom < y <= top
            ]
            value = _clean(
                " ".join(text for _, _, text in sorted(values, key=lambda item: (-item[0], item[1])))
            )
            if value:
                row[field] = value

        number_candidates: list[tuple[float, str]] = []
        for x, y, text in fragments:
            if not (number_bounds[0] <= x < number_bounds[1] and bottom < y <= top):
                continue
            number_candidates.extend(
                (abs(y - anchor_y), match.group(0))
                for match in external_id_pattern.finditer(text)
            )
        if number_candidates:
            row["external_id"] = min(number_candidates)[1]
        elif row.get("name"):
            row["external_id"] = f"project:{_slug(str(row['name']))}"
        rows.append(row)
    return rows


class TabularPdfProjectTrackerAdapter(CollectorAdapter):
    """Configurable collector for official project-list PDFs laid out as fixed columns."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.document_url = str(config.options.get("document_url") or config.base_url)
        self.columns = {
            str(field): (float(bounds[0]), float(bounds[1]))
            for field, bounds in dict(config.options["columns"]).items()
        }
        self.row_labels = {str(value) for value in config.options["row_labels"]}
        self.page_top = float(config.options.get("page_top", 495))
        self.page_bottom = float(config.options.get("page_bottom", 25))
        self.anchor_max_x = float(config.options.get("anchor_max_x", 80))
        self.min_page_count = int(config.options.get("min_page_count", 1))
        self.expected_project_count = int(config.options.get("expected_project_count", 1))
        self.canary_markers = [str(value) for value in config.options.get("canary_markers", [])]
        self.external_id_pattern = re.compile(
            str(config.options.get("external_id_pattern", r"\b[A-Z]{2,4}\d{2}-\d{3,4}\b"))
        )
        self.updated_pattern = re.compile(
            str(config.options.get("updated_pattern", r"Updated\s+(\d{1,2}/\d{1,2}/\d{2,4})")),
            re.IGNORECASE,
        )
        self.timezone = ZoneInfo(str(config.options.get("timezone", "America/Los_Angeles")))
        self._client = client
        self._cached_download: tuple[bytes, dict[str, str]] | None = None

    async def _download(self) -> tuple[bytes, dict[str, str]]:
        if self._cached_download is not None:
            return self._cached_download
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=60, follow_redirects=True)
        try:
            response = await client.get(
                self.document_url,
                headers={"User-Agent": "NS-Trackstar/0.1", "Accept": "application/pdf"},
            )
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise RuntimeError("Tabular project tracker did not return a PDF document")
            self._cached_download = (response.content, dict(response.headers))
            return self._cached_download
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _reader(content: bytes) -> PdfReader:
        return PdfReader(io.BytesIO(content))

    async def canary(self) -> bool:
        content, _ = await self._download()
        reader = self._reader(content)
        if len(reader.pages) < self.min_page_count:
            return False
        sample = _clean("\n".join((page.extract_text() or "") for page in reader.pages[:2]))
        return all(marker.casefold() in sample.casefold() for marker in self.canary_markers)

    def _source_updated_at(self, text: str, headers: dict[str, str]) -> datetime | None:
        match = self.updated_pattern.search(text)
        if match:
            value = match.group(1)
            for date_format in ("%m/%d/%y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(value, date_format).replace(tzinfo=self.timezone)
                except ValueError:
                    continue
        last_modified = headers.get("last-modified")
        if last_modified:
            try:
                return parsedate_to_datetime(last_modified)
            except (TypeError, ValueError):
                return None
        return None

    async def collect(self) -> CollectorResult:
        content, headers = await self._download()
        reader = self._reader(content)
        document_hash = hashlib.sha256(content).hexdigest()
        records: list[NormalizedRecord] = []
        attempted = 0

        for page_number, page in enumerate(reader.pages, start=1):
            fragments: list[Fragment] = []

            def visitor(
                text: str,
                _cm: list[float],
                tm: list[float],
                _font: Any,
                _size: float,
                target: list[Fragment] = fragments,
            ) -> None:
                cleaned = _clean(text)
                if cleaned:
                    target.append((float(tm[4]), float(tm[5]), cleaned))

            page_text = page.extract_text(visitor_text=visitor) or ""
            rows = parse_tabular_page(
                fragments,
                columns=self.columns,
                row_labels=self.row_labels,
                page_top=self.page_top,
                page_bottom=self.page_bottom,
                anchor_max_x=self.anchor_max_x,
                external_id_pattern=self.external_id_pattern,
            )
            attempted += len(rows)
            updated_at = self._source_updated_at(page_text, headers)
            for row_number, normalized in enumerate(rows, start=1):
                external_id = normalized.pop("external_id", None)
                name = normalized.get("name")
                if not external_id or not name:
                    continue
                normalized.update(
                    {
                        "document_sha256": document_hash,
                        "page_number": page_number,
                        "row_number": row_number,
                    }
                )
                records.append(
                    NormalizedRecord(
                        source_key=self.config.key,
                        external_id=str(external_id),
                        canonical_url=self.document_url,
                        source_updated_at=updated_at,
                        raw_payload={
                            "document_sha256": document_hash,
                            "page_number": page_number,
                            "row_number": row_number,
                            "positioned_text": fragments,
                        },
                        normalized_payload=normalized,
                    )
                )

        if len(records) < self.expected_project_count:
            raise RuntimeError(
                "Tabular project tracker parser yield fell below expected project count: "
                f"{len(records)} < {self.expected_project_count}"
            )
        schema = {
            "page_count": len(reader.pages),
            "columns": self.columns,
            "row_labels": sorted(self.row_labels),
        }
        return CollectorResult(
            records=records,
            schema_fingerprint=hashlib.sha256(
                json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            parser_yield=len(records) / attempted if attempted else 0.0,
            metadata={
                "document_sha256": document_hash,
                "page_count": len(reader.pages),
                "rows_detected": attempted,
                "projects_parsed": len(records),
            },
        )
