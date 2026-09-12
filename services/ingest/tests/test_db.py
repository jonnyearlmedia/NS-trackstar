import json

import pytest

from ns_trackstar.db import canonical_json, persist_record, record_content_hash
from ns_trackstar.models import LocationAccuracy, NormalizedRecord


def test_content_hash_ignores_raw_transport_noise() -> None:
    base = NormalizedRecord(
        source_key="test",
        external_id="1",
        raw_payload={"request_id": "one"},
        normalized_payload={"status": "issued", "apn": "123"},
        geometry_geojson={"type": "Point", "coordinates": [-122.2, 38.1]},
        location_accuracy=LocationAccuracy.EXACT_ADDRESS,
    )
    noisy = base.model_copy(update={"raw_payload": {"request_id": "two"}})
    assert record_content_hash(base) == record_content_hash(noisy)


def test_content_hash_changes_for_semantic_change() -> None:
    base = NormalizedRecord(
        source_key="test",
        external_id="1",
        normalized_payload={"status": "issued"},
    )
    changed = base.model_copy(update={"normalized_payload": {"status": "finaled"}})
    assert record_content_hash(base) != record_content_hash(changed)


def test_canonical_json_replaces_postgres_unsupported_unicode_without_dropping_text() -> None:
    encoded = canonical_json(
        {
            "agenda\x00note": "Approve\x00the item",
            "nested": ["valid", "unpaired surrogate: \ud800"],
        }
    )

    assert "\x00" not in encoded
    assert "\ud800" not in encoded
    assert json.loads(encoded) == {
        "agenda\ufffdnote": "Approve\ufffdthe item",
        "nested": ["valid", "unpaired surrogate: \ufffd"],
    }


def test_content_hash_uses_the_postgres_storable_representation() -> None:
    unsupported = NormalizedRecord(
        source_key="test",
        external_id="unicode",
        normalized_payload={"agenda_note": "Approve\x00the item"},
    )
    replacement = unsupported.model_copy(
        update={"normalized_payload": {"agenda_note": "Approve\ufffdthe item"}}
    )

    assert record_content_hash(unsupported) == record_content_hash(replacement)


@pytest.mark.asyncio
async def test_persist_record_types_null_geometry_for_postgres() -> None:
    class Cursor:
        def __init__(self, row) -> None:
            self.row = row

        async def fetchone(self):
            return self.row

    class Connection:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def execute(self, query, _params=None):
            self.queries.append(query)
            if query.startswith("SELECT id, content_hash"):
                return Cursor(None)
            if "INSERT INTO source_record" in query:
                return Cursor({"id": "record-id"})
            return Cursor(None)

    connection = Connection()
    record = NormalizedRecord(
        source_key="test",
        external_id="without-geometry",
        normalized_payload={"name": "Source record without geometry"},
    )

    persisted = await persist_record(connection, source_id="source-id", record=record)

    assert persisted.changed is True
    geometry_queries = [query for query in connection.queries if "ST_GeomFromGeoJSON" in query]
    assert geometry_queries
    assert all("%(geometry)s::text" in query for query in geometry_queries)


@pytest.mark.asyncio
async def test_persist_record_sanitizes_raw_and_normalized_json_parameters() -> None:
    class Cursor:
        def __init__(self, row) -> None:
            self.row = row

        async def fetchone(self):
            return self.row

    class Connection:
        def __init__(self) -> None:
            self.parameters: list[dict | tuple | None] = []

        async def execute(self, query, params=None):
            self.parameters.append(params)
            if query.startswith("SELECT id, content_hash"):
                return Cursor(None)
            if "INSERT INTO source_record" in query:
                return Cursor({"id": "record-id"})
            return Cursor(None)

    connection = Connection()
    record = NormalizedRecord(
        source_key="napa-city.legistar",
        external_id="event:1:item:2",
        raw_payload={"EventItemAgendaNote": "First\x00second"},
        normalized_payload={"agenda_note": "First\x00second"},
    )

    await persist_record(connection, source_id="source-id", record=record)

    json_parameters = [
        value
        for parameters in connection.parameters
        if isinstance(parameters, dict)
        for key, value in parameters.items()
        if key in {"raw_payload", "normalized_payload"}
    ]
    assert json_parameters
    assert all("\x00" not in value for value in json_parameters)
    assert any("First\ufffdsecond" in value for value in json_parameters)
