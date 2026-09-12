from ns_trackstar.matching import (
    MatchEvidence,
    conservative_candidate_relationship,
    has_strong_same_project_evidence,
    identity_collapse_allowed,
)
from ns_trackstar.models import RelationshipType


def test_same_name_alone_never_collapses_identity() -> None:
    evidence = MatchEvidence(normalized_name_match=True)
    assert has_strong_same_project_evidence(evidence) is False
    assert conservative_candidate_relationship(evidence) is None
    assert identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, evidence) is False


def test_shared_parcel_is_spatial_relationship_not_identity() -> None:
    evidence = MatchEvidence(shared_apns=frozenset({"0173-390-200"}))
    assert has_strong_same_project_evidence(evidence) is False
    assert conservative_candidate_relationship(evidence) is RelationshipType.SPATIAL_OVERLAP_ONLY


def test_authoritative_physical_identifier_can_prove_identity() -> None:
    evidence = MatchEvidence(authoritative_identifiers={"permit_number": "BP-123"})

    assert has_strong_same_project_evidence(evidence) is True
    assert conservative_candidate_relationship(evidence) is RelationshipType.SAME_PHYSICAL_PROJECT
    assert identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, evidence) is True


def test_environmental_review_number_does_not_prove_physical_identity() -> None:
    evidence = MatchEvidence(authoritative_identifiers={"sch_number": "2024070295"})
    assert has_strong_same_project_evidence(evidence) is False
    assert conservative_candidate_relationship(evidence) is None


def test_explicit_official_cross_reference_can_prove_identity() -> None:
    evidence = MatchEvidence(explicit_same_project_references=("official-record-link",))
    assert has_strong_same_project_evidence(evidence) is True
    assert identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, evidence) is True


def test_non_identity_relationship_never_collapses_even_with_strong_evidence() -> None:
    evidence = MatchEvidence(authoritative_identifiers={"planning_case": "PLN-42"})
    assert identity_collapse_allowed(RelationshipType.PARENT_CHILD, evidence) is False
