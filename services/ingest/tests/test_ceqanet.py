from __future__ import annotations

import csv
import io

import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.ceqanet import CeqanetAdapter, _row_preference, parse_coordinates
from ns_trackstar.models import LocationAccuracy

FIELDNAMES = [
    "SCH Number",
    "Lead Agency Name",
    "Lead Agency Title",
    "Lead Agency Acronym",
    "Document Title",
    "Document Type",
    "Received",
    "Posted",
    "Document Description",
    "Document Portal URL",
    "Project Title",
    "Location Coordinates",
    "Cities",
    "Counties",
    "Location Cross Streets",
    "Location Zip Code",
    "Location Total Acres",
    "Location Parcel Number",
    "Location State Highways",
    "Location Waterways",
    "NOC State Review Start Date",
    "NOC State Review End Date",
    "NOC Development Type",
    "NOC Local Action",
    "NOC Project Issues",
]


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _row(**changes: str) -> dict[str, str]:
    row = dict.fromkeys(FIELDNAMES, "")
    row.update(
        {
            "SCH Number": "2021010044",
            "Lead Agency Name": "City of Suisun",
            "Document Title": "Suisun Logistics Center Project",
            "Document Type": "EIR",
            "Received": "7/27/2026",
            "Document Description": "Industrial logistics development.",
            "Document Portal URL": "https://ceqanet.lci.ca.gov/2021010044/4",
            "Project Title": "Suisun Logistics Center Project",
            "Location Coordinates": "38°14'22\"N 121°58'48\"W",
            "Cities": "Suisun City",
            "Counties": "Solano",
            "Location Cross Streets": "State Route 12 / Walters Road",
        }
    )
    row.update(changes)
    return row


def _config() -> SourceConfig:
    return SourceConfig(
        key="california.ceqanet.napa-solano",
        name="CEQAnet Napa and Solano",
        jurisdiction="Napa and Solano Counties",
        base_url="https://ceqanet.lci.ca.gov/Search",
        poll_minutes=1440,
        options={
            "queries": [{"County": "Solano", "StartRange": "2020-01-01"}],
            "canary_sch": "2021010044",
            "max_counties_per_record": 4,
        },
    )


def test_parse_coordinates_preserves_source_point_as_lon_lat() -> None:
    geometry = parse_coordinates("38°14'22\"N 121°58'48\"W")
    assert geometry is not None
    assert geometry["type"] == "Point"
    assert geometry["coordinates"] == pytest.approx([-121.98, 38.2394444444])


def test_duplicate_row_preference_is_deterministic_and_favors_more_source_data() -> None:
    sparse = _row()
    complete = _row(**{"Location Total Acres": "167.43"})
    assert _row_preference(complete) > _row_preference(sparse)


@pytest.mark.asyncio
async def test_collect_groups_documents_by_sch_and_excludes_statewide_rows() -> None:
    historical = _row(
        **{
            "Document Type": "NOP",
            "Received": "1/6/2021",
            "Document Portal URL": "https://ceqanet.lci.ca.gov/2021010044/2",
        }
    )
    statewide = _row(
        **{
            "SCH Number": "2026000001",
            "Counties": "Alameda, Contra Costa, Napa, Solano, Sonoma",
            "Document Portal URL": "https://ceqanet.lci.ca.gov/2026000001",
        }
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        rows = [_row()] if request.url.params.get("Sch") else [_row(), historical, statewide]
        return httpx.Response(200, content=_csv_bytes(rows), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CeqanetAdapter(_config(), client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert len(result.records) == 1
    record = result.records[0]
    assert record.external_id == "2021010044"
    assert record.location_accuracy == LocationAccuracy.APPROXIMATE_AREA
    assert record.normalized_payload["document_count"] == 2
    assert len(record.normalized_payload["document_events"]) == 2
    assert record.normalized_payload["latest_document_type"] == "EIR"
    assert record.source_created_at.isoformat().startswith("2021-01-06")
    assert record.source_updated_at.isoformat().startswith("2026-07-27")
    assert result.metadata["excluded_broad_geographies"] == 1
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_canary_rejects_changed_csv_schema() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="SCH Number,Project Title\n2021010044,Test\n", request=request
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await CeqanetAdapter(_config(), client=client).canary() is False
