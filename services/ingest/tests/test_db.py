from ns_trackstar.db import record_content_hash
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
