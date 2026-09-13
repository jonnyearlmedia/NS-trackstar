from __future__ import annotations

import json
from pathlib import Path

import pytest

from ns_trackstar.matching import (
    MatchEvidence,
    conservative_candidate_relationship,
    identity_collapse_allowed,
)
from ns_trackstar.models import RelationshipType

FIXTURE_DIRECTORY = Path(__file__).parents[3] / "fixtures" / "regression"


def _fixtures() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text()) for path in sorted(FIXTURE_DIRECTORY.glob("*.json"))
    }


def _match_evidence(value: dict) -> MatchEvidence:
    return MatchEvidence(
        shared_apns=frozenset(value.get("shared_apns", [])),
        authoritative_identifiers=value.get("authoritative_identifiers", {}),
        explicit_same_project_references=tuple(value.get("explicit_same_project_references", [])),
        geometry_overlap=value.get("geometry_overlap", False),
        normalized_address_match=value.get("normalized_address_match", False),
        normalized_name_match=value.get("normalized_name_match", False),
    )


def test_all_required_real_project_fixtures_are_executable() -> None:
    fixtures = _fixtures()
    assert set(fixtures) == {
        "dutch-bros-suisun",
        "napa-pipe",
        "one-lake-canon-station",
        "scotts-valley-vallejo-casino",
        "sr37-sears-point-mare-island",
    }

    for fixture in fixtures.values():
        entity_keys = {entity["key"] for entity in fixture["entities"]}
        assert len(entity_keys) == len(fixture["entities"])
        assert fixture["sources"]
        for relationship in fixture["relationships"]:
            assert relationship["from"] in entity_keys
            assert relationship["to"] in entity_keys
            relationship_type = RelationshipType(relationship["type"])
            assert relationship_type in RelationshipType
            if relationship["collapse_identities"]:
                pytest.fail("Typed fixture relationships must precede any identity collapse")


@pytest.mark.parametrize("fixture", _fixtures().values(), ids=_fixtures().keys())
def test_match_cases_obey_conservative_identity_rules(fixture: dict) -> None:
    for case in fixture["match_cases"]:
        evidence = _match_evidence(case["evidence"])
        relationship = conservative_candidate_relationship(evidence)
        assert relationship is RelationshipType(case["expected_relationship"])
        assert (
            identity_collapse_allowed(relationship, evidence) is case["expected_identity_collapse"]
        )


def test_apn_only_never_collapses_scotts_valley_or_napa_pipe_entities() -> None:
    fixtures = _fixtures()
    for fixture_key in ("scotts-valley-vallejo-casino", "napa-pipe"):
        case = fixtures[fixture_key]["match_cases"][0]
        evidence = _match_evidence(case["evidence"])
        assert evidence.shared_apns
        assert (
            conservative_candidate_relationship(evidence) is RelationshipType.SPATIAL_OVERLAP_ONLY
        )
        assert not identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, evidence)


def test_same_physical_project_collapse_requires_authoritative_physical_identifier() -> None:
    strong = MatchEvidence(authoritative_identifiers={"planning_case": "PL-2026-0042"})
    environmental_only = MatchEvidence(authoritative_identifiers={"sch_number": "2024070295"})

    assert conservative_candidate_relationship(strong) is RelationshipType.SAME_PHYSICAL_PROJECT
    assert identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, strong)
    assert conservative_candidate_relationship(environmental_only) is None
    assert not identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, environmental_only)


def test_napa_pipe_phases_remain_children_of_the_master_project() -> None:
    fixture = _fixtures()["napa-pipe"]
    relationships = {
        (relationship["from"], relationship["to"], relationship["type"])
        for relationship in fixture["relationships"]
    }
    assert ("master-development", "phase-1", "parent_child") in relationships
    assert ("master-development", "phase-2", "parent_child") in relationships


def test_one_lake_alias_does_not_turn_the_developer_into_a_project() -> None:
    fixture = _fixtures()["one-lake-canon-station"]
    master = next(entity for entity in fixture["entities"] if entity["key"] == "master-development")
    assert "Canon Station" in master["aliases"]
    assert fixture["organizations"][0] == {
        "key": "canon-station-llc",
        "name": "Canon Station, LLC",
        "role": "developer",
        "is_project": False,
    }
    assert any(
        relationship["type"] == "related_infrastructure"
        for relationship in fixture["relationships"]
    )


def test_sr37_keeps_linear_geometry_identifiers_and_package_boundary() -> None:
    fixture = _fixtures()["sr37-sears-point-mare-island"]
    corridor = next(entity for entity in fixture["entities"] if entity["key"] == "corridor-project")
    assert corridor["geometry"]["type"] == "LineString"
    assert corridor["geometry"]["location_accuracy"] == "street_segment"
    assert corridor["identifiers"]["caltrans_ea"] == "04-1Q7600"
    assert corridor["identifiers"]["sch_number"] == "2020070226"
    assert corridor["status_dimensions"]["funding"] == "partially_funded"
    assert corridor["status_dimensions"]["construction"] == "not_implied_by_funding"
    assert fixture["relationships"][0]["type"] == "parent_child"
    assert fixture["required_event_types"] == [
        "funding_authorized",
        "construction_started",
        "road_closure_started",
        "road_closure_ended",
    ]


def test_scotts_valley_preserves_independent_contradictory_statuses() -> None:
    fixture = _fixtures()["scotts-valley-vallejo-casino"]
    project = next(
        entity for entity in fixture["entities"] if entity["key"] == "casino-and-tribal-housing"
    )
    assert project["status_dimensions"] == {
        "environmental": "fonsi_issued",
        "land_status": "in_trust",
        "gaming_eligibility": "reconsidered",
        "litigation": "tracked_separately",
    }
    assert {relationship["type"] for relationship in fixture["relationships"]} >= {
        "environmental_review_for",
        "litigation_about",
        "spatial_overlap_only",
    }
    assert set(fixture["required_evidence_types"]) == {
        "ceqa_document",
        "bia_action",
        "nigc_action",
        "federal_litigation",
        "interested_party_statement",
    }


def test_dutch_bros_separates_tenant_identity_from_opening_certainty() -> None:
    fixture = _fixtures()["dutch-bros-suisun"]
    business = fixture["entities"][0]
    assert business["status_dimensions"]["business_identity"] == "likely_new_business"
    assert business["status_dimensions"]["operations"] == "not_confirmed"
    assert business["facts"]["opening_date"] is None
    assert (
        business["confidence_dimensions"]["tenant_identity"]
        > business["confidence_dimensions"]["opening_state"]
    )
    assert fixture["required_event_types"][-2:] == ["construction_started", "business_opened"]
