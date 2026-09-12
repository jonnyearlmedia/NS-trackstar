import pytest

from ns_trackstar_api.app import app, changes, map_projects


class EmptyCursor:
    async def fetchall(self):
        return []


class RecordingDatabase:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, query: str, params: dict[str, object]):
        self.calls.append((query, params))
        return EmptyCursor()


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

    assert len(database.calls) == 2
    for query, params in database.calls:
        assert "p.project_type = %(project_type)s" in query
        assert params["project_type"] == "municipal_development"
