from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord


class FederalRegisterAdapter(CollectorAdapter):
    """Collector for the documented, anonymous FederalRegister.gov API."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self._client = client
        self.api_url = str(
            config.options.get(
                "api_url", "https://www.federalregister.gov/api/v1/documents.json"
            )
        )
        self.terms = [str(term) for term in config.options.get("terms", [])]
        self.per_page = min(int(config.options.get("per_page", 100)), 1000)
        self.max_pages = max(1, int(config.options.get("max_pages_per_term", 5)))
        self.start_date = config.options.get("start_date")
        self.canary_document_number = str(
            config.options.get("canary_document_number", "2024-23655")
        )

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        finally:
            if owns_client:
                await client.aclose()

    async def canary(self) -> bool:
        payload = await self._get_json(
            f"https://www.federalregister.gov/api/v1/documents/"
            f"{self.canary_document_number}.json"
        )
        return payload.get("document_number") == self.canary_document_number and bool(
            payload.get("html_url")
        )

    async def collect(self) -> CollectorResult:
        if not self.terms:
            raise ValueError("Federal Register source requires at least one configured term")

        documents: dict[str, dict[str, Any]] = {}
        attempted = 0
        parsed = 0
        schema_keys: set[str] = set()
        for term in self.terms:
            for page in range(1, self.max_pages + 1):
                params: dict[str, Any] = {
                    "conditions[term]": term,
                    "per_page": self.per_page,
                    "page": page,
                    "order": "newest",
                }
                if self.start_date:
                    params["conditions[publication_date][gte]"] = self.start_date
                payload = await self._get_json(self.api_url, params)
                results = payload.get("results")
                if not isinstance(results, list):
                    raise TypeError("Federal Register results schema is missing")
                attempted += len(results)
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    document_number = item.get("document_number")
                    if document_number:
                        parsed += 1
                        documents[str(document_number)] = item
                        schema_keys.update(item)
                if page >= int(payload.get("total_pages") or 1) or len(results) < self.per_page:
                    break

        records: list[NormalizedRecord] = []
        for document_number, item in documents.items():
            publication_date = item.get("publication_date")
            published_at = None
            if publication_date:
                published_at = datetime.fromisoformat(str(publication_date)).replace(tzinfo=UTC)
            normalized = {
                "document_number": document_number,
                "title": item.get("title"),
                "document_type": item.get("type"),
                "abstract": item.get("abstract"),
                "publication_date": publication_date,
                "agencies": [
                    agency.get("name")
                    for agency in item.get("agencies", [])
                    if isinstance(agency, dict) and agency.get("name")
                ],
                "citation": item.get("citation"),
                "docket_ids": item.get("docket_ids") or [],
                "search_terms": self.terms,
            }
            records.append(
                NormalizedRecord(
                    source_key=self.config.key,
                    external_id=document_number,
                    canonical_url=item.get("html_url"),
                    source_created_at=published_at,
                    source_updated_at=published_at,
                    raw_payload=item,
                    normalized_payload=normalized,
                )
            )

        schema_fingerprint = hashlib.sha256(
            json.dumps(sorted(schema_keys), separators=(",", ":")).encode()
        ).hexdigest()
        return CollectorResult(
            records=sorted(records, key=lambda record: record.external_id),
            schema_fingerprint=schema_fingerprint,
            parser_yield=parsed / attempted if attempted else 1.0,
            metadata={
                "terms": self.terms,
                "documents": len(documents),
                "results_attempted": attempted,
                "duplicates": parsed - len(documents),
            },
        )
