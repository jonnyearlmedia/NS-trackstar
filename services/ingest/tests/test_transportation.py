from __future__ import annotations

import os
from unittest.mock import AsyncMock

import httpx
import pytest

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.adapters.transportation import BayArea511TrafficAdapter, WzdxAdapter
from ns_trackstar.cli import _dry_run
from ns_trackstar.models import LocationAccuracy
from ns_trackstar.registry import build_adapter


def wzdx_config(*, token_env: str | None = None, bbox: list[float] | None = None) -> SourceConfig:
    options: dict[str, object] = {
        "endpoint_url": "https://example.test/traffic/wzdx",
        "request_params": {"includeAllDefinedEnums": "false"},
    }
    if bbox:
        options["bbox"] = bbox
    if token_env:
        options["api_key_env"] = token_env
    return SourceConfig(
        key="test.wzdx",
        name="Test WZDx",
        jurisdiction="Test County",
        base_url="https://example.test/traffic/wzdx",
        poll_minutes=5,
        options=options,
    )


def traffic_config(*, max_pages: int = 3, service_area_names: list[str] | None = None) -> SourceConfig:
    return SourceConfig(
        key="test.511-traffic",
        name="Test 511 Traffic",
        jurisdiction="Test County",
        base_url="https://api.511.org/traffic/events",
        poll_minutes=5,
        options={
            "endpoint_url": "https://api.511.org/traffic/events",
            "api_key_env": "TEST_511_API_KEY",
            "status": "ACTIVE",
            "bbox": [-122.75, 37.95, -121.55, 38.9],
            "page_size": 1,
            "max_pages": max_pages,
            "service_area_names": service_area_names or [],
        },
    )


def wzdx_payload(*, features: list[dict] | None = None) -> dict:
    if features is None:
        features = [
            {
                "type": "Feature",
                "id": "DOT-37-001",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.31, 38.12], [-122.29, 38.13]],
                },
                "properties": {
                    "core_details": {
                        "event_type": "work-zone",
                        "data_source_id": "DOT-1",
                        "road_names": ["SR-37"],
                        "direction": "eastbound",
                        "creation_date": "2026-09-01T12:00:00Z",
                        "update_date": "2026-09-11T15:30:00Z",
                        "description": "Bridge rehabilitation",
                    },
                    "start_date": "2026-09-10T07:00:00Z",
                    "end_date": "2026-10-01T07:00:00Z",
                    "event_status": "active",
                    "beginning_accuracy": "verified",
                    "ending_accuracy": "estimated",
                    "location_method": "channel-device-method",
                    "vehicle_impact": "some-lanes-closed",
                    "project_id": "EA-0Q250",
                    "route": "37",
                    "beginning_postmile": "4.2",
                    "ending_postmile": "6.8",
                    "vendor_extension": {"funding_id": "PPNO-1234"},
                },
            }
        ]
    return {
        "road_event_feed_info": {
            "publisher": "Test DOT",
            "version": "4.2",
            "update_date": "2026-09-11T15:35:00Z",
            "data_sources": [{"data_source_id": "DOT-1"}],
        },
        "type": "FeatureCollection",
        "features": features,
    }


def test_transportation_adapters_are_config_driven_registry_entries() -> None:
    assert isinstance(build_adapter("wzdx", wzdx_config()), WzdxAdapter)
    assert isinstance(
        build_adapter("bayarea_511_traffic", traffic_config()),
        BayArea511TrafficAdapter,
    )


@pytest.mark.asyncio
async def test_wzdx_preserves_line_geometry_status_identifiers_and_extensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["includeAllDefinedEnums"] == "false"
        return httpx.Response(200, json=wzdx_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = WzdxAdapter(wzdx_config(), client=client)
        assert await adapter.canary() is True
        result = await adapter.collect()

    assert result.parser_yield == 1.0
    reti = result.records[0]
    assert reti.external_id == "DOT-37-001"
    assert reti.geometry_geojson["type"] == "LineString"
    assert reti.location_accuracy == LocationAccuracy.EXACT_SOURCE_GEOMETRY
    assert reti.normalized_payload["event_status"] == "active"
    assert reti.normalized_payload["project_id"] == "EA-0Q250"
    assert reti.normalized_payload["route"] == "37"
    assert reti.normalized_payload["begin_postmile"] == "4.2"
    assert reti.normalized_payload["end_postmile"] == "6.8"
    assert reti.normalized_payload["vendor_extension"]["funding_id"] == "PPNO-1234"
    assert reti.normalized_payload["location_accuracy_detail"] == {
        "beginning": "verified",
        "ending": "estimated",
        "method": "channel-device-method",
    }
    assert reti.source_updated_at.isoformat() == "2026-09-11T15:30:00+00:00"
    assert result.metadata["feed_version"] == "4.2"
    assert result.schema_fingerprint


@pytest.mark.asyncio
async def test_wzdx_zero_records_is_valid_only_with_feed_invariants() -> None:
    async def run(payload: dict) -> tuple[bool, float]:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = WzdxAdapter(wzdx_config(), client=client)
            return await adapter.canary(), (await adapter.collect()).parser_yield

    valid, parser_yield = await run(wzdx_payload(features=[]))
    assert valid is True
    assert parser_yield == 1.0

    invalid_payload = {"type": "FeatureCollection", "features": []}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=invalid_payload))
    async with httpx.AsyncClient(transport=transport) as client:
        assert await WzdxAdapter(wzdx_config(), client=client).canary() is False


@pytest.mark.asyncio
async def test_wzdx_missing_configured_token_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_WZDX_TOKEN", raising=False)
    transport = httpx.MockTransport(lambda _: pytest.fail("HTTP must not run without a token"))
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = WzdxAdapter(wzdx_config(token_env="MISSING_WZDX_TOKEN"), client=client)
        with pytest.raises(SourceBlockedError, match="MISSING_WZDX_TOKEN"):
            await adapter.canary()


@pytest.mark.asyncio
async def test_missing_token_dry_run_reports_blocked_without_http(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MISSING_WZDX_TOKEN", raising=False)
    config = wzdx_config(token_env="MISSING_WZDX_TOKEN")
    assert await _dry_run("wzdx", config) == 3
    output = capsys.readouterr().out
    assert '"health_state": "blocked"' in output
    assert "MISSING_WZDX_TOKEN" in output


@pytest.mark.asyncio
async def test_511_traffic_paginates_and_prefers_closure_line_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_511_API_KEY", "secret-test-token")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["api_key"] == "secret-test-token"
        assert request.url.params["bbox"] == "-122.75,37.95,-121.55,38.9"
        offset = int(request.url.params["offset"])
        event = {
            "url": f"/traffic/events/511.org/{offset + 149}",
            "id": f"511.org/{offset + 149}",
            "status": "ACTIVE",
            "headline": "Road work on SR-37",
            "event_type": "CONSTRUCTION",
            "event_subtypes": ["Road Work"],
            "severity": "MODERATE",
            "created": "2026-09-11T14:00:00Z",
            "updated": "2026-09-11T15:00:00Z",
            "geography": {"type": "Point", "coordinates": [-122.3, 38.1]},
            "+closure_geography": {
                "type": "MultiLineString",
                "coordinates": [[[-122.31, 38.1], [-122.29, 38.11]]],
            },
            "roads": [
                {
                    "name": "SR-37",
                    "state": "Closed",
                    "+lane_status": "closed",
                    "+lane_type": "right lane",
                    "begin_postmile": "4.2",
                    "end_postmile": "6.8",
                }
            ],
            "+source_id": "CALTRANS-149",
            "+source_name": "Caltrans",
        }
        return httpx.Response(
            200,
            json={
                "events": [event] if offset == 0 else [],
                "pagination": (
                    {"offset": 0, "next_url": "/traffic/events?limit=1&offset=1"}
                    if offset == 0
                    else {"offset": 1}
                ),
                "meta": {"version": "v1"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = BayArea511TrafficAdapter(traffic_config(), client=client)
        result = await adapter.collect()

    assert len(requests) == 2
    assert len(result.records) == 1
    record = result.records[0]
    assert record.external_id == "511.org/149"
    assert record.canonical_url == "https://api.511.org/traffic/events/511.org/149"
    assert record.geometry_geojson["type"] == "MultiLineString"
    assert record.normalized_payload["geometry_method"] == "source_provided_closure_geometry"
    assert record.normalized_payload["route"] == "SR-37"
    assert record.normalized_payload["begin_postmile"] == "4.2"
    assert record.normalized_payload["end_postmile"] == "6.8"
    assert record.normalized_payload["lane_status"] == "closed"
    assert record.raw_payload["+source_id"] == "CALTRANS-149"


@pytest.mark.asyncio
async def test_511_canary_accepts_valid_empty_active_event_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_511_API_KEY", "test-token")
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={"events": [], "pagination": {"offset": 0}, "meta": {"version": "v1"}},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await BayArea511TrafficAdapter(traffic_config(), client=client).canary() is True


@pytest.mark.asyncio
async def test_511_rejected_token_is_blocked_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_511_API_KEY", "do-not-leak-this-token")
    transport = httpx.MockTransport(lambda _: httpx.Response(401, json={"error": "unauthorized"}))
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = BayArea511TrafficAdapter(traffic_config(), client=client)
        with pytest.raises(SourceBlockedError) as error:
            await adapter.canary()
    assert "do-not-leak-this-token" not in str(error.value)
    assert os.environ["TEST_511_API_KEY"] not in str(error.value)


@pytest.mark.asyncio
async def test_511_retries_429_and_honors_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_511_API_KEY", "test-token")
    sleep = AsyncMock()
    monkeypatch.setattr("ns_trackstar.adapters.transportation.asyncio.sleep", sleep)
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(
            200,
            json={"events": [], "pagination": {"offset": 0}, "meta": {"version": "v1"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await BayArea511TrafficAdapter(traffic_config(), client=client).canary() is True

    assert attempts == 2
    sleep.assert_awaited_once_with(7.0)


@pytest.mark.asyncio
async def test_traffic_events_keep_only_the_counties_511_itself_labels() -> None:
    """The bbox request parameter is accepted and ignored by this endpoint.

    A run that trusted it returned Pescadero and Santa Cruz roadwork as Napa and
    Solano coverage, so the filter is 511's own `areas[].name` and the yield is
    measured against the events that survive it rather than against the whole Bay
    Area - a filter rate dressed as a parse rate can never catch a parse break.
    """
    events = [
        {
            "id": "napa-1",
            "status": "ACTIVE",
            "event_type": "CONSTRUCTION",
            "headline": "Roadwork on CA-128",
            "areas": [{"name": "Napa"}],
            "geography": {"type": "Point", "coordinates": [-122.4, 38.5]},
            "roads": [{"name": "CA-128"}],
            "updated": "2026-09-13T15:00:00Z",
        },
        {
            "id": "sonoma-1",
            "status": "ACTIVE",
            "event_type": "CONSTRUCTION",
            "headline": "Roadwork on CA-116",
            "areas": [{"name": "Sonoma"}],
            "geography": {"type": "Point", "coordinates": [-122.9, 38.5]},
            "roads": [{"name": "CA-116"}],
            "updated": "2026-09-13T15:00:00Z",
        },
        {
            "id": "sanmateo-1",
            "status": "ACTIVE",
            "event_type": "CONSTRUCTION",
            "headline": "Roadwork on CA-84",
            "areas": [{"name": "San Mateo"}],
            "geography": {"type": "Point", "coordinates": [-122.3, 37.2]},
            "roads": [{"name": "CA-84"}],
            "updated": "2026-09-13T15:00:00Z",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"events": events, "pagination": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        os.environ["TEST_511_API_KEY"] = "test-token"
        adapter = BayArea511TrafficAdapter(
            traffic_config(service_area_names=["Napa", "Solano"]), client=client
        )
        result = await adapter.collect()

    assert [r.normalized_payload.get("event_id") or r.external_id for r in result.records]
    assert len(result.records) == 1
    assert result.metadata["events_seen"] == 3
    assert result.metadata["service_area_events"] == 1
    assert result.parser_yield == 1.0


@pytest.mark.asyncio
async def test_wzdx_keeps_a_work_zone_that_only_partly_reaches_the_service_area() -> None:
    """A work zone is a line. Testing one representative point would drop a closure
    that starts outside the service area and ends inside it, which is exactly the
    closure a resident on that road needs to know about."""
    def feature(fid: str, coords: list[list[float]]) -> dict:
        base = wzdx_payload()["features"][0]
        return {**base, "id": fid, "geometry": {"type": "LineString", "coordinates": coords}}

    feed = wzdx_payload(
        features=[
            feature("crosses-in", [[-123.0, 38.4], [-122.3, 38.5]]),
            feature("far-away", [[-121.0, 37.2], [-121.1, 37.3]]),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=feed)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = WzdxAdapter(
            wzdx_config(bbox=[-122.64, 38.03, -121.59, 38.87]), client=client
        )
        result = await adapter.collect()

    assert result.metadata["features_seen"] == 2
    assert result.metadata["service_area_features"] == 1
    assert result.parser_yield == 1.0
