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
    ABC_LICENSE_ISSUED = "abc_license_issued"
    ABC_STATUS_CHANGE = "abc_status_change"
    ENVIRONMENTAL_HEALTH = "environmental_health"
    CONSTRUCTION_INSPECTION = "construction_inspection"
    CERTIFICATE_OF_OCCUPANCY = "certificate_of_occupancy"
    FIRST_PARTY_ANNOUNCEMENT = "first_party_announcement"
    PROPERTY_OWNER_ANNOUNCEMENT = "property_owner_announcement"
    # A tenant improvement permit proves work is happening inside a suite. It says
    # nothing about who is moving in, so it deliberately carries no identity weight.
    TENANT_IMPROVEMENT_PERMIT = "tenant_improvement_permit"
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
    BusinessEvidenceType.ABC_LICENSE_ISSUED: 0.86,
    BusinessEvidenceType.ENVIRONMENTAL_HEALTH: 0.75,
    BusinessEvidenceType.FIRST_PARTY_ANNOUNCEMENT: 0.82,
    BusinessEvidenceType.PROPERTY_OWNER_ANNOUNCEMENT: 0.7,
}

ALLOWED_OPENING_STATES: dict[BusinessEvidenceType, frozenset[BusinessOpeningState]] = {
    BusinessEvidenceType.OFFICIAL_PROJECT_TRACKER: frozenset(BusinessOpeningState),
    BusinessEvidenceType.PLANNING_APPROVAL: frozenset({BusinessOpeningState.ENTITLED}),
    BusinessEvidenceType.BUILDING_PERMIT_ISSUED: frozenset({BusinessOpeningState.PERMITTED}),
    BusinessEvidenceType.CONSTRUCTION_INSPECTION: frozenset(
        {BusinessOpeningState.UNDER_CONSTRUCTION}
    ),
    BusinessEvidenceType.TENANT_IMPROVEMENT_PERMIT: frozenset(
        {BusinessOpeningState.PERMITTED, BusinessOpeningState.UNDER_CONSTRUCTION}
    ),
    BusinessEvidenceType.ABC_APPLICATION: frozenset({BusinessOpeningState.PERMITTED}),
    BusinessEvidenceType.ABC_LICENSE_ISSUED: frozenset(
        {BusinessOpeningState.OCCUPANCY_READY, BusinessOpeningState.CONFIRMED_OPEN}
    ),
    BusinessEvidenceType.ABC_STATUS_CHANGE: frozenset(
        {
            BusinessOpeningState.CONFIRMED_OPEN,
            BusinessOpeningState.OWNERSHIP_CHANGE,
            BusinessOpeningState.CLOSED,
        }
    ),
    BusinessEvidenceType.PROPERTY_OWNER_ANNOUNCEMENT: frozenset(
        {BusinessOpeningState.OPENING_ANNOUNCED}
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


# California ABC report row -> business evidence. The mapping is deliberately narrow:
# a row only carries a tenant identity when ABC itself printed a "DBA:" trade name, and
# the opening state it supports is bounded by which of the three reports it came from.
ABC_REPORT_EVIDENCE: dict[str, tuple[BusinessEvidenceType, BusinessOpeningState]] = {
    "new_applications": (BusinessEvidenceType.ABC_APPLICATION, BusinessOpeningState.PERMITTED),
    "issued_licenses": (
        BusinessEvidenceType.ABC_LICENSE_ISSUED,
        BusinessOpeningState.OCCUPANCY_READY,
    ),
}

# ABC truncates its status codes in the published report ("SURREND", "AUTREV"), so the
# markers are stems rather than whole words.
_ABC_SURRENDER_MARKERS = ("surrend", "revok", "autrev", "cancel", "expir")
_ABC_TRANSFER_MARKERS = ("transfer", "escrow")


def _abc_status_change_state(row: dict[str, object]) -> BusinessOpeningState:
    change = str(row.get("status_changed_from_to") or "").casefold()
    transfer = str(row.get("transfer_from_to") or "").casefold()
    if any(marker in change for marker in _ABC_SURRENDER_MARKERS):
        return BusinessOpeningState.CLOSED
    if transfer or any(marker in change for marker in _ABC_TRANSFER_MARKERS):
        return BusinessOpeningState.OWNERSHIP_CHANGE
    if "active" in change:
        return BusinessOpeningState.CONFIRMED_OPEN
    return BusinessOpeningState.UNKNOWN


def business_evidence_from_abc_record(
    row: dict[str, object],
    *,
    source_key: str,
    observed_at: datetime | None = None,
) -> BusinessEvidence | None:
    """Turn one normalized ABC report row into business-opening evidence.

    Returns ``None`` for a row whose state the report cannot support, rather than
    guessing. A licence holder's own name is never treated as a storefront brand:
    identity is only explicit when ABC printed a DBA.
    """

    report_type = str(row.get("report_type") or "")
    dba = row.get("dba_name")
    tenant_name = str(dba) if isinstance(dba, str) and dba.strip() else None

    if report_type == "status_changes":
        state = _abc_status_change_state(row)
        if state is BusinessOpeningState.UNKNOWN:
            return None
        evidence_type = BusinessEvidenceType.ABC_STATUS_CHANGE
    else:
        mapped = ABC_REPORT_EVIDENCE.get(report_type)
        if mapped is None:
            return None
        evidence_type, state = mapped

    return BusinessEvidence(
        source_key=source_key,
        source_family="abc_ca",
        evidence_type=evidence_type,
        tenant_name=tenant_name,
        identity_is_explicit=tenant_name is not None,
        opening_state=state,
        observed_at=observed_at,
        confidence=0.9,
        details={
            "license_number": row.get("license_number"),
            "report_type": report_type,
            "county": row.get("county"),
            "city": row.get("city"),
        },
    )
