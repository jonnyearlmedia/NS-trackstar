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


def test_identifier_needs_corroboration_before_identity_collapse() -> None:
    identifier_only = MatchEvidence(authoritative_identifiers={"permit_number": "BP-123"})
    corroborated = MatchEvidence(
        authoritative_identifiers={"permit_number": "BP-123"},
        normalized_address_match=True,
    )

    assert has_strong_same_project_evidence(identifier_only) is False
    assert conservative_candidate_relationship(identifier_only) is None
    assert has_strong_same_project_evidence(corroborated) is True
    assert conservative_candidate_relationship(corroborated) is RelationshipType.SAME_PHYSICAL_PROJECT
    assert identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, corroborated) is True


def test_explicit_official_cross_reference_can_prove_identity() -> None:
    evidence = MatchEvidence(explicit_same_project_references=("official-record-link",))
    assert has_strong_same_project_evidence(evidence) is True
    assert identity_collapse_allowed(RelationshipType.SAME_PHYSICAL_PROJECT, evidence) is True


def test_non_identity_relationship_never_collapses_even_with_strong_evidence() -> None:
    evidence = MatchEvidence(
        authoritative_identifiers={"planning_case": "PLN-42"},
        normalized_name_match=True,
    )
    assert identity_collapse_allowed(RelationshipType.PARENT_CHILD, evidence) is False
