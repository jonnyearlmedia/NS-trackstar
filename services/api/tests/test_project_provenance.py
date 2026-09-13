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
                "assertions": [
                    {
                        "field": "description",
                        "value": (
                            "A logistics and warehouse campus proposed on vacant land "
                            "north of the rail line, with truck access improvements."
                        ),
                        "source_url": "https://ceqanet.lci.ca.gov/Project/2021010044",
                    },
                    {"field": "building_area_sqft", "value": 480000, "source_url": None},
                    {"field": "apn", "value": "0032-190-140", "source_url": None},
                ],
                "recent_events": [
                    {
                        "event_type": "environmental_changed",
                        "title": "Environmental changed to document_type_eir",
                        "summary": None,
                        "occurred_at": "2026-07-27T00:00:00+00:00",
                        "observed_at": "2026-07-27T00:00:00+00:00",
                        "significance": 0.75,
                    }
                ],
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

    # The consumer answer is composed deterministically from the same evidence and
    # never degrades into generic filler copy.
    explainer = result["explainer"]
    assert explainer["what_is_this"].startswith("A logistics and warehouse campus")
    assert "Napa" not in explainer["what_is_this"]
    assert explainer["evidence_backed"] is True
    assert explainer["whats_happening"].startswith("Environmental changed to")
    assert {fact["field"] for fact in explainer["why_care"]} == {"building_area_sqft"}
    assert result["summary"] == explainer["what_is_this"]

    # Technical evidence stays available, grouped rather than allowlisted away.
    sections = {section["key"]: section for section in result["evidence_sections"]}
    assert sections["scale"]["items"][0]["field"] == "building_area_sqft"
    assert sections["identifiers"]["items"][0]["field"] == "apn"
    assert sections["identifiers"]["items"][0]["bureaucratic"] is True
