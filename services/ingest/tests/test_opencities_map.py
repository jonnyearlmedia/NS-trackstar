import httpx
import pytest

from ns_trackstar.adapters.base import SourceConfig
from ns_trackstar.adapters.opencities_map import OpenCitiesMapAdapter
from ns_trackstar.models import LocationAccuracy


@pytest.fixture
def config() -> SourceConfig:
    return SourceConfig(
        key="american-canyon.development-updates",
        name="American Canyon Development Updates",
        jurisdiction="City of American Canyon",
        base_url="https://example.test/updates",
        poll_minutes=1440,
        options={
            "map_id": "map-id",
            "bounds": "38.05,-122.5,38.35,-122.05",
            "expected_map_name": "Construction & Development Updates",
            "expected_layer_names": ["Under Review"],
            "min_request_interval_seconds": 0,
        },
    )


@pytest.mark.asyncio
async def test_collects_structured_markers_and_details(config: SourceConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ocmaps/get/map-id":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "map": {
                        "id": "map-id",
                        "Name": "Construction & Development Updates",
                        "layer": [{"Id": "review", "Name": "Under Review"}],
                    },
                },
            )
        if request.url.path == "/ocmaps/layer":
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "resultsLeft": 0,
                    "layerItems": [
                        {
                            "ContentId": "project-id",
                            "MainContentId": "main-id",
                            "ContentTitle": "Paoli / Watson Lane Annexation",
                            "Lat": "38.1948",
                            "Lng": " -122.2555",
                            "Id": "review",
                            "Name": "Under Review",
                        }
                    ],
                },
            )
        assert request.url.path == "/ocapi/get/markerinfo/project-id/en-US"
        return httpx.Response(
            200,
            json={
                "success": True,
                "markerInfo": {
                    "Title": "Paoli / Watson Lane Annexation",
                    "Description": "General Plan amendment and annexation.",
                    "Link": "https://example.test/projects/paoli",
                    "Address": {"Formatted": "Paoli Loop Rd., American Canyon, 94503"},
                    "AdditionalInfo": [],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenCitiesMapAdapter(config, client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert result.parser_yield == 1.0
    assert result.records[0].external_id == "project-id"
    assert result.records[0].normalized_payload["tracker_stage"] == "Under Review"
    assert result.records[0].geometry_geojson == {
        "type": "Point",
        "coordinates": [-122.2555, 38.1948],
    }
    assert result.records[0].location_accuracy == LocationAccuracy.EXACT_SOURCE_GEOMETRY


@pytest.mark.asyncio
async def test_fails_closed_when_map_results_are_truncated(config: SourceConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/ocmaps/get/"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "map": {
                        "id": "map-id",
                        "Name": "Construction & Development Updates",
                        "layer": [{"Id": "review", "Name": "Under Review"}],
                    },
                },
            )
        return httpx.Response(
            200,
            json={"success": True, "resultsLeft": 1, "layerItems": []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="response was truncated"):
            await OpenCitiesMapAdapter(config, client=client).collect()
