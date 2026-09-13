from types import SimpleNamespace
from uuid import UUID

import pytest

from ns_trackstar_api.search import FUZZY_THRESHOLD, search_projects_classified


@pytest.mark.asyncio
async def test_classified_search_enables_fuzzy_human_queries() -> None:
    class Cursor:
        async def fetchall(self):
            return [
                {
                    "id": UUID("4ff99fa2-9617-4232-b10b-2df456aab31d"),
                    "canonical_name": "Napa Pipe",
                    "project_type": "municipal_development",
                    "last_activity_at": None,
                    "geometry": None,
                    "statuses": {"official_tracker_stage": "Proposed"},
                    "summary": "Mixed-use redevelopment project",
                    "semantic_values": ["Napa Pipe", "Napa"],
                    "matched_on": "fuzzy_project_name",
                }
            ]

    class Database:
        def __init__(self) -> None:
            self.query = ""
            self.params = None

        async def execute(self, query, params):
            self.query = query
            self.params = params
            return Cursor()

    database = Database()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=database)))

    results = await search_projects_classified(request=request, q="npa pipe", limit=20)

    assert database.params["query"] == "npa pipe"
    assert database.params["fuzzy_threshold"] == FUZZY_THRESHOLD
    assert "similarity(p.canonical_name" in database.query
    assert "similarity(pa.alias::text" in database.query
    assert "similarity((a.value #>> '{}')" in database.query
    assert results[0]["name"] == "Napa Pipe"
    assert results[0]["matched_on"] == "fuzzy_project_name"
    assert results[0]["consumer_category"] == "development"
