from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ns_trackstar.models import RelationshipType

# These identifiers can name a specific physical project in an issuing system. They are useful
# evidence, but permit/case numbers can repeat across jurisdictions, so they are not by themselves
# enough to collapse two canonical projects.
PHYSICAL_PROJECT_IDENTIFIER_TYPES = frozenset(
    {
        "caltrans_ea",
        "local_project_id",
        "permit_number",
        "planning_case",
        "subdivision_map",
    }
)


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    shared_apns: frozenset[str] = field(default_factory=frozenset)
    authoritative_identifiers: Mapping[str, str] = field(default_factory=dict)
    explicit_same_project_references: tuple[str, ...] = ()
    geometry_overlap: bool = False
    normalized_address_match: bool = False
    normalized_name_match: bool = False


def has_project_identifier(evidence: MatchEvidence) -> bool:
    return any(
        identifier_type in PHYSICAL_PROJECT_IDENTIFIER_TYPES and bool(value.strip())
        for identifier_type, value in evidence.authoritative_identifiers.items()
    )


def has_strong_same_project_evidence(evidence: MatchEvidence) -> bool:
    """Require an explicit cross-reference or an identifier plus a corroborating signal.

    A shared parcel, name, address or overlapping geometry is useful corroboration, but none of
    those signals alone proves identity. This intentionally biases Trackstar toward keeping two
    records separate rather than making a bad merge that would misstate the real world.
    """

    if evidence.explicit_same_project_references:
        return True
    return has_project_identifier(evidence) and (
        evidence.normalized_address_match
        or evidence.normalized_name_match
        or evidence.geometry_overlap
        or bool(evidence.shared_apns)
    )


def identity_collapse_allowed(
    relationship_type: RelationshipType,
    evidence: MatchEvidence,
) -> bool:
    """Allow identity collapse only for an evidenced same-physical-project relationship."""

    return (
        relationship_type is RelationshipType.SAME_PHYSICAL_PROJECT
        and has_strong_same_project_evidence(evidence)
    )


def conservative_candidate_relationship(
    evidence: MatchEvidence,
) -> RelationshipType | None:
    """Return the strongest safe automatic candidate without inventing identity certainty."""

    if has_strong_same_project_evidence(evidence):
        return RelationshipType.SAME_PHYSICAL_PROJECT
    if evidence.shared_apns or evidence.geometry_overlap:
        return RelationshipType.SPATIAL_OVERLAP_ONLY
    return None
