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
