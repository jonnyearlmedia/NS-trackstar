from ns_trackstar_api.area import _bbox_params, normalize_lifecycle


def test_lifecycle_prefers_construction_over_approved() -> None:
    stage, dimension, value = normalize_lifecycle(
        {
            "planning": "Approved",
            "delivery_stage": "Active Construction",
        }
    )
    assert stage == "construction"
    assert dimension == "delivery_stage"
    assert value == "Active Construction"


def test_lifecycle_marks_explicit_review_without_guessing() -> None:
    stage, dimension, value = normalize_lifecycle({"planning": "Under Review"})
    assert stage == "review"
    assert dimension == "planning"
    assert value == "Under Review"


def test_lifecycle_marks_explicit_approval() -> None:
    stage, dimension, value = normalize_lifecycle({"official_tracker_stage": "Approved"})
    assert stage == "approved"
    assert dimension == "official_tracker_stage"
    assert value == "Approved"


def test_lifecycle_keeps_ambiguous_status_unknown() -> None:
    stage, dimension, value = normalize_lifecycle({"planning": "Phase 2", "delivery_stage": "Design"})
    assert stage == "unknown"
    assert dimension is None
    assert value is None


def test_lifecycle_keeps_combined_entitled_or_construction_unknown() -> None:
    stage, dimension, value = normalize_lifecycle(
        {"official_tracker_stage": "entitled_or_under_construction"}
    )
    assert stage == "unknown"
    assert dimension is None
    assert value is None


def test_lifecycle_does_not_misclassify_preconstruction() -> None:
    stage, _, _ = normalize_lifecycle({"delivery_stage": "Pre-Construction"})
    assert stage == "unknown"


def test_lifecycle_does_not_match_words_inside_other_words() -> None:
    assert normalize_lifecycle({"delivery_stage": "Incomplete"})[0] == "unknown"
    assert normalize_lifecycle({"planning": "Disapproved"})[0] == "inactive"


def test_lifecycle_does_not_promote_negated_status() -> None:
    assert normalize_lifecycle({"delivery_stage": "Not under construction"})[0] == "unknown"
    assert normalize_lifecycle({"planning": "Not yet approved"})[0] == "unknown"


def test_lifecycle_marks_terminal_statuses() -> None:
    assert normalize_lifecycle({"delivery_stage": "Completed"})[0] == "completed"
    assert normalize_lifecycle({"planning": "Withdrawn"})[0] == "inactive"


def test_invalid_bbox_fails_closed() -> None:
    assert _bbox_params(-121.0, 38.0, -122.0, 39.0) == {
        "west": 0.0,
        "south": 0.0,
        "east": 0.0,
        "north": 0.0,
    }
