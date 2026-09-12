from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord


def _action_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class OfficialDocumentSetAdapter(CollectorAdapter):
    """Collect an explicit set of public agency PDFs as immutable source evidence.

    This adapter is deliberately a document-set collector, not a discovery scraper. It is
    useful when an agency publishes authoritative PDFs but exposes no stable anonymous listing
    API. Status assertions are configured per document and remain separate dimensions; the
    adapter never infers a current status from PDF prose.
    """

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.documents = list(config.options.get("documents") or [])
        self.allowed_hosts = {
            str(host).casefold() for host in config.options.get("allowed_hosts") or []
        }
        self.canary_external_id = str(config.options.get("canary_external_id") or "")
        self._client = client
        self._cache: dict[str, tuple[bytes, str]] = {}

    def _document(self, external_id: str) -> dict[str, Any]:
        try:
            return next(
                document
                for document in self.documents
                if str(document.get("external_id")) == external_id
            )
        except StopIteration as exc:
            raise ValueError(f"Unknown official document external_id: {external_id}") from exc

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Official document URLs must use HTTPS")
        if self.allowed_hosts and parsed.hostname.casefold() not in self.allowed_hosts:
            raise ValueError(f"Official document host is not allowlisted: {parsed.hostname}")

    async def _download(self, document: dict[str, Any]) -> tuple[bytes, str]:
        external_id = str(document["external_id"])
        if external_id in self._cache:
            return self._cache[external_id]
        url = str(document["document_url"])
        self._validate_url(url)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=60, follow_redirects=True)
        try:
            response = await client.get(
                url,
                headers={"User-Agent": "NS-Trackstar/0.1", "Accept": "application/pdf"},
            )
            response.raise_for_status()
            content = response.content
            if not content.startswith(b"%PDF"):
                raise RuntimeError(f"Official document {external_id} did not return a PDF")
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
            self._cache[external_id] = (content, text)
            return self._cache[external_id]
        finally:
            if owns_client:
                await client.aclose()

    async def canary(self) -> bool:
        if not self.documents or not self.canary_external_id:
            return False
        document = self._document(self.canary_external_id)
        _, text = await self._download(document)
        markers = [str(marker) for marker in document.get("canary_markers") or []]
        folded_text = text.casefold()
        return all(marker.casefold() in folded_text for marker in markers)

    async def collect(self) -> CollectorResult:
        if not self.documents:
            raise ValueError("Official document source requires at least one document")

        records: list[NormalizedRecord] = []
        schema: set[tuple[str, ...]] = set()
        dimensions: set[str] = set()
        for document in self.documents:
            external_id = str(document["external_id"])
            content, text = await self._download(document)
            markers = [str(marker) for marker in document.get("canary_markers") or []]
            folded_text = text.casefold()
            if not all(marker.casefold() in folded_text for marker in markers):
                raise RuntimeError(f"Official document markers failed for {external_id}")

            assertions = list(document.get("status_assertions") or [])
            for assertion in assertions:
                if not isinstance(assertion, dict) or not assertion.get("dimension"):
                    raise ValueError(f"Invalid status assertion in {external_id}")
                dimensions.add(str(assertion["dimension"]))

            document_hash = hashlib.sha256(content).hexdigest()
            normalized = {
                key: value
                for key, value in document.items()
                if key not in {"canary_markers", "document_url"}
            }
            normalized.update(
                {
                    "record_kind": "official_decision_document",
                    "document_sha256": document_hash,
                    "document_url": str(document["document_url"]),
                }
            )
            schema.add(tuple(sorted(normalized)))
            action_at = _action_datetime(document.get("action_date"))
            records.append(
                NormalizedRecord(
                    source_key=self.config.key,
                    external_id=external_id,
                    canonical_url=str(document["document_url"]),
                    source_created_at=action_at,
                    source_updated_at=action_at,
                    raw_payload={
                        "document_sha256": document_hash,
                        "extracted_text": text,
                    },
                    normalized_payload=normalized,
                )
            )

        fingerprint_payload = {
            "record_schemas": sorted(schema),
            "status_dimensions": sorted(dimensions),
        }
        return CollectorResult(
            records=records,
            schema_fingerprint=hashlib.sha256(
                json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            parser_yield=1.0,
            metadata={
                "documents_configured": len(self.documents),
                "documents_returned": len(records),
                "discovery_mode": "explicit_document_set",
                "status_dimensions": sorted(dimensions),
            },
        )
