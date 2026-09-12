import psycopg
import pytest

from ns_trackstar_api.app import ResilientDatabaseConnection


@pytest.mark.asyncio
async def test_execute_reconnects_once_after_database_restart(monkeypatch) -> None:
    class DeadConnection:
        async def execute(self, _query, _params):
            raise psycopg.OperationalError("server closed the connection")

        async def close(self):
            return None

    class FreshConnection:
        async def execute(self, query, params):
            return (query, params)

        async def close(self):
            return None

    fresh = FreshConnection()

    async def reconnect(*_args, **_kwargs):
        return fresh

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", reconnect)
    database = ResilientDatabaseConnection("postgresql://example")
    database.connection = DeadConnection()

    result = await database.execute("SELECT %s", (1,))

    assert result == ("SELECT %s", (1,))
    assert database.connection is fresh
