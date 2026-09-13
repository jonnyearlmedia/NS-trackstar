from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from ns_trackstar.adapters.abc_ca import (
    REPORT_TYPES,
    SERVICE_AREA_COUNTY_CODES,
    AbcCaAdapter,
    _parse_premises,
)
from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig

DATA = Path("services/ingest/tests/data")


def config(**options) -> SourceConfig:
    return SourceConfig(
        key="california.abc.napa-solano-smoke",
        name="California ABC Daily Licensing Reports",
        jurisdiction="Napa and Solano Counties",
        base_url="https://www.abc.ca.gov",
        poll_minutes=720,
        options={
            "report_types": ["new_applications"],
            "lookback_days": 1,
            "min_request_interval_seconds": 0,
            **options,
        },
    )


def adapter_with(handler, **options) -> AbcCaAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x")
    return AbcCaAdapter(config(**options), client=client)


def report_handler(page_html: str, post_html: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, html=page_html)
        return httpx.Response(200, html=post_html)

    return handler


def test_a_dba_line_is_the_only_thing_treated_as_a_trade_name():
    cell = BeautifulSoup(
        "<td>DBA: NARDI RESTAURANT<br/>NARDI RESTAURANT LLC<br/>"
        "3415 TELEGRAPH AVE,<br/>OAKLAND, CA 94609-3002</td>",
        "html.parser",
    ).td
    parsed = _parse_premises(cell)
    assert parsed["dba_name"] == "NARDI RESTAURANT"
    assert parsed["owner_name"] == "NARDI RESTAURANT LLC"
    assert parsed["premises_address_lines"] == ["3415 TELEGRAPH AVE,", "OAKLAND, CA 94609-3002"]


def test_a_licence_holder_name_is_never_promoted_to_a_storefront_brand():
    """Without a DBA label the first line is a person, not a business opening."""

    cell = BeautifulSoup(
        "<td>MOHAMED, BASHAR HASSAN<br/>330 W INYO AVE,<br/>TULARE, CA 93274</td>",
        "html.parser",
    ).td
    parsed = _parse_premises(cell)
    assert parsed["dba_name"] is None
    assert parsed["owner_name"] == "MOHAMED, BASHAR HASSAN"


@pytest.mark.asyncio
async def test_statewide_report_is_filtered_to_the_service_area_by_county_code():
    html = DATA.joinpath("abc-new-applications.html").read_text()
    adapter = adapter_with(report_handler(html, html))

    result = await adapter.collect()

    assert result.records, "the fixture contains a Napa row"
    counties = {record.normalized_payload["county"] for record in result.records}
    assert counties <= set(SERVICE_AREA_COUNTY_CODES.values())
    cities = {record.normalized_payload["city"].upper() for record in result.records}
    assert "NAPA" in cities
    # Oakland is in the same statewide report and must not survive the filter.
    assert "OAKLAND" not in cities
    assert result.metadata["statewide_rows_seen"] >= len(result.records)


@pytest.mark.asyncio
async def test_status_changes_report_keeps_its_own_columns():
    html = DATA.joinpath("abc-status-changes.html").read_text()
    adapter = adapter_with(report_handler(html, html), report_types=["status_changes"])

    result = await adapter.collect()

    assert result.records
    record = result.records[0]
    assert record.normalized_payload["report_type"] == "status_changes"
    # Ownership transfer and the from/to status are only in this report; they must not
    # be flattened away by a shared parser.
    assert "status_changed_from_to" in record.normalized_payload
    assert "transfer_from_to" in record.normalized_payload
    assert record.normalized_payload["city"].upper() == "VALLEJO"


@pytest.mark.asyncio
async def test_records_carry_a_stable_id_and_the_official_lookup_url():
    html = DATA.joinpath("abc-new-applications.html").read_text()
    adapter = adapter_with(report_handler(html, html))

    first = await adapter.collect()
    second = await adapter.collect()

    assert [record.external_id for record in first.records] == [
        record.external_id for record in second.records
    ]
    for record in first.records:
        assert record.canonical_url.startswith(
            "https://www.abc.ca.gov/licensing/license-lookup/single-license/"
        )
        assert record.normalized_payload["license_number"] in record.external_id


@pytest.mark.asyncio
async def test_a_changed_column_set_fails_loudly_instead_of_returning_nothing():
    html = DATA.joinpath("abc-new-applications.html").read_text().replace("County", "Cnty")
    adapter = adapter_with(report_handler(html, html))

    with pytest.raises(RuntimeError, match="columns changed"):
        await adapter.collect()


@pytest.mark.asyncio
async def test_an_empty_statewide_week_is_a_failure_not_a_clean_run():
    """California does not stop issuing licences for a week; an empty run is broken."""

    empty = '<html><body><form id="daily-license-report-form">' \
            '<input name="rpttype" value="2"/><input name="abclqs_daily_report" value="n"/>' \
            "</form></body></html>"
    adapter = adapter_with(report_handler(empty, empty), lookback_days=7)

    with pytest.raises(RuntimeError, match="no statewide rows"):
        await adapter.collect()


@pytest.mark.asyncio
async def test_a_cloudflare_challenge_is_reported_as_blocked_not_worked_around():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"cf-mitigated": "challenge"}, html="Just a moment...")

    adapter = adapter_with(handler)

    with pytest.raises(SourceBlockedError, match="Cloudflare bot challenge"):
        await adapter.canary()


@pytest.mark.asyncio
async def test_canary_fails_when_the_report_form_is_gone():
    adapter = adapter_with(report_handler("<html><body>no form</body></html>", ""))
    assert await adapter.canary() is False


def test_every_report_type_is_a_real_abc_report():
    assert set(REPORT_TYPES) == {"new_applications", "issued_licenses", "status_changes"}
    with pytest.raises(ValueError, match="Unsupported ABC report type"):
        AbcCaAdapter(config(report_types=["invented_report"]))
