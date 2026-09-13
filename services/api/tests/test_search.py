from datetime import UTC, datetime
from uuid import UUID

import pytest

from ns_trackstar_api.app import app, search_projects


@pytest.mark.asyncio
async def test_search_returns_evidence_match_without_geometry() -> None:
    class Cursor:
        async def fetchall(self):
            return [
                {
                    "id": UUID("4ff99fa2-9617-4232-b10b-2df456aab31d"),
                    "canonical_name": "Dutch Bros",
                    "project_type": "municipal_development",
                    "last_activity_at": datetime(2025, 9, 17, tzinfo=UTC),
                    "geometry": None,
                    "statuses": {"official_tracker_stage": "under_review_or_in_process"},
                    "summary": "Drive thru coffee business",
                    "matched_on": "project_evidence",
                }
            ]

    class Database:
        def __init__(self) -> None:
            self.params = None

        async def execute(self, _query, params):
            self.params = params
            return Cursor()

    database = Database()
    previous = getattr(app.state, "db", None)
    app.state.db = database
    try:
        results = await search_projects(q="  Highway   12  ", limit=20)
    finally:
        if previous is None:
            del app.state.db
        else:
            app.state.db = previous

    assert database.params["query"] == "Highway 12"
    assert database.params["pattern"] == "%Highway 12%"
    assert results[0]["name"] == "Dutch Bros"
    assert results[0]["geometry"] is None
    assert results[0]["matched_on"] == "project_evidence"
