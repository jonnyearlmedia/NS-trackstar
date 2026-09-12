from __future__ import annotations

from datetime import UTC, datetime

from ns_trackstar.business import (
    BusinessEvidence,
    BusinessEvidenceType,
    BusinessOpeningState,
    TenantIdentityState,
    assess_business_opening,
)


def test_generic_permit_narrative_cannot_manufacture_a_brand() -> None:
    assessment = assess_business_opening(
        [
            BusinessEvidence(
                source_key="suisun.building",
                source_family="permit_portal",
                evidence_type=BusinessEvidenceType.PERMIT_NARRATIVE,
                tenant_name="Dutch Bros",
                identity_is_explicit=True,
                details={"narrative": "Restaurant tenant improvement"},
            )
        ]
    )

    assert assessment.tenant_name is None
    assert assessment.tenant_identity_state is TenantIdentityState.UNKNOWN
    assert assessment.tenant_identity_confidence == 0


def test_repeated_records_from_one_system_do_not_fake_source_diversity() -> None:
    evidence = [
        BusinessEvidence(
            source_key=f"suisun.sign-permit.{record_number}",
            source_family="permit_portal",
            evidence_type=BusinessEvidenceType.SIGN_PERMIT,
            tenant_name="Dutch Bros",
            identity_is_explicit=True,
        )
        for record_number in range(3)
    ]

    assessment = assess_business_opening(evidence)

    assert assessment.tenant_identity_state is TenantIdentityState.LIKELY_NEW_BUSINESS
    assert assessment.tenant_identity_confidence == 0.69
    assert assessment.identity_source_families == ["permit_portal"]


def test_one_official_dutch_bros_source_is_a_likely_lead_not_confirmation() -> None:
    assessment = assess_business_opening(
        [
            BusinessEvidence(
                source_key="suisun-city.development-calendar",
                source_family="official_curated_tracker",
                evidence_type=BusinessEvidenceType.OFFICIAL_PROJECT_TRACKER,
                tenant_name="Dutch Bros",
                identity_is_explicit=True,
                confidence=1,
            )
        ]
    )

    assert assessment.tenant_name == "Dutch Bros"
    assert assessment.tenant_identity_state is TenantIdentityState.LIKELY_NEW_BUSINESS
    assert assessment.tenant_identity_confidence == 0.69
    assert assessment.opening_state is BusinessOpeningState.UNKNOWN
    assert assessment.opening_state_confidence == 0


def test_independent_sources_can_confirm_dutch_bros_tenant_identity() -> None:
    assessment = assess_business_opening(
        [
            BusinessEvidence(
                source_key="suisun-city.development-calendar",
                source_family="official_curated_tracker",
                evidence_type=BusinessEvidenceType.OFFICIAL_PROJECT_TRACKER,
                tenant_name="Dutch Bros",
                identity_is_explicit=True,
                confidence=1,
            ),
            BusinessEvidence(
                source_key="suisun.sign-permits",
                source_family="permit_portal",
                evidence_type=BusinessEvidenceType.SIGN_PERMIT,
                tenant_name="Dutch Bros",
                identity_is_explicit=True,
                confidence=1,
            ),
        ]
    )

    assert assessment.tenant_identity_state is TenantIdentityState.CONFIRMED_TENANT
    assert assessment.tenant_identity_confidence > 0.9
    assert assessment.identity_source_families == ["official_curated_tracker", "permit_portal"]


def test_building_permit_advances_opening_state_without_claiming_business_is_open() -> None:
    assessment = assess_business_opening(
        [
            BusinessEvidence(
                source_key="suisun.building",
                source_family="permit_portal",
                evidence_type=BusinessEvidenceType.BUILDING_PERMIT_ISSUED,
                opening_state=BusinessOpeningState.PERMITTED,
                confidence=0.98,
            )
        ]
    )

    assert assessment.opening_state is BusinessOpeningState.PERMITTED
    assert assessment.opening_state_confidence == 0.98
    assert assessment.tenant_identity_state is TenantIdentityState.UNKNOWN


def test_unsupported_opening_inference_is_discarded() -> None:
    assessment = assess_business_opening(
        [
            BusinessEvidence(
                source_key="suisun.building",
                source_family="permit_portal",
                evidence_type=BusinessEvidenceType.BUILDING_PERMIT_ISSUED,
                opening_state=BusinessOpeningState.CONFIRMED_OPEN,
                confidence=1,
            )
        ]
    )

    assert assessment.opening_state is BusinessOpeningState.UNKNOWN
    assert assessment.opening_state_confidence == 0


def test_latest_supported_opening_evidence_controls_current_state() -> None:
    assessment = assess_business_opening(
        [
            BusinessEvidence(
                source_key="inspection",
                source_family="permit_portal",
                evidence_type=BusinessEvidenceType.CONSTRUCTION_INSPECTION,
                opening_state=BusinessOpeningState.UNDER_CONSTRUCTION,
                observed_at=datetime(2026, 7, 1, tzinfo=UTC),
                confidence=0.95,
            ),
            BusinessEvidence(
                source_key="operations",
                source_family="official_operations",
                evidence_type=BusinessEvidenceType.OFFICIAL_OPERATIONS_RECORD,
                opening_state=BusinessOpeningState.CONFIRMED_OPEN,
                observed_at=datetime(2026, 9, 1, tzinfo=UTC),
                confidence=1,
            ),
        ]
    )

    assert assessment.opening_state is BusinessOpeningState.CONFIRMED_OPEN
    assert assessment.opening_state_confidence == 0.99


def test_every_business_state_from_the_product_contract_is_represented() -> None:
    assert {state.value for state in TenantIdentityState} >= {
        "possible_new_business",
        "likely_new_business",
        "confirmed_tenant",
    }
    assert {state.value for state in BusinessOpeningState} >= {
        "entitled",
        "permitted",
        "under_construction",
        "opening_announced",
        "occupancy_ready",
        "apparently_open",
        "confirmed_open",
        "ownership_change",
        "closed",
    }
