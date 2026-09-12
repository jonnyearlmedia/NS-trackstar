import json
from pathlib import Path

import httpx
import pytest

from ns_trackstar.adapters.arcgis import ArcGISRestAdapter
from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.models import LocationAccuracy


@pytest.fixture
def source_config() -> SourceConfig:
    return SourceConfig(
        key="test.parcels",
        name="Test parcels",
        jurisdiction="Test County",
        base_url="https://example.test",
        poll_minutes=1440,
        options={
            "layer_url": "https://example.test/FeatureServer/0",
            "id_field": "OBJECTID",
            "page_size": 100,
        },
    )


@pytest.mark.asyncio
async def test_arcgis_collects_geojson_without_flattening_fields(source_config: SourceConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {
                                "OBJECTID": 7,
                                "APN": "0182-010-010",
                                "CITY": "Vallejo",
                                "CUSTOM_FIELD": "preserved",
                            },
                            "geometry": {
                                "type": "Point",
                                "coordinates": [-122.2, 38.1],
                            },
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "name": "Parcels",
                "type": "Feature Layer",
                "maxRecordCount": 2000,
                "fields": [
                    {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                    {"name": "APN", "type": "esriFieldTypeString", "length": 32},
                    {"name": "CITY", "type": "esriFieldTypeString", "length": 64},
                    {"name": "CUSTOM_FIELD", "type": "esriFieldTypeString", "length": 64},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ArcGISRestAdapter(source_config, client=client)
        result = await adapter.collect()

    assert result.parser_yield == 1.0
    assert len(result.records) == 1
    record = result.records[0]
    assert record.external_id == "7"
    assert record.normalized_payload["CUSTOM_FIELD"] == "preserved"
    assert record.location_accuracy == LocationAccuracy.EXACT_SOURCE_GEOMETRY


@pytest.mark.asyncio
async def test_arcgis_canary_requires_configured_id_field(source_config: SourceConfig) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "name": "Parcels",
                "type": "Feature Layer",
                "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ArcGISRestAdapter(source_config, client=client)
        assert await adapter.canary() is True


@pytest.mark.asyncio
async def test_arcgis_canary_requires_all_configured_source_fields() -> None:
    config = SourceConfig(
        key="test.projects",
        name="Test projects",
        jurisdiction=None,
        base_url="https://example.test",
        poll_minutes=1440,
        options={
            "layer_url": "https://example.test/FeatureServer/0",
            "id_field": "OBJECTID",
            "canary_fields": ["PROJECT_NAME", "STATUS"],
        },
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "Feature Layer",
                "fields": [
                    {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                    {"name": "PROJECT_NAME", "type": "esriFieldTypeString"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await ArcGISRestAdapter(config, client=client).canary() is False


@pytest.mark.asyncio
async def test_arcgis_canary_checks_geometry_and_plausible_filtered_count() -> None:
    config = SourceConfig(
        key="test.transportation",
        name="Test transportation projects",
        jurisdiction="Test County",
        base_url="https://example.test",
        poll_minutes=1440,
        options={
            "layer_url": "https://example.test/FeatureServer/0",
            "id_field": "ProjectID",
            "where": "CountyName = 'Test'",
            "expected_geometry_type": "esriGeometryMultipoint",
            "min_expected_records": 10,
            "max_expected_records": 100,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            assert request.url.params["where"] == "CountyName = 'Test'"
            assert request.url.params["returnCountOnly"] == "true"
            return httpx.Response(200, json={"count": 25})
        return httpx.Response(
            200,
            json={
                "type": "Feature Layer",
                "geometryType": "esriGeometryMultipoint",
                "fields": [{"name": "ProjectID", "type": "esriFieldTypeString"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await ArcGISRestAdapter(config, client=client).canary() is True

    too_many = config.options | {"max_expected_records": 20}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ArcGISRestAdapter(
            SourceConfig(
                key=config.key,
                name=config.name,
                jurisdiction=config.jurisdiction,
                base_url=config.base_url,
                poll_minutes=config.poll_minutes,
                options=too_many,
            ),
            client=client,
        )
        assert await adapter.canary() is False


def test_arcgis_ignores_placeholder_canonical_urls() -> None:
    assert ArcGISRestAdapter._canonical_url(" N/A ") is None
    assert ArcGISRestAdapter._canonical_url("https://example.test/project") == (
        "https://example.test/project"
    )


def test_caltrans_building_ca_config_preserves_identifiers_without_construction_inference() -> None:
    config_path = (
        Path(__file__).parents[3]
        / "config"
        / "sources"
        / "caltrans.building-ca.napa-solano.json"
    )
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    options = payload["options"]
    mapping = options["project_mapping"]

    assert payload["adapter"] == "arcgis_rest"
    assert options["id_field"] == "BCAProjectID"
    assert {"BCAProjectID", "ProjectID", "SB1Funds", "IIJAFunds"}.issubset(
        options["canary_fields"]
    )
    assert mapping["assertions"]["building_california_project_id"] == "BCAProjectID"
    assert mapping["assertions"]["project_number"] == "ProjectID"
    assert mapping["assertions"]["total_cost"] == "TotalCost"
    assert mapping["status_dimension"] == "official_program_status"
    assert mapping["status_dimension"] != "construction"
    assert options["expected_geometry_type"] == "esriGeometryMultipoint"
    assert options["min_expected_records"] > 0
