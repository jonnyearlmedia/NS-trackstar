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


from ns_trackstar.business import (  # noqa: E402
    ABC_REPORT_EVIDENCE,
    BusinessEvidenceType,
    BusinessOpeningState,
    business_evidence_from_abc_record,
)


def abc_row(**overrides) -> dict:
    return {
        "report_type": "new_applications",
        "dba_name": "NARDI RESTAURANT",
        "owner_name": "NARDI RESTAURANT LLC",
        "license_number": "681826",
        "city": "VALLEJO",
        "county": "Solano County",
        **overrides,
    }


def test_a_new_abc_application_is_permitted_not_open():
    evidence = business_evidence_from_abc_record(abc_row(), source_key="california.abc")
    assert evidence is not None
    assert evidence.evidence_type is BusinessEvidenceType.ABC_APPLICATION
    assert evidence.opening_state is BusinessOpeningState.PERMITTED
    assert evidence.tenant_name == "NARDI RESTAURANT"
    assert evidence.identity_is_explicit


def test_a_row_without_a_dba_carries_no_brand_claim():
    evidence = business_evidence_from_abc_record(
        abc_row(dba_name=None, owner_name="MOHAMED, BASHAR HASSAN"), source_key="california.abc"
    )
    assert evidence is not None
    assert evidence.tenant_name is None
    assert evidence.identity_is_explicit is False


def test_status_changes_separate_closure_from_transfer_from_activation():
    closed = business_evidence_from_abc_record(
        abc_row(report_type="status_changes", status_changed_from_to="ACTIVE SURREND"),
        source_key="california.abc",
    )
    assert closed.opening_state is BusinessOpeningState.CLOSED

    transferred = business_evidence_from_abc_record(
        abc_row(
            report_type="status_changes",
            status_changed_from_to="ACTIVE ACTIVE",
            transfer_from_to="SMITH INC / JONES LLC",
        ),
        source_key="california.abc",
    )
    assert transferred.opening_state is BusinessOpeningState.OWNERSHIP_CHANGE

    activated = business_evidence_from_abc_record(
        abc_row(report_type="status_changes", status_changed_from_to="PEND ACTIVE"),
        source_key="california.abc",
    )
    assert activated.opening_state is BusinessOpeningState.CONFIRMED_OPEN


def test_an_unreadable_status_change_produces_nothing_rather_than_a_guess():
    assert (
        business_evidence_from_abc_record(
            abc_row(report_type="status_changes", status_changed_from_to=""),
            source_key="california.abc",
        )
        is None
    )
    assert business_evidence_from_abc_record(
        abc_row(report_type="some_other_report"), source_key="california.abc"
    ) is None


def test_a_tenant_improvement_permit_can_never_name_a_business():
    """The explicit product rule: do not infer a brand from a generic permit."""

    from ns_trackstar.business import IDENTITY_EVIDENCE_WEIGHT

    assert BusinessEvidenceType.TENANT_IMPROVEMENT_PERMIT not in IDENTITY_EVIDENCE_WEIGHT
    assert BusinessEvidenceType.PERMIT_NARRATIVE not in IDENTITY_EVIDENCE_WEIGHT
    assert BusinessEvidenceType.CONSTRUCTION_INSPECTION not in IDENTITY_EVIDENCE_WEIGHT


def test_abc_reports_never_claim_a_business_is_open_on_an_application_alone():
    for report_type, (_evidence_type, state) in ABC_REPORT_EVIDENCE.items():
        if report_type == "new_applications":
            assert state is BusinessOpeningState.PERMITTED
        else:
            assert state is not BusinessOpeningState.CONFIRMED_OPEN
