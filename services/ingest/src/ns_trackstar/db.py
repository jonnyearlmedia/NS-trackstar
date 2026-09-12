from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ns_trackstar.models import CollectorResult, NormalizedRecord


@dataclass(frozen=True, slots=True)
class PersistedRecord:
    id: str
    changed: bool


@dataclass(frozen=True, slots=True)
class PersistSummary:
    source_id: str
    run_id: str
    records_seen: int
    records_changed: int
    projects_created: int
    projects_touched: int


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_content_hash(record: NormalizedRecord) -> str:
    payload = {
        "normalized_payload": record.normalized_payload,
        "geometry": record.geometry_geojson,
        "geometry_source": record.geometry_source,
        "location_accuracy": record.location_accuracy.value if record.location_accuracy else None,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@asynccontextmanager
async def connect(database_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    connection = await psycopg.AsyncConnection.connect(database_url, row_factory=dict_row)
    try:
        yield connection
    finally:
        await connection.close()


async def ensure_source(
    conn: psycopg.AsyncConnection,
    *,
    source_key: str,
    name: str,
    source_family: str,
    jurisdiction: str | None,
    base_url: str,
    poll_interval_minutes: int,
    collector_type: str,
    config: dict,
) -> str:
    cursor = await conn.execute(
        """
        INSERT INTO source (
            source_key, name, source_family, jurisdiction, base_url,
            poll_interval_minutes, collector_type, config
        )
        VALUES (%(source_key)s, %(name)s, %(source_family)s, %(jurisdiction)s, %(base_url)s,
                %(poll_interval_minutes)s, %(collector_type)s, %(config)s::jsonb)
        ON CONFLICT (source_key) DO UPDATE SET
            name = EXCLUDED.name,
            source_family = EXCLUDED.source_family,
            jurisdiction = EXCLUDED.jurisdiction,
            base_url = EXCLUDED.base_url,
            poll_interval_minutes = EXCLUDED.poll_interval_minutes,
            collector_type = EXCLUDED.collector_type,
            config = EXCLUDED.config,
            enabled = true
        RETURNING id
        """,
        {
            "source_key": source_key,
            "name": name,
            "source_family": source_family,
            "jurisdiction": jurisdiction,
            "base_url": base_url,
            "poll_interval_minutes": poll_interval_minutes,
            "collector_type": collector_type,
            "config": canonical_json(config),
        },
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Failed to upsert source {source_key}")
    return str(row["id"])


async def start_source_run(conn: psycopg.AsyncConnection, source_id: str) -> str:
    cursor = await conn.execute(
        "INSERT INTO source_run (source_id) VALUES (%s) RETURNING id",
        (source_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Failed to create source run")
    return str(row["id"])


async def fail_source_run(
    conn: psycopg.AsyncConnection,
    *,
    run_id: str,
    source_id: str,
    error_type: str,
    error_message: str,
    canary_ok: bool | None,
    health_state: str = "broken",
) -> None:
    await conn.execute(
        """
        UPDATE source_run SET
            finished_at = now(), success = false,
            canary_ok = %(canary_ok)s,
            error_type = %(error_type)s,
            error_message = %(error_message)s
        WHERE id = %(run_id)s
        """,
        {
            "run_id": run_id,
            "canary_ok": canary_ok,
            "error_type": error_type,
            "error_message": error_message[:4000],
        },
    )
    await conn.execute(
        """
        INSERT INTO source_health (
            source_id, last_attempt_at, consecutive_failures,
            expected_poll_interval_minutes, health_state, health_reason
        )
        SELECT s.id, now(), 1, s.poll_interval_minutes,
               %(health_state)s::source_health_state, %(health_reason)s
        FROM source s WHERE s.id = %(source_id)s
        ON CONFLICT (source_id) DO UPDATE SET
            last_attempt_at = now(),
            consecutive_failures = source_health.consecutive_failures + 1,
            expected_poll_interval_minutes = EXCLUDED.expected_poll_interval_minutes,
            health_state = EXCLUDED.health_state,
            health_reason = EXCLUDED.health_reason,
            updated_at = now()
        """,
        {
            "source_id": source_id,
            "health_state": health_state,
            "health_reason": f"{error_type}: {error_message}"[:4000],
        },
    )


async def persist_record(
    conn: psycopg.AsyncConnection,
    *,
    source_id: str,
    record: NormalizedRecord,
) -> PersistedRecord:
    content_hash = record_content_hash(record)
    geometry_json = canonical_json(record.geometry_geojson) if record.geometry_geojson else None
    location_accuracy = record.location_accuracy.value if record.location_accuracy else None

    cursor = await conn.execute(
        "SELECT id, content_hash FROM source_record WHERE source_id = %s AND external_id = %s",
        (source_id, record.external_id),
    )
    existing = await cursor.fetchone()
    changed = existing is None or existing["content_hash"] != content_hash

    params = {
        "source_id": source_id,
        "external_id": record.external_id,
        "canonical_url": record.canonical_url,
        "source_created_at": record.source_created_at,
        "source_updated_at": record.source_updated_at,
        "raw_payload": canonical_json(record.raw_payload),
        "normalized_payload": canonical_json(record.normalized_payload),
        "content_hash": content_hash,
        "geometry": geometry_json,
        "geometry_source": record.geometry_source,
        "location_accuracy": location_accuracy,
    }

    if existing is None:
        cursor = await conn.execute(
            """
            INSERT INTO source_record (
                source_id, external_id, canonical_url,
                source_created_at, source_updated_at,
                raw_payload, normalized_payload, content_hash,
                geometry, geometry_source, location_accuracy
            ) VALUES (
                %(source_id)s, %(external_id)s, %(canonical_url)s,
                %(source_created_at)s, %(source_updated_at)s,
                %(raw_payload)s::jsonb, %(normalized_payload)s::jsonb, %(content_hash)s,
                CASE WHEN %(geometry)s IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326) END,
                %(geometry_source)s, %(location_accuracy)s::location_accuracy
            ) RETURNING id
            """,
            params,
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Failed to insert source record")
        record_id = str(row["id"])
    else:
        record_id = str(existing["id"])
        await conn.execute(
            """
            UPDATE source_record SET
                canonical_url = %(canonical_url)s,
                source_created_at = COALESCE(%(source_created_at)s, source_created_at),
                source_updated_at = COALESCE(%(source_updated_at)s, source_updated_at),
                last_seen_at = now(), fetched_at = now(),
                raw_payload = %(raw_payload)s::jsonb,
                normalized_payload = %(normalized_payload)s::jsonb,
                content_hash = %(content_hash)s,
                geometry = CASE WHEN %(geometry)s IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326) END,
                geometry_source = %(geometry_source)s,
                location_accuracy = %(location_accuracy)s::location_accuracy
            WHERE id = %(id)s
            """,
            {**params, "id": record_id},
        )

    if changed:
        await conn.execute(
            """
            INSERT INTO source_snapshot (
                source_record_id, content_hash, raw_payload, normalized_payload, geometry
            ) VALUES (
                %(source_record_id)s, %(content_hash)s,
                %(raw_payload)s::jsonb, %(normalized_payload)s::jsonb,
                CASE WHEN %(geometry)s IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326) END
            ) ON CONFLICT (source_record_id, content_hash) DO NOTHING
            """,
            {
                "source_record_id": record_id,
                "content_hash": content_hash,
                "raw_payload": canonical_json(record.raw_payload),
                "normalized_payload": canonical_json(record.normalized_payload),
                "geometry": geometry_json,
            },
        )

    return PersistedRecord(id=record_id, changed=changed)


async def finish_source_run(
    conn: psycopg.AsyncConnection,
    *,
    run_id: str,
    source_id: str,
    result: CollectorResult,
    records_changed: int,
    canary_ok: bool,
) -> None:
    await conn.execute(
        """
        UPDATE source_run SET
            finished_at = now(), success = true,
            records_returned = %(records_returned)s,
            records_changed = %(records_changed)s,
            schema_fingerprint = %(schema_fingerprint)s,
            parser_yield = %(parser_yield)s, canary_ok = %(canary_ok)s
        WHERE id = %(run_id)s
        """,
        {
            "run_id": run_id,
            "records_returned": len(result.records),
            "records_changed": records_changed,
            "schema_fingerprint": result.schema_fingerprint,
            "parser_yield": result.parser_yield,
            "canary_ok": canary_ok,
        },
    )

    await conn.execute(
        """
        INSERT INTO source_health (
            source_id, last_attempt_at, last_success_at, last_successful_parse_at,
            last_record_seen_at, last_content_change_at, records_returned,
            consecutive_failures, schema_fingerprint, parser_yield,
            expected_poll_interval_minutes, health_state, health_reason
        )
        SELECT s.id, now(), now(), now(),
            CASE WHEN %(records_returned)s > 0 THEN now() ELSE NULL END,
            CASE WHEN %(records_changed)s > 0 THEN now() ELSE NULL END,
            %(records_returned)s, 0, %(schema_fingerprint)s, %(parser_yield)s,
            s.poll_interval_minutes, 'healthy'::source_health_state, NULL
        FROM source s WHERE s.id = %(source_id)s
        ON CONFLICT (source_id) DO UPDATE SET
            last_attempt_at = EXCLUDED.last_attempt_at,
            last_success_at = EXCLUDED.last_success_at,
            last_successful_parse_at = EXCLUDED.last_successful_parse_at,
            last_record_seen_at = COALESCE(EXCLUDED.last_record_seen_at, source_health.last_record_seen_at),
            last_content_change_at = COALESCE(EXCLUDED.last_content_change_at, source_health.last_content_change_at),
            records_returned = EXCLUDED.records_returned,
            consecutive_failures = 0,
            schema_fingerprint = EXCLUDED.schema_fingerprint,
            parser_yield = EXCLUDED.parser_yield,
            expected_poll_interval_minutes = EXCLUDED.expected_poll_interval_minutes,
            health_state = EXCLUDED.health_state,
            health_reason = NULL, updated_at = now()
        """,
        {
            "source_id": source_id,
            "records_returned": len(result.records),
            "records_changed": records_changed,
            "schema_fingerprint": result.schema_fingerprint,
            "parser_yield": result.parser_yield,
        },
    )


async def persist_collection(
    conn: psycopg.AsyncConnection,
    *,
    source_id: str,
    run_id: str,
    result: CollectorResult,
    canary_ok: bool,
    project_mapping: dict[str, Any] | None = None,
) -> PersistSummary:
    from ns_trackstar.projects import materialize_project

    changed = 0
    projects_created = 0
    projects_touched = 0

    for record in result.records:
        persisted = await persist_record(conn, source_id=source_id, record=record)
        changed += int(persisted.changed)

        if project_mapping:
            project = await materialize_project(
                conn,
                source_id=source_id,
                source_record_id=persisted.id,
                record=record,
                mapping=project_mapping,
            )
            if project:
                projects_touched += 1
                projects_created += int(project.created)

    await finish_source_run(
        conn,
        run_id=run_id,
        source_id=source_id,
        result=result,
        records_changed=changed,
        canary_ok=canary_ok,
    )
    return PersistSummary(
        source_id=source_id,
        run_id=run_id,
        records_seen=len(result.records),
        records_changed=changed,
        projects_created=projects_created,
        projects_touched=projects_touched,
    )
