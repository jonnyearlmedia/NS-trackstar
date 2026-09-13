from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.courtlistener import CourtListenerAdapter
from ns_trackstar.config import load_source_config
from ns_trackstar.registry import build_adapter


def _config(**options) -> SourceConfig:
    return SourceConfig(
        key="courtlistener.recap.napa-solano",
        name="CourtListener RECAP Napa Solano",
        jurisdiction="Napa and Solano Counties",
        base_url="https://www.courtlistener.com/",
        poll_minutes=1440,
        options={"query_terms": ["Scotts Valley Band of Pomo Indians"], **options},
    )


def _docket(docket_id: int = 73414675) -> dict:
    return {
        "caseName": "Example Tribal Plaintiff v. U.S. Department of the Interior",
        "case_name_full": "",
        "court": "District Court, D. District of Columbia",
        "court_id": "dcd",
        "dateFiled": "2025-01-17",
        "dateTerminated": None,
        "docketNumber": "1:25-cv-00123",
        "docket_absolute_url": f"/docket/{docket_id}/example-case/",
        "docket_id": docket_id,
        "pacer_case_id": "123456",
        "party": ["Example Tribal Plaintiff", "U.S. Department of the Interior"],
        "cause": "Administrative Procedure Act",
        "suitNature": "Civil",
        "jurisdictionType": "U.S. Government Defendant",
        "meta": {"timestamp": "2026-09-01T12:30:00Z"},
    }


def test_smoke_config_builds_registered_adapter() -> None:
    config_path = Path(__file__).parents[3] / "config" / "smoke" / "napa-solano.courtlistener.json"
    adapter_name, config = load_source_config(config_path)

    assert adapter_name == "courtlistener"
    assert isinstance(build_adapter(adapter_name, config), CourtListenerAdapter)


@pytest.mark.asyncio
async def test_missing_token_fails_as_blocked(monkeypatch) -> None:
    monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
    adapter = CourtListenerAdapter(_config())

    with pytest.raises(SourceBlockedError, match="Missing CourtListener API token"):
        await adapter.canary()


@pytest.mark.asyncio
async def test_search_contract_paginates_and_preserves_docket_provenance(monkeypatch) -> None:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Token test-token"
        if request.url.params.get("cursor"):
            return httpx.Response(
                200,
                json={"count": 2, "next": None, "previous": "previous", "results": [_docket(2)]},
            )
        assert request.url.params["type"] == "d"
        assert request.url.params["q"] == "Scotts Valley Band of Pomo Indians"
        return httpx.Response(
            200,
            json={
                "count": 2,
                "next": "https://www.courtlistener.com/api/rest/v4/search/?cursor=next-page",
                "previous": None,
                "results": [_docket(1)],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await CourtListenerAdapter(_config(max_pages_per_query=2), client=client).collect()

    assert len(requests) == 2
    assert len(result.records) == 2
    record = result.records[0]
    assert record.external_id == "docket:1"
    assert record.canonical_url == "https://www.courtlistener.com/docket/1/example-case/"
    assert record.normalized_payload["docket_number"] == "1:25-cv-00123"
    assert record.normalized_payload["court_id"] == "dcd"
    assert record.normalized_payload["parties"] == [
        "Example Tribal Plaintiff",
        "U.S. Department of the Interior",
    ]
    assert record.normalized_payload["date_filed"] == "2025-01-17"
    assert result.metadata["pacer_fetch_used"] is False
    assert result.parser_yield == 1
    assert result.schema_fingerprint


@pytest.mark.asyncio
async def test_multiple_configured_queries_deduplicate_same_docket(monkeypatch) -> None:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"count": 1, "next": None, "previous": None, "results": [_docket()]},
        )

    config = _config(query_terms=["Scotts Valley", "Vallejo casino"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await CourtListenerAdapter(config, client=client).collect()

    assert len(result.records) == 1
    assert result.records[0].normalized_payload["matched_queries"] == [
        "Scotts Valley",
        "Vallejo casino",
    ]
    assert result.metadata["raw_results_seen"] == 2
    assert result.metadata["unique_dockets"] == 1


@pytest.mark.asyncio
async def test_canary_rejects_changed_search_schema(monkeypatch) -> None:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 0, "items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CourtListenerAdapter(_config(), client=client)
        with pytest.raises(TypeError, match="missing count/results"):
            await adapter.canary()


@pytest.mark.asyncio
async def test_invalid_or_denied_token_is_blocked(monkeypatch) -> None:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "invalid-token")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid token."})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceBlockedError, match="rejected"):
            await CourtListenerAdapter(_config(), client=client).canary()


@pytest.mark.asyncio
async def test_pagination_cannot_leave_official_search_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "count": 1,
                "next": "https://example.com/steal-token",
                "previous": None,
                "results": [_docket()],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="unsafe pagination URL"):
            await CourtListenerAdapter(_config(), client=client).collect()
