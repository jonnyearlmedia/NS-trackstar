from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from ns_trackstar.db import canonical_json
from ns_trackstar.models import NormalizedRecord


@dataclass(frozen=True, slots=True)
class ProjectMaterialization:
    project_id: str
    created: bool
    status_changed: bool


def _value(record: NormalizedRecord, field: str | None) -> Any:
    if not field:
        return None
    return record.normalized_payload.get(field)


async def _latest_assertion_value(
    conn: psycopg.AsyncConnection, *, project_id: str, field: str
) -> Any:
    cursor = await conn.execute(
        """
        SELECT value
        FROM assertion
        WHERE project_id = %s AND field = %s
        ORDER BY observed_at DESC
        LIMIT 1
        """,
        (project_id, field),
    )
    row = await cursor.fetchone()
    return row["value"] if row else None


async def _assert_if_changed(
    conn: psycopg.AsyncConnection,
    *,
    project_id: str,
    source_id: str,
    source_record_id: str,
    field: str,
    value: Any,
    authority_type: str,
) -> str | None:
    if value is None:
        return None
    if await _latest_assertion_value(conn, project_id=project_id, field=field) == value:
        return None

    cursor = await conn.execute(
        """
        INSERT INTO assertion (
            project_id, field, value, source_id, source_record_id,
            authority_type, confidence, direct, inferred
        ) VALUES (
            %(project_id)s, %(field)s, %(value)s::jsonb, %(source_id)s, %(source_record_id)s,
            %(authority_type)s, 1, true, false
        ) RETURNING id
        """,
        {
            "project_id": project_id,
            "field": field,
            "value": canonical_json(value),
            "source_id": source_id,
            "source_record_id": source_record_id,
            "authority_type": authority_type,
        },
    )
    row = await cursor.fetchone()
    return str(row["id"]) if row else None


async def materialize_project(
    conn: psycopg.AsyncConnection,
    *,
    source_id: str,
    source_record_id: str,
    record: NormalizedRecord,
    mapping: dict[str, Any],
) -> ProjectMaterialization | None:
    name = _value(record, mapping.get("name_field"))
    if not name:
        return None

    cursor = await conn.execute(
        """
        SELECT p.id
        FROM project p
        JOIN project_source_record psr ON psr.project_id = p.id
        WHERE psr.source_record_id = %s AND psr.relationship_type = 'evidence_for'
        LIMIT 1
        """,
        (source_record_id,),
    )
    linked = await cursor.fetchone()
    created = linked is None

    if created:
        cursor = await conn.execute(
            """
            INSERT INTO project (canonical_name, project_type, primary_geometry, last_activity_at)
            SELECT %(name)s, %(project_type)s, geometry, COALESCE(source_updated_at, fetched_at)
            FROM source_record WHERE id = %(source_record_id)s
            RETURNING id
            """,
            {
                "name": str(name),
                "project_type": str(mapping.get("project_type", "project")),
                "source_record_id": source_record_id,
            },
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Failed to materialize project")
        project_id = str(row["id"])
        await conn.execute(
            """
            INSERT INTO project_source_record (project_id, source_record_id, relationship_type)
            VALUES (%s, %s, 'evidence_for')
            """,
            (project_id, source_record_id),
        )
        await conn.execute(
            """
            INSERT INTO project_location (
                project_id, geometry, geometry_method, geometry_source,
                location_accuracy, is_primary
            )
            SELECT id, primary_geometry, 'source_geometry', %(geometry_source)s,
                   %(location_accuracy)s::location_accuracy, true
            FROM project
            WHERE id = %(project_id)s AND primary_geometry IS NOT NULL
            """,
            {
                "project_id": project_id,
                "geometry_source": record.geometry_source or record.source_key,
                "location_accuracy": (
                    record.location_accuracy.value if record.location_accuracy else "approximate_area"
                ),
            },
        )
        await conn.execute(
            """
            INSERT INTO project_event (
                project_id, event_type, occurred_at, title, summary,
                source_record_id, significance
            ) VALUES (
                %(project_id)s, 'project_discovered', %(occurred_at)s,
                %(title)s, %(summary)s, %(source_record_id)s, 0.5
            )
            """,
            {
                "project_id": project_id,
                "occurred_at": record.source_updated_at or record.source_created_at,
                "title": f"Tracking {name}",
                "summary": _value(record, mapping.get("description_field")),
                "source_record_id": source_record_id,
            },
        )
    else:
        project_id = str(linked["id"])
        await conn.execute(
            """
            UPDATE project p SET
                canonical_name = %(name)s,
                primary_geometry = sr.geometry,
                last_activity_at = COALESCE(sr.source_updated_at, sr.fetched_at),
                updated_at = now()
            FROM source_record sr
            WHERE p.id = %(project_id)s AND sr.id = %(source_record_id)s
            """,
            {
                "project_id": project_id,
                "source_record_id": source_record_id,
                "name": str(name),
            },
        )

    authority_type = str(mapping.get("authority_type", "government_record"))
    for canonical_field, source_field in (mapping.get("assertions") or {}).items():
        await _assert_if_changed(
            conn,
            project_id=project_id,
            source_id=source_id,
            source_record_id=source_record_id,
            field=str(canonical_field),
            value=_value(record, str(source_field)),
            authority_type=authority_type,
        )

    status_changed = False
    dimension = mapping.get("status_dimension")
    status_field = mapping.get("status_field")
    status_value = _value(record, str(status_field)) if status_field else None
    if dimension and status_value is not None:
        cursor = await conn.execute(
            "SELECT value FROM project_status_dimension WHERE project_id = %s AND dimension = %s",
            (project_id, str(dimension)),
        )
        previous = await cursor.fetchone()
        previous_value = previous["value"] if previous else None
        status_changed = previous_value is not None and previous_value != str(status_value)

        assertion_id = await _assert_if_changed(
            conn,
            project_id=project_id,
            source_id=source_id,
            source_record_id=source_record_id,
            field=f"status.{dimension}",
            value=str(status_value),
            authority_type=authority_type,
        )

        await conn.execute(
            """
            INSERT INTO project_status_dimension (
                project_id, dimension, value, effective_at, assertion_id
            ) VALUES (%(project_id)s, %(dimension)s, %(value)s, %(effective_at)s, %(assertion_id)s)
            ON CONFLICT (project_id, dimension) DO UPDATE SET
                value = EXCLUDED.value,
                effective_at = EXCLUDED.effective_at,
                assertion_id = COALESCE(EXCLUDED.assertion_id, project_status_dimension.assertion_id),
                updated_at = now()
            """,
            {
                "project_id": project_id,
                "dimension": str(dimension),
                "value": str(status_value),
                "effective_at": record.source_updated_at,
                "assertion_id": assertion_id,
            },
        )

        if status_changed:
            await conn.execute(
                """
                INSERT INTO project_event (
                    project_id, event_type, occurred_at, title,
                    source_record_id, assertion_id, significance, metadata
                ) VALUES (
                    %(project_id)s, %(event_type)s, %(occurred_at)s, %(title)s,
                    %(source_record_id)s, %(assertion_id)s, 0.75, %(metadata)s::jsonb
                )
                """,
                {
                    "project_id": project_id,
                    "event_type": f"{dimension}_changed",
                    "occurred_at": record.source_updated_at,
                    "title": f"{dimension.replace('_', ' ').title()} changed to {status_value}",
                    "source_record_id": source_record_id,
                    "assertion_id": assertion_id,
                    "metadata": json.dumps(
                        {"from": previous_value, "to": str(status_value)}, separators=(",", ":")
                    ),
                },
            )

    return ProjectMaterialization(
        project_id=project_id,
        created=created,
        status_changed=status_changed,
    )
