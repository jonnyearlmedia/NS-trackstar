import pytest

from ns_trackstar.db import persist_record, record_content_hash
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
