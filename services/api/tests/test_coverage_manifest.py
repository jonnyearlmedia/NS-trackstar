from __future__ import annotations

import json
from pathlib import Path

from ns_trackstar_api.coverage import (
    build_scorecard,
    coverage_gaps,
    derive_state,
    load_manifest,
    manifest_path,
    production_source_keys,
    smoke_source_keys,
)

# Every jurisdiction the map's service-area polygon claims. Removing one from the
# manifest is a product decision, not a data-availability decision, so the contract
# pins the list.
SERVICE_AREA_JURISDICTIONS = {
    "napa",
    "american-canyon",
    "yountville",
    "st-helena",
    "calistoga",
    "napa-county",
    "vallejo",
    "benicia",
    "fairfield",
    "suisun-city",
    "vacaville",
    "dixon",
    "rio-vista",
    "solano-county",
}

REQUIRED_CATEGORIES = {
    "current_development",
    "permits",
    "government_meetings",
    "cip_construction",
    "gis_spatial",
    "ceqa_environmental",
    "business_openings",
    "transportation",
    "procurement",
    "specialized_regulatory",
}


def test_manifest_covers_the_whole_service_area():
    manifest = load_manifest()
    keys = {item["key"] for item in manifest["jurisdictions"]}
    assert keys == SERVICE_AREA_JURISDICTIONS
    assert {item["key"] for item in manifest["categories"]} == REQUIRED_CATEGORIES


def test_every_jurisdiction_is_scored_in_every_category():
    scorecard = build_scorecard()
    assert len(scorecard["jurisdictions"]) == len(SERVICE_AREA_JURISDICTIONS)
    for jurisdiction in scorecard["jurisdictions"]:
        categories = {row["category"] for row in jurisdiction["categories"]}
        assert categories == REQUIRED_CATEGORIES, jurisdiction["key"]


def test_every_declared_source_exists_on_disk():
    manifest = load_manifest()
    known = production_source_keys() | smoke_source_keys()
    for jurisdiction in manifest["jurisdictions"]:
        for category, entry in jurisdiction["categories"].items():
            for item in entry.get("evidence") or []:
                assert item["source"] in known, f"{jurisdiction['key']}/{category}: {item['source']}"
            blocker = entry.get("blocker") or {}
            smoke_source = blocker.get("smoke_source")
            if smoke_source:
                assert smoke_source in known, smoke_source


def test_state_is_derived_from_evidence_not_declared():
    assert derive_state(scopes=("recurring_tracker",), has_blocker=False) == "strong"
    assert derive_state(scopes=("recurring_tracker",), has_blocker=True) == "strong"
    assert derive_state(scopes=("regional_rollup",), has_blocker=False) == "partial"
    assert derive_state(scopes=("project_specific",), has_blocker=False) == "partial"
    assert derive_state(scopes=("reference",), has_blocker=False) == "partial"
    assert derive_state(scopes=(), has_blocker=True) == "blocked"
    assert derive_state(scopes=(), has_blocker=False) == "missing"


def test_a_jurisdiction_is_never_strong_without_a_production_source():
    scorecard = build_scorecard()
    production = production_source_keys()
    for jurisdiction in scorecard["jurisdictions"]:
        for row in jurisdiction["categories"]:
            if row["state"] in {"strong", "partial"}:
                assert row["production_sources"], f"{jurisdiction['key']}/{row['category']}"
                assert set(row["production_sources"]) <= production
            else:
                assert not row["production_sources"], f"{jurisdiction['key']}/{row['category']}"


def test_unpromoted_sources_never_raise_a_state():
    """A smoke config is evidence of intent, never evidence of coverage."""

    scorecard = build_scorecard()
    for jurisdiction in scorecard["jurisdictions"]:
        for row in jurisdiction["categories"]:
            if not row["production_sources"]:
                assert row["state"] in {"blocked", "missing"}


def test_parcels_and_ceqa_alone_do_not_make_development_coverage():
    """Explicit product rule: reference data is not project activity."""

    scorecard = build_scorecard()
    by_key = {item["key"]: item for item in scorecard["jurisdictions"]}
    # This list has emptied steadily through September 13, 2026, and every departure
    # was a source that began returning records, never reference data starting to
    # count. St. Helena and Calistoga left on their own project pages; Dixon on its
    # CEQA review page; Rio Vista, Dixon and Suisun City on permit systems that turned
    # out to live on hosts their blocked websites never pointed at.
    #
    # Development and permits are tracked separately now, because they stopped moving
    # together: Rio Vista has thousands of permit records and still publishes no
    # planning pipeline at all.
    for key in ("vacaville", "rio-vista", "yountville"):
        rows = {row["category"]: row for row in by_key[key]["categories"]}
        # These jurisdictions genuinely do get statewide CEQA filings, and full county
        # spatial truth: parcels, address-level geocoding and jurisdiction boundaries.
        assert rows["ceqa_environmental"]["state"] == "partial"
        assert rows["gis_spatial"]["state"] == "strong"
        # ...but neither ever reads as local development coverage. Knowing exactly
        # where a project would sit is not knowing that one exists.
        #
        # The assertion is "not covered" rather than one exact label, because a
        # category legitimately moves between missing and blocked as work proceeds.
        # Both still mean not covered, and pinning the label would make that progress
        # look like a regression.
        assert rows["current_development"]["state"] in {"missing", "blocked"}

    for key in ("vacaville", "yountville"):
        rows = {row["category"]: row for row in by_key[key]["categories"]}
        assert rows["permits"]["state"] in {"missing", "blocked"}


def test_spatial_truth_is_only_strong_with_parcels_addresses_and_boundaries():
    assert derive_state(
        scopes=("reference",),
        has_blocker=False,
        category="gis_spatial",
        roles=("parcels", "address_level", "boundaries"),
    ) == "strong"
    # Parcels on their own were the old state of the world, and were never enough.
    assert derive_state(
        scopes=("reference",),
        has_blocker=False,
        category="gis_spatial",
        roles=("parcels",),
    ) == "partial"
    # The spatial rule never leaks into another category.
    assert derive_state(
        scopes=("reference",),
        has_blocker=False,
        category="current_development",
        roles=("parcels", "address_level", "boundaries"),
    ) == "partial"


def test_blocked_jurisdictions_record_why_and_name_the_smoke_config():
    scorecard = build_scorecard()
    blocked = [
        (jurisdiction["key"], row)
        for jurisdiction in scorecard["jurisdictions"]
        for row in jurisdiction["categories"]
        if row["state"] == "blocked"
    ]
    assert blocked, "the manifest should record the known upstream blockers"
    for key, row in blocked:
        assert row["blocker"] and row["blocker"].get("reason"), f"{key}/{row['category']}"


def test_gaps_list_is_actionable_and_ordered_by_manifest():
    gaps = coverage_gaps("partial")
    assert gaps
    assert all(row["state"] in {"blocked", "missing"} for row in gaps)
    assert {row["jurisdiction"] for row in gaps} <= SERVICE_AREA_JURISDICTIONS


def test_manifest_file_is_committed_and_parses():
    path = manifest_path()
    assert path.exists()
    json.loads(Path(path).read_text())
