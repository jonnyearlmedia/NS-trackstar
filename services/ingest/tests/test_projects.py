from __future__ import annotations

import pytest

from ns_trackstar.models import NormalizedRecord
from ns_trackstar.projects import _anchored_project, _insert_mapped_events, _project_name


def test_project_name_uses_first_populated_configured_field() -> None:
    record = NormalizedRecord(
        source_key="benicia.current-planning-applications",
        external_id="17",
        normalized_payload={"Descriptio": None, "Record__": "PHD-26-1"},
    )

    assert _project_name(record, {"name_fields": ["Descriptio", "Record__"]}) == "PHD-26-1"


@pytest.mark.asyncio
async def test_explicit_record_link_resolves_typed_source_anchor() -> None:
    class Cursor:
        async def fetchone(self):
            return {"id": "canonical-project-id"}

    class Connection:
        def __init__(self) -> None:
            self.params = None

        async def execute(self, _query, params):
            self.params = params
            return Cursor()

    record = NormalizedRecord(source_key="ceqanet", external_id="2021010044")
    mapping = {
        "record_links": {
            "2021010044": {
                "source_key": "suisun-city.development-calendar",
                "external_id": "project:suisun-logistics-center",
                "relationship_type": "environmental_review_for",
                "confidence": 1,
                "evidence": {"signals": ["SCH, location, and lead agency"]},
            }
        }
    }
    connection = Connection()

    result = await _anchored_project(connection, record=record, mapping=mapping)

    assert connection.params == (
        "suisun-city.development-calendar",
        "project:suisun-logistics-center",
    )
    assert result == (
        "canonical-project-id",
        "environmental_review_for",
        1,
        {"signals": ["SCH, location, and lead agency"]},
    )


@pytest.mark.asyncio
async def test_configured_anchor_fails_closed_when_target_is_missing() -> None:
    class Cursor:
        async def fetchone(self):
            return None

    class Connection:
        async def execute(self, _query, _params):
            return Cursor()

    record = NormalizedRecord(source_key="ceqanet", external_id="2021010044")
    mapping = {
        "record_links": {
            "2021010044": {
                "source_key": "tracker",
                "external_id": "missing-project",
            }
        }
    }

    with pytest.raises(RuntimeError, match="Configured project anchor was not found"):
        await _anchored_project(Connection(), record=record, mapping=mapping)


@pytest.mark.asyncio
async def test_mapped_event_keeps_stable_source_identity_for_idempotency() -> None:
    class Connection:
        def __init__(self) -> None:
            self.params = []

        async def execute(self, _query, params):
            self.params.append(params)

    record = NormalizedRecord(
        source_key="ceqanet",
        external_id="2021010044",
        normalized_payload={
            "document_events": [
                {
                    "identity": "https://ceqanet.lci.ca.gov/2021010044/4",
                    "event_type": "ceqa_document_received",
                    "occurred_at": "2026-07-27T00:00:00-07:00",
                    "title": "EIR received by State Clearinghouse",
                    "summary": "Suisun Logistics Center Project",
                    "metadata": {"sch_number": "2021010044"},
                }
            ]
        },
    )
    connection = Connection()

    await _insert_mapped_events(
        connection,
        project_id="project-id",
        source_record_id="source-record-id",
        record=record,
        mapping={"events": {"items_field": "document_events", "significance": 0.8}},
    )

    assert len(connection.params) == 1
    assert connection.params[0]["identity"].endswith("/2021010044/4")
    assert '"source_event_identity":"https://ceqanet.lci.ca.gov/2021010044/4"' in (
        connection.params[0]["metadata"]
    )
