import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.pdf_project_tracker import PdfProjectTrackerAdapter, parse_project_page


def test_parses_project_fields_and_keeps_tracker_stage_separate() -> None:
    parsed = parse_project_page(
        """Dutch Bros
North of Highway 12 and directly east of the Sunset Center
Property Owner and/or Applicant: Hilbers Inc.
Land Use Designation: Commercial Mixed Use
Zoning: Commercial Mixed Use
Status: In planning review. Planning
Commission tentative, Fall 2025.
Project Description: A 1,025 square foot drive
thru coffee business
""",
        tracker_stage="under_review_or_in_process",
    )

    assert parsed is not None
    assert parsed["name"] == "Dutch Bros"
    assert parsed["location_description"].startswith("North of Highway 12")
    assert parsed["owner_applicant"] == "Hilbers Inc."
    assert parsed["status_text"] == "In planning review. Planning Commission tentative, Fall 2025."
    assert parsed["tracker_stage"] == "under_review_or_in_process"


def test_moves_trailing_geographic_text_out_of_description() -> None:
    parsed = parse_project_page(
        """CALTRANS Lot Swap
Property Owner and/or Applicant: State of California.
Land Use Designation: Waterfront District Specific Plan
Zoning: Downtown Mixed Use
Status: Application not yet submitted
Project Description: Unknown / To Be Determined
South of Highway 12 between Main St. & Civic Center Blvd.
""",
        tracker_stage="future_requires_entitlements",
    )

    assert parsed is not None
    assert parsed["project_description"] == "Unknown / To Be Determined"
    assert parsed["location_description"].startswith("South of Highway 12")


@pytest.mark.asyncio
async def test_collect_preserves_page_text_and_document_hash(monkeypatch) -> None:
    config = SourceConfig(
        key="suisun.development-calendar",
        name="Suisun Development Calendar",
        jurisdiction="City of Suisun City",
        base_url="https://example.test/calendar",
        poll_minutes=1440,
        options={
            "document_url": "https://example.test/calendar.pdf",
            "expected_project_count": 1,
            "page_groups": [{"tracker_stage": "under_review", "pages": [2]}],
        },
    )

    class FakePage:
        def extract_text(self) -> str:
            return """Dutch Bros
North of Highway 12
Property Owner: Hilbers Inc.
Status: In planning review
Project Description: Drive thru coffee business
"""

    class FakeReader:
        def __init__(self) -> None:
            self.pages = [FakePage(), FakePage()]

    async def fake_download(self) -> tuple[bytes, dict[str, str]]:
        return b"%PDF-test", {"last-modified": "Wed, 17 Sep 2025 22:05:44 GMT"}

    monkeypatch.setattr(PdfProjectTrackerAdapter, "_download", fake_download)
    monkeypatch.setattr(PdfProjectTrackerAdapter, "_reader", staticmethod(lambda _: FakeReader()))
    adapter = PdfProjectTrackerAdapter(config)
    result = await adapter.collect()

    assert result.parser_yield == 1.0
    assert result.records[0].external_id == "project:dutch-bros"
    assert result.records[0].normalized_payload["page_number"] == 2
    assert result.records[0].raw_payload["extracted_text"].startswith("Dutch Bros")
    assert result.records[0].source_updated_at is not None


@pytest.mark.asyncio
async def test_rejects_non_pdf_response() -> None:
    config = SourceConfig(
        key="test.pdf",
        name="Test PDF",
        jurisdiction=None,
        base_url="https://example.test/calendar.pdf",
        poll_minutes=1440,
        options={"min_page_count": 1},
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="blocked")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="did not return a PDF"):
            await PdfProjectTrackerAdapter(config, client=client).canary()
