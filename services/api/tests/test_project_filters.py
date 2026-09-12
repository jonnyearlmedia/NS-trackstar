import pytest

from ns_trackstar_api.app import _display_priority, app, changes, map_projects


class EmptyCursor:
    async def fetchall(self):
        return []

    async def fetchone(self):
        return {"total_matching": 0, "mapped_matching": 0}


class RecordingDatabase:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, query: str, params: dict[str, object]):
        self.calls.append((query, params))
        return EmptyCursor()


def test_display_priority_surfaces_large_review_only_projects() -> None:
    priority = _display_priority(
        {
            "importance_score": 0,
            "project_type": "environmental_review",
            "source_count": 1,
            "status_count": 1,
            "relationship_count": 0,
            "scale_acres": 160,
            "delivery_stage": None,
        }
    )
    assert priority >= 0.4


def test_display_priority_keeps_small_single_source_reviews_quiet() -> None:
    priority = _display_priority(
        {
            "importance_score": 0,
            "project_type": "environmental_review",
            "source_count": 1,
            "status_count": 1,
            "relationship_count": 0,
            "scale_acres": 1,
            "delivery_stage": None,
        }
    )
    assert priority < 0.4


@pytest.mark.asyncio
async def test_map_and_change_queries_apply_project_type_filter() -> None:
    database = RecordingDatabase()
    previous = getattr(app.state, "db", None)
    app.state.db = database
    try:
        await map_projects(
            west=None,
            south=None,
            east=None,
            north=None,
            time_window="all",
            project_type="municipal_development",
        )
        await changes(
            time_window="all",
            limit=50,
            project_type="municipal_development",
        )
    finally:
        if previous is None:
            del app.state.db
        else:
            app.state.db = previous

    # Map rendering now runs both a feature query and a coverage metadata query,
    # followed by the changes query. Every scoped query must apply the same type filter.
    assert len(database.calls) == 3
    for query, params in database.calls:
        assert "p.project_type = %(project_type)s" in query
        assert params["project_type"] == "municipal_development"
