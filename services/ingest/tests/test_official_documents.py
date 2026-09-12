import io

import httpx
import pytest
from pypdf import PdfWriter

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.official_documents import OfficialDocumentSetAdapter


def pdf_bytes() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


def config() -> SourceConfig:
    return SourceConfig(
        key="bia.test",
        name="BIA test decisions",
        jurisdiction="United States",
        base_url="https://www.bia.gov/",
        poll_minutes=1440,
        options={
            "allowed_hosts": ["www.bia.gov"],
            "canary_external_id": "decision-1",
            "documents": [
                {
                    "external_id": "decision-1",
                    "document_url": "https://www.bia.gov/decision-1.pdf",
                    "action_date": "2025-03-27",
                    "title": "Partial reconsideration",
                    "canary_markers": [],
                    "status_assertions": [
                        {
                            "dimension": "gaming_eligibility",
                            "value": "temporarily_rescinded_for_reconsideration",
                            "direct": True,
                        }
                    ],
                },
                {
                    "external_id": "decision-2",
                    "document_url": "https://www.bia.gov/decision-2.pdf",
                    "action_date": "2026-07-30",
                    "title": "Reconsideration decision",
                    "supersedes_external_id": "decision-1",
                    "status_assertions": [
                        {
                            "dimension": "gaming_eligibility",
                            "value": "restored_lands_exception_disapproved",
                            "direct": True,
                        }
                    ],
                },
            ],
        },
    )


@pytest.mark.asyncio
async def test_collect_preserves_separate_dated_document_assertions() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=pdf_bytes()))
    ) as client:
        adapter = OfficialDocumentSetAdapter(config(), client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 2
    assert result.parser_yield == 1.0
    assert result.metadata["discovery_mode"] == "explicit_document_set"
    assert result.metadata["status_dimensions"] == ["gaming_eligibility"]
    assert result.records[0].source_created_at.isoformat() == "2025-03-27T00:00:00+00:00"
    assert result.records[1].normalized_payload["supersedes_external_id"] == "decision-1"
    assert result.records[0].geometry_geojson is None


@pytest.mark.asyncio
async def test_rejects_non_allowlisted_document_redirect_target() -> None:
    source = config()
    source.options["documents"][0]["document_url"] = "https://example.com/decision.pdf"
    adapter = OfficialDocumentSetAdapter(source)
    with pytest.raises(ValueError, match="not allowlisted"):
        await adapter.canary()


@pytest.mark.asyncio
async def test_rejects_non_pdf_response() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="blocked"))
    ) as client:
        with pytest.raises(RuntimeError, match="did not return a PDF"):
            await OfficialDocumentSetAdapter(config(), client=client).collect()
