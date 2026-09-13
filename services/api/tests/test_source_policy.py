from ns_trackstar_api import cadence
from ns_trackstar_api.source_policy import SOURCE_FRESHNESS_POLICIES


EXPECTED_PRODUCTION_SOURCES = {
    "american-canyon.construction-development-updates",
    "benicia.current-planning-applications",
    "bia.scotts-valley-gaming-decisions",
    "california.ceqanet.napa-solano",
    "caltrans.building-ca.napa-solano",
    "fairfield.one-lake-assessor-map",
    "fairfield.one-lake-council-goals",
    "fairfield.vanden-canon-overcrossing",
    "federal-register.napa-solano",
    "napa-city.legistar",
    "napa-city.napa-pipe-amendments",
    "napa-city.public-works-cip",
    "napa-city.water-cip",
    "napa-county.current-projects-explorer",
    "napa-county.napa-pipe-development-plan",
    "napa-county.parcels",
    "nigc.scotts-valley-gaming-ordinance",
    "solano-county.legistar",
    "solano-county.parcels",
    "suisun-city.development-calendar",
    "suisun-city.dutch-bros-public-notice",
    "vallejo.civicclerk",
    "vallejo.value-current-development",
}


def test_every_production_source_has_an_explicit_freshness_policy() -> None:
    assert set(SOURCE_FRESHNESS_POLICIES) == EXPECTED_PRODUCTION_SOURCES
    assert len(SOURCE_FRESHNESS_POLICIES) == 23


def test_policy_ranges_are_sane() -> None:
    for source_key, policy in SOURCE_FRESHNESS_POLICIES.items():
        assert policy.recommended_min_minutes > 0, source_key
        assert policy.recommended_max_minutes >= policy.recommended_min_minutes, source_key
        assert policy.meaningful_change_window, source_key
        assert policy.rationale, source_key


def test_policy_state_reports_within_faster_slower_and_unclassified() -> None:
    source = "napa-city.legistar"
    assert cadence._policy_state(source, 60)["cadence_policy_state"] == "within_policy"
    assert cadence._policy_state(source, 30)["cadence_policy_state"] == "faster_than_needed"
    assert cadence._policy_state(source, 240)["cadence_policy_state"] == "slower_than_recommended"

    missing = cadence._policy_state("does-not-exist", 60)
    assert missing["cadence_policy_state"] == "unclassified"
    assert missing["freshness_class"] == "unclassified"
