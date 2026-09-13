"""Images carry a legal obligation, so the rules are asserted, not assumed.

Two mistakes are easy here and both are expensive. Showing an image we have no basis
to show is a rights problem. Showing a row that was only ever a research note - "we
know the page, we never resolved the file" - puts a broken image in front of a
resident. The schema forbids both and these tests hold the API to the same line.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCHEMA = Path("db/migrations/0005_project_image.sql")
SEED = Path("db/migrations/0006_seed_verified_project_images.sql")
API = Path("services/api/src/ns_trackstar_api/app.py")


@pytest.fixture(scope="module")
def schema_sql() -> str:
    return SCHEMA.read_text()


@pytest.fixture(scope="module")
def api_sql() -> str:
    return API.read_text()


def test_a_cached_copy_requires_a_recorded_basis(schema_sql: str) -> None:
    # "cleared" with nothing behind it is an assertion nobody can audit later, which is
    # precisely the state this table exists to make impossible.
    assert "project_image_cached_only_when_cleared" in schema_sql
    assert "project_image_cleared_needs_evidence" in schema_sql
    assert "rights_evidence_url IS NOT NULL" in schema_sql


def test_a_row_claiming_to_be_an_image_has_to_carry_one(schema_sql: str) -> None:
    assert "project_image_resolved_has_asset" in schema_sql
    assert re.search(
        r"asset_resolution_status <> 'resolved' OR asset_url IS NOT NULL", schema_sql
    )


def test_only_one_hero_per_project(schema_sql: str) -> None:
    assert "project_image_single_hero_idx" in schema_sql
    assert "WHERE is_hero" in schema_sql


def test_the_consumer_query_filters_on_both_resolution_and_rights(api_sql: str) -> None:
    # The whole point: an unresolved row and a row we may not show must never reach a
    # consumer response, and the filter has to be in the query rather than in a caller
    # who might forget.
    start = api_sql.index("FROM project_image")
    block = api_sql[start : start + 400]
    assert "asset_resolution_status = 'resolved'" in block
    assert "rights_status IN ('reference_only', 'cleared')" in block


def test_the_api_prefers_our_own_copy_when_we_are_allowed_one(api_sql: str) -> None:
    assert "COALESCE(cached_asset_url, asset_url)" in api_sql


def test_nothing_seeded_claims_to_be_cleared(schema_sql: str) -> None:
    seed = SEED.read_text()
    # Every seeded image is an agency's own photograph on the agency's own server.
    # Published is not licensed.
    assert "'cleared'" not in seed
    assert seed.count("'reference_only'") >= 2


def test_fairfield_is_seeded_as_unresolved_because_its_assets_403(schema_sql: str) -> None:
    seed = SEED.read_text()
    fairfield = seed[seed.index("West Texas") - 1200 :]
    # Five exact URLs are known and every one answers 403 to automated clients.
    # Recording them as resolved would put five broken images in front of a resident.
    assert "'unresolved'" in fairfield
    assert "403" in seed
