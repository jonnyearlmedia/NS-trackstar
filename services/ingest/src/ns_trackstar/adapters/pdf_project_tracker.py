from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pypdf import PdfReader

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

_FIELD_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "owner_applicant",
        re.compile(r"^Property Owner(?: and/or Applicant)?:\s*(.*)$", re.IGNORECASE),
    ),
    ("land_use_designation", re.compile(r"^Land Use Designation:\s*(.*)$", re.IGNORECASE)),
    (
        "zoning",
        re.compile(r"^(?:Zoning Classification|Zoning|Zone)\s*:\s*(.*)$", re.IGNORECASE),
    ),
    ("status_text", re.compile(r"^Status:\s*(.*)$", re.IGNORECASE)),
    ("project_description", re.compile(r"^Project Description:\s*(.*)$", re.IGNORECASE)),
)
_LOCATION_PREFIXES = (
    "between ",
    "east of ",
    "multiple parcel",
    "north of ",
    "northeast ",
    "northwest ",
    "south of ",
    "southeast ",
    "southwest ",
    "west of ",
)


def _clean(value: str) -> str:
    return " ".join(value.split()).strip()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")


def _field_match(line: str) -> tuple[str, str] | None:
    for field, pattern in _FIELD_LABELS:
        match = pattern.match(line)
        if match:
            return field, match.group(1)
    return None


def parse_project_page(text: str, *, tracker_stage: str) -> dict[str, Any] | None:
    """Parse a one-project-per-page municipal tracker without inventing missing fields."""
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    if not lines:
        return None

    first_label = next((index for index, line in enumerate(lines) if _field_match(line)), None)
    if first_label is None:
        return None

    name = lines[0]
    location_lines = lines[1:first_label]
    fields: dict[str, list[str]] = {}
    current_field: str | None = None

    for line in lines[first_label:]:
        matched = _field_match(line)
        if matched:
            current_field, initial = matched
            fields[current_field] = [initial] if initial else []
        elif current_field:
            fields[current_field].append(line)

    # A few slide-authored PDFs extract a visually top-left location after the
    # description text. Split only explicit geographic-looking trailing lines.
    description_lines = fields.get("project_description", [])
    trailing_location_at = next(
        (
            index
            for index, line in enumerate(description_lines[1:], start=1)
            if line.casefold().startswith(_LOCATION_PREFIXES)
        ),
        None,
    )
    if trailing_location_at is not None:
        location_lines.extend(description_lines[trailing_location_at:])
        fields["project_description"] = description_lines[:trailing_location_at]

    normalized: dict[str, Any] = {
        "record_kind": "curated_project",
        "name": name,
        "tracker_stage": tracker_stage,
        "source_text": "\n".join(lines),
    }
    if location_lines:
        normalized["location_description"] = _clean(" ".join(location_lines))
    for field, values in fields.items():
        value = _clean(" ".join(values))
        if value:
            normalized[field] = value
    return normalized


class PdfProjectTrackerAdapter(CollectorAdapter):
    """Collect a public PDF where each configured page describes one project."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.document_url = str(config.options.get("document_url") or config.base_url)
        self.page_groups = list(config.options.get("page_groups") or [])
        self.expected_project_count = int(config.options.get("expected_project_count", 1))
        self.min_page_count = int(config.options.get("min_page_count", 1))
        self.canary_markers = [str(value) for value in config.options.get("canary_markers", [])]
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
            content = response.content
            if not content.startswith(b"%PDF"):
                raise RuntimeError("PDF project tracker did not return a PDF document")
            self._cached_download = (content, dict(response.headers))
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
        sample_text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
        return all(marker.casefold() in sample_text.casefold() for marker in self.canary_markers)

    @staticmethod
    def _header_datetime(headers: dict[str, str], name: str) -> datetime | None:
        value = headers.get(name)
        if not value:
            return None
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

    async def collect(self) -> CollectorResult:
        content, headers = await self._download()
        reader = self._reader(content)
        document_hash = hashlib.sha256(content).hexdigest()
        records: list[NormalizedRecord] = []
        attempted = 0

        for group in self.page_groups:
            tracker_stage = str(group["tracker_stage"])
            for page_number_value in group.get("pages") or []:
                page_number = int(page_number_value)
                attempted += 1
                if page_number < 1 or page_number > len(reader.pages):
                    continue
                text = reader.pages[page_number - 1].extract_text() or ""
                normalized = parse_project_page(text, tracker_stage=tracker_stage)
                if not normalized:
                    continue
                name = str(normalized["name"])
                records.append(
                    NormalizedRecord(
                        source_key=self.config.key,
                        external_id=f"project:{_slug(name)}",
                        canonical_url=self.document_url,
                        source_updated_at=self._header_datetime(headers, "last-modified"),
                        raw_payload={
                            "document_sha256": document_hash,
                            "page_number": page_number,
                            "extracted_text": text,
                        },
                        normalized_payload={
                            **normalized,
                            "document_sha256": document_hash,
                            "page_number": page_number,
                        },
                    )
                )

        parser_yield = len(records) / attempted if attempted else 0.0
        if len(records) < self.expected_project_count:
            raise RuntimeError(
                "PDF project tracker parser yield fell below expected project count: "
                f"{len(records)} < {self.expected_project_count}"
            )

        schema = {
            "page_count": len(reader.pages),
            "configured_pages": [
                int(page)
                for group in self.page_groups
                for page in (group.get("pages") or [])
            ],
            "fields": [field for field, _ in _FIELD_LABELS],
        }
        return CollectorResult(
            records=records,
            schema_fingerprint=hashlib.sha256(
                json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            parser_yield=parser_yield,
            metadata={
                "document_sha256": document_hash,
                "page_count": len(reader.pages),
                "project_pages_attempted": attempted,
                "projects_parsed": len(records),
            },
        )
