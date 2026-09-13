"""The high-interest portfolio is a promise, so it has to stay checkable.

These tests do not hit the network. They assert the file stays honest about itself:
every entry names a real jurisdiction, every tier is one Trackstar actually measures,
and - the one that matters - a "guaranteed" entry has to carry the evidence that
earned it. A guaranteed tier with no observed name is an assertion, not a measurement,
and this file exists precisely so that nobody has to take coverage on trust.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ns_trackstar_api.coverage import load_manifest

PORTFOLIO = Path("fixtures/high-interest/portfolio.json")
TIERS = {"guaranteed", "found_unmapped", "watchlist"}


@pytest.fixture(scope="module")
def portfolio() -> dict:
    return json.loads(PORTFOLIO.read_text())


def test_every_entry_is_shaped_and_tiered(portfolio: dict) -> None:
    projects = portfolio["projects"]
    assert len(projects) >= 80, "the portfolio should not silently shrink"
    keys = [project["key"] for project in projects]
    assert len(keys) == len(set(keys)), "project keys must be unique"
    for project in projects:
        assert project["tier"] in TIERS, project
        assert project["queries"], project["key"]
        assert project["label"].strip(), project["key"]


def test_guaranteed_entries_carry_the_evidence_that_earned_them(portfolio: dict) -> None:
    for project in portfolio["projects"]:
        if project["tier"] != "guaranteed":
            continue
        # Measured, not asserted: a guaranteed project was found by name and placed.
        assert project.get("observed_name"), f"{project['key']} claims guaranteed with no match"
        assert project.get("mapped") is True, f"{project['key']} is guaranteed but not mapped"


def test_watchlist_entries_make_no_coverage_claim(portfolio: dict) -> None:
    # A watchlist entry is a target. It must not carry an observation, because a
    # target that looks like a result is how a gap turns into a false green.
    for project in portfolio["projects"]:
        if project["tier"] == "watchlist":
            assert "observed_name" not in project, project["key"]


def test_every_jurisdiction_named_is_one_trackstar_actually_covers(portfolio: dict) -> None:
    known = {j["name"] for j in load_manifest()["jurisdictions"]}
    known |= {name.replace("City of ", "").replace("Town of ", "") for name in known}
    known |= {"Unincorporated Napa County", "Unincorporated Solano County"}
    for project in portfolio["projects"]:
        assert project["jurisdiction"] in known, project["jurisdiction"]


def test_the_recorded_counts_match_the_entries(portfolio: dict) -> None:
    counted: dict[str, int] = {}
    for project in portfolio["projects"]:
        counted[project["tier"]] = counted.get(project["tier"], 0) + 1
    assert counted == portfolio["measured_counts"], (
        "the summary at the top of the file has drifted from the entries below it"
    )
