from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from math import prod

from pydantic import BaseModel, Field


class TenantIdentityState(StrEnum):
    UNKNOWN = "unknown"
    POSSIBLE_NEW_BUSINESS = "possible_new_business"
    LIKELY_NEW_BUSINESS = "likely_new_business"
    CONFIRMED_TENANT = "confirmed_tenant"


class BusinessOpeningState(StrEnum):
    UNKNOWN = "unknown"
    ENTITLED = "entitled"
    PERMITTED = "permitted"
    UNDER_CONSTRUCTION = "under_construction"
    OPENING_ANNOUNCED = "opening_announced"
    OCCUPANCY_READY = "occupancy_ready"
    APPARENTLY_OPEN = "apparently_open"
    CONFIRMED_OPEN = "confirmed_open"
    OWNERSHIP_CHANGE = "ownership_change"
    CLOSED = "closed"


class BusinessEvidenceType(StrEnum):
    OFFICIAL_PROJECT_TRACKER = "official_project_tracker"
    PLANNING_APPROVAL = "planning_approval"
    PERMIT_NARRATIVE = "permit_narrative"
    BUILDING_PERMIT_ISSUED = "building_permit_issued"
    SIGN_PERMIT = "sign_permit"
    BUSINESS_LICENSE = "business_license"
    ABC_APPLICATION = "abc_application"
    ENVIRONMENTAL_HEALTH = "environmental_health"
    CONSTRUCTION_INSPECTION = "construction_inspection"
    CERTIFICATE_OF_OCCUPANCY = "certificate_of_occupancy"
    FIRST_PARTY_ANNOUNCEMENT = "first_party_announcement"
    PUBLIC_OBSERVATION = "public_observation"
    OFFICIAL_OPERATIONS_RECORD = "official_operations_record"
    OWNERSHIP_FILING = "ownership_filing"
    OFFICIAL_CLOSURE_RECORD = "official_closure_record"


class BusinessEvidence(BaseModel):
    source_key: str
    source_family: str
    evidence_type: BusinessEvidenceType
    tenant_name: str | None = None
    identity_is_explicit: bool = False
    opening_state: BusinessOpeningState | None = None
    observed_at: datetime | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    direct: bool = True
    details: dict[str, object] = Field(default_factory=dict)


class BusinessAssessment(BaseModel):
    tenant_name: str | None
    tenant_identity_state: TenantIdentityState
    tenant_identity_confidence: float = Field(ge=0, le=1)
    identity_source_families: list[str] = Field(default_factory=list)
    opening_state: BusinessOpeningState
    opening_state_confidence: float = Field(ge=0, le=1)
    opening_source_keys: list[str] = Field(default_factory=list)


IDENTITY_EVIDENCE_WEIGHT: dict[BusinessEvidenceType, float] = {
    BusinessEvidenceType.OFFICIAL_PROJECT_TRACKER: 0.72,
    BusinessEvidenceType.PLANNING_APPROVAL: 0.45,
    BusinessEvidenceType.BUILDING_PERMIT_ISSUED: 0.5,
    BusinessEvidenceType.SIGN_PERMIT: 0.8,
    BusinessEvidenceType.BUSINESS_LICENSE: 0.85,
    BusinessEvidenceType.ABC_APPLICATION: 0.78,
    BusinessEvidenceType.ENVIRONMENTAL_HEALTH: 0.75,
    BusinessEvidenceType.FIRST_PARTY_ANNOUNCEMENT: 0.82,
}

ALLOWED_OPENING_STATES: dict[BusinessEvidenceType, frozenset[BusinessOpeningState]] = {
    BusinessEvidenceType.OFFICIAL_PROJECT_TRACKER: frozenset(BusinessOpeningState),
    BusinessEvidenceType.PLANNING_APPROVAL: frozenset({BusinessOpeningState.ENTITLED}),
    BusinessEvidenceType.BUILDING_PERMIT_ISSUED: frozenset({BusinessOpeningState.PERMITTED}),
    BusinessEvidenceType.CONSTRUCTION_INSPECTION: frozenset(
        {BusinessOpeningState.UNDER_CONSTRUCTION}
    ),
    BusinessEvidenceType.FIRST_PARTY_ANNOUNCEMENT: frozenset(
        {BusinessOpeningState.OPENING_ANNOUNCED}
    ),
    BusinessEvidenceType.CERTIFICATE_OF_OCCUPANCY: frozenset(
        {BusinessOpeningState.OCCUPANCY_READY}
    ),
    BusinessEvidenceType.PUBLIC_OBSERVATION: frozenset({BusinessOpeningState.APPARENTLY_OPEN}),
    BusinessEvidenceType.OFFICIAL_OPERATIONS_RECORD: frozenset(
        {BusinessOpeningState.CONFIRMED_OPEN}
    ),
    BusinessEvidenceType.OWNERSHIP_FILING: frozenset({BusinessOpeningState.OWNERSHIP_CHANGE}),
    BusinessEvidenceType.OFFICIAL_CLOSURE_RECORD: frozenset({BusinessOpeningState.CLOSED}),
}

OPENING_STATE_ORDER = {
    BusinessOpeningState.UNKNOWN: 0,
    BusinessOpeningState.ENTITLED: 1,
    BusinessOpeningState.PERMITTED: 2,
    BusinessOpeningState.UNDER_CONSTRUCTION: 3,
    BusinessOpeningState.OPENING_ANNOUNCED: 4,
    BusinessOpeningState.OCCUPANCY_READY: 5,
    BusinessOpeningState.APPARENTLY_OPEN: 6,
    BusinessOpeningState.CONFIRMED_OPEN: 7,
    BusinessOpeningState.OWNERSHIP_CHANGE: 8,
    BusinessOpeningState.CLOSED: 9,
}


def _identity_key(name: str) -> str:
    return " ".join(name.casefold().split())


def _identity_assessment(
    evidence: list[BusinessEvidence],
) -> tuple[str | None, TenantIdentityState, float, list[str]]:
    candidates: dict[str, list[BusinessEvidence]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for item in evidence:
        if not item.tenant_name or not item.identity_is_explicit:
            continue
        if item.evidence_type not in IDENTITY_EVIDENCE_WEIGHT:
            continue
        key = _identity_key(item.tenant_name)
        candidates[key].append(item)
        display_names.setdefault(key, " ".join(item.tenant_name.split()))

    if not candidates:
        return None, TenantIdentityState.UNKNOWN, 0, []

    def candidate_score(items: list[BusinessEvidence]) -> float:
        strongest_by_family: dict[str, float] = {}
        for item in items:
            strength = item.confidence * IDENTITY_EVIDENCE_WEIGHT[item.evidence_type]
            if not item.direct:
                strength *= 0.5
            strongest_by_family[item.source_family] = max(
                strongest_by_family.get(item.source_family, 0), strength
            )
        strengths = strongest_by_family.values()
        return 1 - prod(1 - strength for strength in strengths)

    winner, winner_evidence = max(
        candidates.items(), key=lambda candidate: candidate_score(candidate[1])
    )
    source_families = sorted({item.source_family for item in winner_evidence})
    direct_source_families = {item.source_family for item in winner_evidence if item.direct}
    score = candidate_score(winner_evidence)

    if len(direct_source_families) >= 2 and score >= 0.8:
        state = TenantIdentityState.CONFIRMED_TENANT
    elif score >= 0.6:
        state = TenantIdentityState.LIKELY_NEW_BUSINESS
    else:
        state = TenantIdentityState.POSSIBLE_NEW_BUSINESS

    # One system can support a lead, but never a strong brand claim by itself.
    if len(source_families) < 2:
        score = min(score, 0.69)
        if state is TenantIdentityState.CONFIRMED_TENANT:
            state = TenantIdentityState.LIKELY_NEW_BUSINESS

    return display_names[winner], state, round(score, 4), source_families


def _opening_assessment(
    evidence: list[BusinessEvidence],
) -> tuple[BusinessOpeningState, float, list[str]]:
    supported = [
        item
        for item in evidence
        if item.opening_state is not None
        and item.opening_state in ALLOWED_OPENING_STATES.get(item.evidence_type, frozenset())
    ]
    if not supported:
        return BusinessOpeningState.UNKNOWN, 0, []

    dated = [item for item in supported if item.observed_at is not None]
    if dated:
        latest_at = max(item.observed_at for item in dated)
        candidates = [item for item in dated if item.observed_at == latest_at]
    else:
        candidates = supported

    selected = max(
        candidates,
        key=lambda item: (OPENING_STATE_ORDER[item.opening_state], item.confidence),
    )
    selected_state = selected.opening_state or BusinessOpeningState.UNKNOWN
    corroborating = [item for item in supported if item.opening_state is selected_state]
    source_keys = sorted({item.source_key for item in corroborating})
    confidence = 1 - prod(1 - item.confidence for item in corroborating)
    return selected_state, round(min(confidence, 0.99), 4), source_keys


def assess_business_opening(evidence: Iterable[BusinessEvidence]) -> BusinessAssessment:
    items = list(evidence)
    tenant_name, identity_state, identity_confidence, identity_sources = _identity_assessment(items)
    opening_state, opening_confidence, opening_sources = _opening_assessment(items)
    return BusinessAssessment(
        tenant_name=tenant_name,
        tenant_identity_state=identity_state,
        tenant_identity_confidence=identity_confidence,
        identity_source_families=identity_sources,
        opening_state=opening_state,
        opening_state_confidence=opening_confidence,
        opening_source_keys=opening_sources,
    )
