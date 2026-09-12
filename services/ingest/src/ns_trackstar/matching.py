from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ns_trackstar.models import RelationshipType

# These identifiers name a specific physical project in the issuing system. Parcel and
# environmental-review identifiers are intentionally excluded: either can span multiple projects.
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


def has_strong_same_project_evidence(evidence: MatchEvidence) -> bool:
    if evidence.explicit_same_project_references:
        return True
    return any(
        identifier_type in PHYSICAL_PROJECT_IDENTIFIER_TYPES and bool(value.strip())
        for identifier_type, value in evidence.authoritative_identifiers.items()
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
