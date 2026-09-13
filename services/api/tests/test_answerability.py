"""A major project must never render as a generic card.

These tests prove the composer turns each fixture's declared evidence shape into a real
consumer answer. They deliberately use neutral placeholder values rather than real
figures, because this repository must not assert a fact about a real project that
Trackstar has not actually collected. Whether production *holds* that evidence is a
separate check against the deployed API.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ns_trackstar_api.narrative import compose_evidence_sections, compose_explainer

FIXTURES = json.loads(
    Path("fixtures/answerability/napa-solano.json").read_text()
)
PROJECTS = FIXTURES["projects"]
IDS = [project["key"] for project in PROJECTS]

# Placeholder values by field. Numbers are obviously synthetic; the point is the shape.
PLACEHOLDERS: dict[str, object] = {
    "description": "This project would be described here in the agency's own words, "
                   "in a sentence a resident can follow without any background.",
    "residential_units": 100,
    "site_acres": 10,
    "building_area_sqft": 50000,
    "length_miles": 2,
    "estimated_cost": 1_000_000,
    "address": "100 Example Street",
    "location_description": "Along the example corridor",
    "state_highways": "SR-29",
    "apn": "0000-000-000",
    "planned_construction_start": "2027-04-01",
    "planned_completion": "2028-06-01",
    "completion_date": "2028-06-01",
    "public_hearings": "Planning Commission, date to be noticed",
    "construction_year": "2027",
    "fiscal_year": "2027-28",
}

GENERIC_PHRASES = (
    "a development project in napa",
    "napa-solano",
    "napa–solano",
    "open details for official records",
)


def evidence_for(project: dict) -> list[dict]:
    fields = (
        project["identity_fields"]
        + project["scale_fields"]
        + project["location_fields"]
        + project["next_step_fields"]
    )
    return [
        {"field": field, "value": PLACEHOLDERS[field], "source_url": None, "source_key": "test"}
        for field in fields
        if field in PLACEHOLDERS
    ]


def explainer_for(project: dict):
    return compose_explainer(
        name=project["name"],
        project_type="municipal_development",
        consumer_category="development",
        lifecycle_stage="review",
        assertions=evidence_for(project),
        statuses={dimension: "under_review" for dimension in project["status_dimensions"]},
        events=[
            {
                "event_type": "planning_changed",
                "title": "Planning changed to under review",
                "summary": "The application moved into official review.",
                "occurred_at": datetime(2026, 8, 4, tzinfo=UTC),
            }
        ],
        now=datetime(2026, 9, 13, tzinfo=UTC),
    )


def test_every_declared_field_has_a_placeholder():
    """A missing placeholder would silently drop a field from the whole contract."""

    declared = {
        field
        for project in PROJECTS
        for key in ("identity_fields", "scale_fields", "location_fields", "next_step_fields")
        for field in project[key]
    }
    assert declared <= set(PLACEHOLDERS), sorted(declared - set(PLACEHOLDERS))


def test_the_ten_named_vallejo_projects_are_all_present():
    vallejo = [project["key"] for project in PROJECTS if project["jurisdiction"] == "vallejo"]
    assert vallejo == [
        "scotts-valley-casino",
        "fairview-at-northgate",
        "mare-island-specific-plan",
        "solano360",
        "sr29-sonoma-complete-streets",
        "mare-island-causeway-bridge",
        "vallejo-waterfront-specific-plan",
        "downtown-vallejo-specific-plan",
        "coral-sea-village-8c",
        "vista-cove",
    ]


def test_every_jurisdiction_is_either_represented_or_explicitly_awaiting_a_source():
    represented = {project["jurisdiction"] for project in PROJECTS}
    awaiting = {entry["jurisdiction"] for entry in FIXTURES["awaiting_source"]}
    assert represented | awaiting == {
        "napa", "american-canyon", "yountville", "st-helena", "calistoga", "napa-county",
        "vallejo", "benicia", "fairfield", "suisun-city", "vacaville", "dixon",
        "rio-vista", "solano-county",
    }
    assert not (represented & awaiting), "a jurisdiction cannot be both covered and awaiting"
    for entry in FIXTURES["awaiting_source"]:
        assert entry["reason"], f"{entry['jurisdiction']} must say why it has no project yet"


@pytest.mark.parametrize("project", PROJECTS, ids=IDS)
def test_each_project_answers_what_is_this_without_generic_filler(project: dict):
    explainer = explainer_for(project)
    lowered = explainer.what_is_this.lower()
    for phrase in GENERIC_PHRASES:
        assert phrase not in lowered, f"{project['key']} degraded to generic copy"
    assert explainer.evidence_backed
    assert len(explainer.what_is_this) > 40


@pytest.mark.parametrize("project", PROJECTS, ids=IDS)
def test_each_project_answers_whats_happening_and_whats_next(project: dict):
    explainer = explainer_for(project)
    assert explainer.whats_happening, f"{project['key']} cannot say what is happening"
    assert explainer.whats_next, f"{project['key']} cannot say what happens next"
    assert explainer.whats_next_basis


@pytest.mark.parametrize("project", PROJECTS, ids=IDS)
def test_each_project_surfaces_useful_scale(project: dict):
    explainer = explainer_for(project)
    surfaced = {fact.field for fact in explainer.why_care}
    declared = set(project["scale_fields"])
    assert surfaced & declared, (
        f"{project['key']} declares scale {sorted(declared)} but surfaces {sorted(surfaced)}"
    )
    # Scale is never an identifier. A parcel number is not a reason anyone cares.
    assert "apn" not in surfaced


@pytest.mark.parametrize("project", PROJECTS, ids=IDS)
def test_each_project_keeps_its_technical_evidence_reachable(project: dict):
    sections = compose_evidence_sections(evidence_for(project))
    placed = {item["field"] for section in sections for item in section["items"]}
    expected = set(project["location_fields"]) | set(project["next_step_fields"])
    assert expected <= placed, f"{project['key']} dropped {sorted(expected - placed)}"
    if "apn" in project["location_fields"]:
        identifiers = next(section for section in sections if section["key"] == "identifiers")
        assert any(item["field"] == "apn" for item in identifiers["items"])


@pytest.mark.parametrize("project", PROJECTS, ids=IDS)
def test_each_project_declares_its_required_evidence_and_status_dimensions(project: dict):
    assert project["required_evidence_families"], f"{project['key']} names no official evidence"
    assert project["status_dimensions"], f"{project['key']} names no status dimension"
    assert project["location_fields"], f"{project['key']} names no way to be located"


def test_scotts_valley_keeps_its_contradictory_dimensions_separate():
    project = next(item for item in PROJECTS if item["key"] == "scotts-valley-casino")
    assert set(project["status_dimensions"]) == {
        "environmental",
        "land_status",
        "gaming_eligibility",
    }
    assert "litigation_about" in project["required_relationship_types"]
    assert "spatial_overlap_only" in project["required_relationship_types"]


def test_fairview_records_that_its_unit_count_changed_during_review():
    project = next(item for item in PROJECTS if item["key"] == "fairview-at-northgate")
    assert "residential_units" in project["scale_fields"]
    assert "meeting_agenda_item" in project["required_evidence_families"]
    assert "current figure" in project["note"]
