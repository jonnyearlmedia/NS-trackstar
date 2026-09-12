from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from ns_trackstar.adapters.base import CollectorAdapter, SourceBlockedError, SourceConfig
from ns_trackstar.models import CollectorResult, NormalizedRecord

DEFAULT_SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
COURTLISTENER_ORIGIN = "https://www.courtlistener.com"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _schema_fingerprint(payloads: list[dict[str, Any]]) -> str | None:
    if not payloads:
        return None
    root_keys = sorted({key for payload in payloads for key in payload})
    result_keys = sorted(
        {
            key
            for payload in payloads
            for result in payload.get("results", [])[:25]
            if isinstance(result, dict)
            for key in result
        }
    )
    schema = {"root": root_keys, "results": result_keys}
    return hashlib.sha256(json.dumps(schema, separators=(",", ":")).encode()).hexdigest()


def _courtlistener_docket_url(value: Any) -> str | None:
    if not value:
        return None
    candidate = urljoin(COURTLISTENER_ORIGIN, str(value))
    parsed = urlparse(candidate)
    if (
        parsed.scheme == "https"
        and parsed.netloc == "www.courtlistener.com"
        and parsed.path.startswith("/docket/")
    ):
        return candidate
    return None


class CourtListenerAdapter(CollectorAdapter):
    """Search RECAP docket metadata through CourtListener's token-gated v4 API."""

    def __init__(self, config: SourceConfig, *, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(config)
        self.search_url = str(config.options.get("search_url") or DEFAULT_SEARCH_URL)
        self.query_terms = [
            str(query).strip()
            for query in config.options.get("query_terms", [])
            if str(query).strip()
        ]
        if not self.query_terms:
            raise ValueError("CourtListener requires at least one configured query term")
        self.max_pages_per_query = min(
            max(int(config.options.get("max_pages_per_query", 3)), 1), 20
        )
        self.token_env = str(config.options.get("token_env") or "COURTLISTENER_API_TOKEN")
        self._client = client

        parsed = urlparse(self.search_url)
        if parsed.scheme != "https" or parsed.netloc != "www.courtlistener.com":
            raise ValueError("CourtListener search_url must use the official HTTPS API host")
        self._allowed_path = parsed.path.rstrip("/") + "/"

    def _token(self) -> str:
        token = os.environ.get(self.token_env, "").strip()
        if not token:
            raise SourceBlockedError(
                f"Missing CourtListener API token in environment variable {self.token_env}"
            )
        return token

    def _safe_continuation(self, value: Any) -> str | None:
        if value is None:
            return None
        continuation = str(value)
        parsed = urlparse(continuation)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "www.courtlistener.com"
            or parsed.path.rstrip("/") + "/" != self._allowed_path
        ):
            raise RuntimeError("CourtListener returned an unsafe pagination URL")
        return continuation

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30, follow_redirects=False)
        try:
            response = await client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Token {self._token()}",
                    "Accept": "application/json",
                    "User-Agent": "NS-Trackstar/0.1",
                },
            )
            if response.status_code in {401, 403}:
                raise SourceBlockedError(
                    "CourtListener rejected the configured API token or denied API access"
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("CourtListener search response is not an object")
            if not isinstance(payload.get("results"), list) or "count" not in payload:
                raise TypeError("CourtListener search response is missing count/results")
            return payload
        finally:
            if owns_client:
                await client.aclose()

    async def canary(self) -> bool:
        payload = await self._get_json(
            self.search_url,
            params={"q": self.query_terms[0], "type": "d"},
        )
        results = payload["results"]
        if not results:
            return True
        sample = results[0]
        return (
            isinstance(sample, dict)
            and sample.get("docket_id") is not None
            and "docketNumber" in sample
            and "caseName" in sample
        )

    async def _search_query(
        self, query: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        results: list[dict[str, Any]] = []
        payloads: list[dict[str, Any]] = []
        pages = 0
        next_url: str | None = self.search_url
        params: dict[str, str] | None = {"q": query, "type": "d"}

        while next_url is not None and pages < self.max_pages_per_query:
            payload = await self._get_json(next_url, params=params)
            payloads.append(payload)
            results.extend(result for result in payload["results"] if isinstance(result, dict))
            pages += 1
            next_url = self._safe_continuation(payload.get("next"))
            params = None
        return results, payloads, pages

    def _record(self, result: dict[str, Any], *, matched_query: str) -> NormalizedRecord | None:
        docket_id = result.get("docket_id")
        if docket_id is None:
            return None
        docket_path = result.get("docket_absolute_url") or result.get("absolute_url")
        canonical_url = _courtlistener_docket_url(docket_path)
        parties = result.get("party")
        if not isinstance(parties, list):
            parties = []
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        normalized = {
            "record_kind": "federal_docket",
            "docket_id": str(docket_id),
            "docket_number": result.get("docketNumber"),
            "pacer_case_id": result.get("pacer_case_id"),
            "case_name": result.get("caseName") or result.get("case_name_full"),
            "parties": [str(party) for party in parties],
            "court": result.get("court"),
            "court_id": result.get("court_id"),
            "date_filed": result.get("dateFiled"),
            "date_terminated": result.get("dateTerminated"),
            "cause": result.get("cause"),
            "nature_of_suit": result.get("suitNature"),
            "jurisdiction_type": result.get("jurisdictionType"),
            "matched_queries": [matched_query],
            "courtlistener_url": canonical_url,
        }
        return NormalizedRecord(
            source_key=self.config.key,
            external_id=f"docket:{docket_id}",
            canonical_url=canonical_url,
            source_created_at=_parse_datetime(result.get("dateFiled")),
            source_updated_at=_parse_datetime(meta.get("timestamp")),
            raw_payload=result,
            normalized_payload=normalized,
        )

    async def collect(self) -> CollectorResult:
        records_by_id: dict[str, NormalizedRecord] = {}
        payloads: list[dict[str, Any]] = []
        raw_results_seen = 0
        pages_fetched = 0
        skipped = 0

        for query in self.query_terms:
            results, query_payloads, pages = await self._search_query(query)
            payloads.extend(query_payloads)
            raw_results_seen += len(results)
            pages_fetched += pages
            for result in results:
                record = self._record(result, matched_query=query)
                if record is None:
                    skipped += 1
                    continue
                existing = records_by_id.get(record.external_id)
                if existing is None:
                    records_by_id[record.external_id] = record
                elif query not in existing.normalized_payload["matched_queries"]:
                    existing.normalized_payload["matched_queries"].append(query)

        parsed = raw_results_seen - skipped
        parser_yield = parsed / raw_results_seen if raw_results_seen else 1.0
        return CollectorResult(
            records=list(records_by_id.values()),
            schema_fingerprint=_schema_fingerprint(payloads),
            parser_yield=parser_yield,
            metadata={
                "query_count": len(self.query_terms),
                "queries": self.query_terms,
                "pages_fetched": pages_fetched,
                "raw_results_seen": raw_results_seen,
                "unique_dockets": len(records_by_id),
                "results_skipped_without_docket_id": skipped,
                "api_version": "v4",
                "result_type": "d",
                "pacer_fetch_used": False,
            },
        )
