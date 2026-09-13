import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.federal_register import FederalRegisterAdapter


def config() -> SourceConfig:
    return SourceConfig(
        key="federal-register.test",
        name="Federal Register test",
        jurisdiction="United States",
        base_url="https://www.federalregister.gov/",
        poll_minutes=1440,
        options={"terms": ["Napa County", "Scotts Valley"], "per_page": 100},
    )


@pytest.mark.asyncio
async def test_canary_requires_known_document_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/2024-23655.json")
        return httpx.Response(
            200,
            json={
                "document_number": "2024-23655",
                "html_url": "https://www.federalregister.gov/documents/2024-23655",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await FederalRegisterAdapter(config(), client=client).canary() is True


@pytest.mark.asyncio
async def test_collect_deduplicates_terms_and_preserves_regulatory_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        term = request.url.params["conditions[term]"]
        return httpx.Response(
            200,
            json={
                "total_pages": 1,
                "results": [
                    {
                        "document_number": "2025-10001",
                        "title": f"Federal action concerning {term}",
                        "type": "Notice",
                        "abstract": "Public notice",
                        "publication_date": "2025-06-01",
                        "html_url": "https://www.federalregister.gov/documents/2025-10001",
                        "agencies": [{"name": "Indian Affairs Bureau"}],
                        "docket_ids": ["BIA-2025-1"],
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await FederalRegisterAdapter(config(), client=client).collect()

    assert len(result.records) == 1
    assert result.parser_yield == 1.0
    assert result.metadata["duplicates"] == 1
    record = result.records[0]
    assert record.external_id == "2025-10001"
    assert record.normalized_payload["docket_ids"] == ["BIA-2025-1"]
    assert record.normalized_payload["agencies"] == ["Indian Affairs Bureau"]
    assert record.geometry_geojson is None
