from ns_trackstar_api.area import normalize_lifecycle


def test_consumer_lifecycle_contract_covers_explicit_public_stages() -> None:
    cases = {
        "Proposed": "proposed",
        "Under Review": "review",
        "Application Submitted": "review",
        "Approved": "approved",
        "Permit Issued": "approved",
        "Under Construction": "construction",
        "Completed": "completed",
        "Canceled": "inactive",
        "Cancelled": "inactive",
        "Stalled": "inactive",
        "Withdrawn": "inactive",
    }
    for official_value, expected in cases.items():
        assert normalize_lifecycle({"official_tracker_stage": official_value})[0] == expected


def test_consumer_lifecycle_contract_keeps_ambiguous_language_unknown() -> None:
    for official_value in (
        "Planned",
        "In Progress",
        "Pending",
        "Archived",
        "Design",
        "Pre-Construction",
        "Entitled or Under Construction",
    ):
        assert normalize_lifecycle({"official_tracker_stage": official_value})[0] == "unknown"
