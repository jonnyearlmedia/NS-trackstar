from datetime import UTC, datetime
from uuid import UUID

import pytest

from ns_trackstar_api.app import app, project_detail


@pytest.mark.asyncio
async def test_project_detail_exposes_source_links_and_location_accuracy() -> None:
    project_id = UUID("96fdc652-da24-4fd7-ab06-49c01ed4b1ae")

    class Cursor:
        async def fetchone(self):
            return {
                "id": project_id,
                "canonical_name": "Suisun Logistics Center",
                "project_type": "municipal_development",
                "last_activity_at": datetime(2026, 7, 27, tzinfo=UTC),
                "geometry": {"type": "Point", "coordinates": [-121.98, 38.2394]},
                "location": {
                    "method": "source_coordinate",
                    "source": "CEQAnet location coordinates",
                    "accuracy": "approximate_area",
                    "accuracy_meters": None,
                    "confidence": None,
                },
                "statuses": {
                    "environmental": "document_type_eir",
                    "official_tracker_stage": "under_review_or_in_process",
                },
                "assertions": [],
                "sources": [
                    {
                        "source_key": "california.ceqanet.napa-solano",
                        "source_name": "California CEQAnet — Napa and Solano Counties",
                        "relationship_type": "environmental_review_for",
                        "confidence": 1,
                        "evidence": {"signals": ["SCH and address"]},
                        "url": "https://ceqanet.lci.ca.gov/Project/2021010044",
                    }
                ],
            }

    class Database:
        async def execute(self, _query, _params):
            return Cursor()

    previous = getattr(app.state, "db", None)
    app.state.db = Database()
    try:
        result = await project_detail(project_id)
    finally:
        if previous is None:
            del app.state.db
        else:
            app.state.db = previous

    assert result["location"]["accuracy"] == "approximate_area"
    assert result["sources"][0]["relationship_type"] == "environmental_review_for"
    assert result["sources"][0]["evidence"] == {"signals": ["SCH and address"]}
    assert result["sources"][0]["url"].endswith("2021010044")
