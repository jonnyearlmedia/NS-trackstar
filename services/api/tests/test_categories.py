from ns_trackstar_api.categories import normalize_consumer_category


def test_transportation_project_is_roads() -> None:
    category, basis, evidence = normalize_consumer_category(
        project_type="transportation_project",
        semantic_values=[],
        project_name="Generic capital project",
    )
    assert category == "roads"
    assert basis == "project_type"
    assert evidence == "transportation_project"


def test_water_project_is_utilities() -> None:
    category, basis, _ = normalize_consumer_category(
        project_type="water_infrastructure",
        semantic_values=[],
        project_name="Generic project",
    )
    assert category == "utilities"
    assert basis == "project_type"


def test_official_subtype_outranks_public_works_default() -> None:
    category, basis, evidence = normalize_consumer_category(
        project_type="public_works",
        semantic_values=["Street Rehabilitation"],
        project_name="Capital Improvement 24-03",
    )
    assert category == "roads"
    assert basis == "official_subtype"
    assert evidence == "Street Rehabilitation"


def test_official_utility_subtype_outranks_project_name() -> None:
    category, basis, _ = normalize_consumer_category(
        project_type="public_works",
        semantic_values=["Storm Drain Improvement"],
        project_name="Main Street Project",
    )
    assert category == "utilities"
    assert basis == "official_subtype"


def test_public_place_subtype_is_places() -> None:
    category, basis, _ = normalize_consumer_category(
        project_type="public_works",
        semantic_values=["Park Improvements"],
        project_name="Project 12",
    )
    assert category == "places"
    assert basis == "official_subtype"


def test_municipal_development_stays_development_without_stronger_semantics() -> None:
    category, basis, _ = normalize_consumer_category(
        project_type="municipal_development",
        semantic_values=[],
        project_name="Oak Grove Apartments",
    )
    assert category == "development"
    assert basis == "project_type"


def test_name_is_only_a_fallback() -> None:
    category, basis, evidence = normalize_consumer_category(
        project_type="public_works",
        semantic_values=[],
        project_name="Library Renovation",
    )
    assert category == "places"
    assert basis == "name_fallback"
    assert evidence == "Library Renovation"
