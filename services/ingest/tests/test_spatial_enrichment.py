from __future__ import annotations

import re
from pathlib import Path

import pytest

from ns_trackstar.enrichment import (
    ADDRESS_POINT_SOURCES,
    JURISDICTION_BOUNDARY_SOURCES,
    enrich_project_jurisdictions,
    enrich_projects_from_address_points,
    normalize_address,
)

MIGRATION = Path("db/migrations/0004_spatial_reference.sql")


class Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetchall(self):
        return self._rows


class Connection:
    """Records every statement so the SQL contract can be asserted without a database."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._rows = rows or []

    async def execute(self, query, params=None):
        self.calls.append((query, params or {}))
        return Cursor(self._rows)


def test_address_normalization_collapses_only_real_noise():
    assert normalize_address("1025 Kaiser Rd") == "1025 kaiser road"
    assert normalize_address("1025  KAISER ROAD.") == "1025 kaiser road"
    assert normalize_address("1025 Kaiser Rd.") == normalize_address("1025 kaiser road")
    assert normalize_address("  ") == ""
    assert normalize_address(None) == ""


def test_directionals_are_never_normalized_away():
    """North and South Main Street are different places."""

    assert normalize_address("100 N Main St") != normalize_address("100 S Main St")
    assert normalize_address("100 N Main St") == "100 n main street"


def test_sql_and_python_address_normalizers_use_the_same_abbreviations():
    """One drifting abbreviation would silently stop matching a whole street type."""

    sql = MIGRATION.read_text()
    sql_pairs = dict(re.findall(r"WHEN '([a-z]+)' THEN '([a-z]+)'", sql))
    assert sql_pairs, "the migration should define the abbreviation table"

    for abbreviation, expansion in sql_pairs.items():
        assert normalize_address(f"1 Test {abbreviation}") == f"1 test {expansion}"

    # And nothing the Python side expands is missing from SQL.
    for abbreviation in ("st", "rd", "dr", "ave", "blvd", "pkwy", "hwy", "ct", "ln"):
        assert abbreviation in sql_pairs


def test_migration_defines_the_function_and_supporting_indexes():
    sql = MIGRATION.read_text()
    assert "CREATE OR REPLACE FUNCTION ns_trackstar_normalize_address" in sql
    assert "IMMUTABLE" in sql
    assert "source_record_address_key_idx" in sql
    assert "assertion_jurisdiction_idx" in sql


@pytest.mark.asyncio
async def test_jurisdiction_stamp_runs_once_per_official_boundary_layer():
    connection = Connection([{"project_id": "p1"}, {"project_id": "p2"}])

    stamped = await enrich_project_jurisdictions(connection)

    assert stamped == 4  # two projects per boundary layer
    assert len(connection.calls) == len(JURISDICTION_BOUNDARY_SOURCES) == 2
    source_keys = {params["source_key"] for _query, params in connection.calls}
    assert source_keys == {"napa-county.city-boundaries", "solano-county.city-boundaries"}


@pytest.mark.asyncio
async def test_jurisdiction_stamp_is_recorded_as_derived_not_as_an_agency_claim():
    connection = Connection()
    await enrich_project_jurisdictions(connection)

    query, params = connection.calls[0]
    assert "'derived_spatial'" in query
    assert "false,\n              true," in query  # direct=false, inferred=true
    assert "point_in_polygon" in query
    # Land inside neither city polygon is unincorporated, which is an answer.
    assert params["unincorporated"].startswith("Unincorporated ")


@pytest.mark.asyncio
async def test_address_placement_only_accepts_an_unambiguous_point():
    connection = Connection([{"project_id": "p1"}])

    placed = await enrich_projects_from_address_points(connection)

    assert placed == len(ADDRESS_POINT_SOURCES) == 1
    query, params = connection.calls[0]
    # One address key on two different points is ambiguous and must not place a pin.
    assert "ap.duplicates = 1" in query
    # Placement never overwrites geometry a source already supplied.
    assert "p.primary_geometry IS NULL" in query
    assert "'exact_address'" in query
    assert "'address_point_match'" in query
    assert params["source_key"] == "napa-county.addresses"


@pytest.mark.asyncio
async def test_spatial_enrichment_passes_source_keys_as_bound_parameters():
    for enrichment in (enrich_project_jurisdictions, enrich_projects_from_address_points):
        connection = Connection()
        await enrichment(connection)
        for _query, params in connection.calls:
            assert "source_key" in params
