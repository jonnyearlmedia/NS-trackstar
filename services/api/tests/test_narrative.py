from __future__ import annotations

from datetime import datetime

from ns_trackstar_api.narrative import (
    compose_evidence_sections,
    compose_explainer,
    field_label,
)


def assertion(field: str, value, url: str | None = None) -> dict:
    return {"field": field, "value": value, "source_url": url}


def test_official_description_leads_the_answer():
    explainer = compose_explainer(
        name="Fairview at Northgate",
        project_type="municipal_development",
        consumer_category="development",
        lifecycle_stage="review",
        assertions=[
            assertion(
                "description",
                "Costco plans to move into a larger new store here alongside new "
                "housing and other commercial development on the former Northgate site.",
            ),
            assertion("residential_units", 245),
        ],
    )
    assert explainer.what_is_this.startswith("Costco plans to move into a larger new store")
    assert "official review" in explainer.what_is_this
    assert "description" in explainer.basis
    assert explainer.evidence_backed


def test_structured_facts_compose_a_sentence_without_a_description():
    explainer = compose_explainer(
        name="Coral Sea Village 8C",
        project_type="municipal_development",
        consumer_category="development",
        lifecycle_stage="approved",
        assertions=[
            assertion("residential_units", 245),
            assertion("address", "Mare Island Way, Vallejo"),
        ],
    )
    assert explainer.what_is_this == (
        "A development project with 245 homes at Mare Island Way, Vallejo. "
        "It has been approved and is waiting to be built."
    )
    assert explainer.evidence_backed


def test_no_generic_napa_solano_filler_is_ever_produced():
    explainer = compose_explainer(
        name="Unnamed record",
        project_type="municipal_development",
        consumer_category="development",
    )
    assert "Napa" not in explainer.what_is_this
    assert explainer.what_is_this == (
        "Unnamed record is a development project tracked in official public records."
    )
    assert not explainer.evidence_backed


def test_latest_meaningful_event_answers_whats_happening():
    explainer = compose_explainer(
        name="Fairview at Northgate",
        project_type="municipal_development",
        assertions=[assertion("description", "A large mixed use project on the old mall site.")],
        events=[
            {
                "event_type": "project_discovered",
                "title": "Tracking Fairview at Northgate",
                "occurred_at": datetime(2026, 1, 4),
            },
            {
                "event_type": "planning_changed",
                "title": "Planning changed to Under review",
                "summary": "The updated housing plan was filed, expanding the project "
                "from 178 to 245 homes.",
                "occurred_at": datetime(2026, 5, 12),
            },
        ],
    )
    assert explainer.whats_happening is not None
    assert "245 homes" in explainer.whats_happening
    assert "(May 2026)" in explainer.whats_happening
    # The discovery event is collector metadata, never project activity.
    assert "Tracking" not in explainer.whats_happening


def test_official_status_is_used_when_there_is_no_event():
    explainer = compose_explainer(
        name="Vista Cove",
        project_type="municipal_development",
        assertions=[
            assertion("official_status_text", "Entitled, pending building permits"),
            assertion("official_status_date", "2026-03-02"),
        ],
    )
    assert explainer.whats_happening == (
        "Official records list this as Entitled, pending building permits, "
        "as of March 2, 2026."
    )


def test_why_care_surfaces_scale_and_impact():
    explainer = compose_explainer(
        name="Solano360",
        project_type="municipal_development",
        consumer_category="development",
        assertions=[
            assertion("residential_units", 245),
            assertion("building_area_sqft", 160000),
            assertion("site_acres", 30.5),
            assertion("estimated_cost", "48000000"),
            assertion("developer", "Example Partners LLC"),
            assertion("apn", "0052-201-010"),
        ],
    )
    values = {fact.field: fact.value for fact in explainer.why_care}
    assert values["residential_units"] == "245 homes"
    assert values["building_area_sqft"] == "160,000 sq ft"
    assert values["site_acres"] == "30.5 acres"
    assert values["estimated_cost"] == "$48 million"
    assert values["developer"] == "Example Partners LLC"
    # Parcel numbers are evidence, not a reason a resident would care.
    assert "apn" not in values


def test_whats_next_prefers_a_scheduled_future_event():
    explainer = compose_explainer(
        name="Downtown Vallejo Specific Plan",
        project_type="municipal_development",
        events=[
            {
                "event_type": "meeting_scheduled",
                "title": "Planning Commission hearing",
                "occurred_at": datetime(2026, 10, 8),
            }
        ],
        now=datetime(2026, 9, 13),
    )
    assert explainer.whats_next == "Planning Commission hearing on October 8, 2026."
    assert explainer.whats_next_basis == "scheduled_event"


def test_whats_next_falls_back_to_dated_evidence_then_stage():
    dated = compose_explainer(
        name="Mare Island Causeway Bridge",
        project_type="transportation_project",
        assertions=[assertion("planned_construction_start", "2027-04-01")],
        now=datetime(2026, 9, 13),
    )
    assert dated.whats_next == "Construction expected to start: April 1, 2027."
    assert dated.whats_next_basis == "planned_construction_start"

    staged = compose_explainer(
        name="Vallejo Waterfront Specific Plan",
        project_type="municipal_development",
        lifecycle_stage="approved",
        now=datetime(2026, 9, 13),
    )
    assert staged.whats_next == "Permitting and pre-construction work."
    assert staged.whats_next_basis == "lifecycle_stage"


def test_a_bare_code_is_not_treated_as_a_description():
    explainer = compose_explainer(
        name="BP26-00001",
        project_type="municipal_development",
        consumer_category="development",
        assertions=[
            assertion("description", "BP26-00001 / RES ALT"),
            assertion("address", "1200 Tennessee St"),
        ],
    )
    assert "RES ALT" not in explainer.what_is_this
    assert explainer.what_is_this == "A development project at 1200 Tennessee St."


def test_evidence_sections_keep_every_assertion_and_flag_bureaucratic_fields():
    sections = compose_evidence_sections(
        [
            assertion("residential_units", 245),
            assertion("apn", "0052-201-010", "https://example.gov/parcel"),
            assertion("planning_case", "PL23-0135"),
            assertion("estimated_cost", 48_000_000),
            assertion("some_unmapped_field", "kept anyway"),
            assertion("description", "prose that already leads the answer"),
        ]
    )
    by_key = {section["key"]: section for section in sections}
    assert by_key["scale"]["items"][0]["field"] == "residential_units"
    assert by_key["money"]["items"][0]["label"] == "Estimated cost"

    identifiers = {item["field"]: item for item in by_key["identifiers"]["items"]}
    assert identifiers["apn"]["bureaucratic"] is True
    assert identifiers["apn"]["source_url"] == "https://example.gov/parcel"
    assert identifiers["planning_case"]["bureaucratic"] is True

    other = {item["field"] for item in by_key["other"]["items"]}
    assert "some_unmapped_field" in other
    # The description already leads "What is this?"; it is not repeated as a fact row.
    assert not any(
        item["field"] == "description"
        for section in sections
        for item in section["items"]
    )


def test_newest_assertion_wins_per_field():
    explainer = compose_explainer(
        name="Fairview at Northgate",
        project_type="municipal_development",
        assertions=[assertion("residential_units", 245), assertion("residential_units", 178)],
    )
    assert explainer.why_care[0].value == "245 homes"


def test_field_label_falls_back_readably():
    assert field_label("residential_units") == "Homes"
    assert field_label("brand_new_field") == "Brand new field"


def sourced(field: str, value, source_key: str) -> dict:
    return {"field": field, "value": value, "source_url": None, "source_key": source_key}


def test_a_rollup_filing_abstract_never_leads_when_local_prose_exists():
    explainer = compose_explainer(
        name="Napa Pipe",
        project_type="municipal_development",
        consumer_category="development",
        assertions=[
            sourced(
                "description",
                "Amendment to the previously certified EIR addressing bridge and "
                "levee improvements associated with the approved development plan.",
                "california.ceqanet.napa-solano",
            ),
            sourced(
                "description",
                "A large mixed use community on the former Napa Pipe factory site, "
                "with homes, shops and public open space along the Napa River.",
                "napa-city.napa-pipe-amendments",
            ),
        ],
    )
    assert explainer.what_is_this.startswith("A large mixed use community")
    assert "Amendment to the previously certified EIR" not in explainer.what_is_this
    assert "description" in explainer.basis


def test_a_rollup_abstract_follows_the_identity_sentence_rather_than_replacing_it():
    explainer = compose_explainer(
        name="Napa Pipe",
        project_type="municipal_development",
        consumer_category="development",
        assertions=[
            sourced(
                "description",
                "Amendment to the previously certified EIR addressing bridge and "
                "levee improvements associated with the approved development plan.",
                "california.ceqanet.napa-solano",
            ),
            sourced("residential_units", 945, "napa-county.napa-pipe-development-plan"),
            sourced("address", "1025 Kaiser Road", "napa-county.napa-pipe-development-plan"),
        ],
    )
    # The reader learns what the project is before what the latest filing says.
    assert explainer.what_is_this.startswith(
        "A development project with 945 homes at 1025 Kaiser Road."
    )
    assert "Amendment to the previously certified EIR" in explainer.what_is_this
    assert "rollup_description" in explainer.basis


def test_a_rollup_abstract_is_still_used_when_it_is_all_there_is():
    explainer = compose_explainer(
        name="SCH 2021010044",
        project_type="environmental_review",
        assertions=[
            sourced(
                "description",
                "Construction of a regional logistics facility including warehouse "
                "buildings, truck courts and associated roadway improvements.",
                "california.ceqanet.napa-solano",
            )
        ],
    )
    assert explainer.what_is_this.startswith("Construction of a regional logistics facility")
    assert "rollup_description" in explainer.basis
