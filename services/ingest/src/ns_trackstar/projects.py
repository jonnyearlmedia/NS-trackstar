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


def _configured_record_link(
    record: NormalizedRecord, mapping: dict[str, Any]
) -> dict[str, Any] | None:
    link = (mapping.get("record_links") or {}).get(record.external_id)
    return dict(link) if isinstance(link, dict) else None


async def _anchored_project(
    conn: psycopg.AsyncConnection,
    *,
    record: NormalizedRecord,
    mapping: dict[str, Any],
) -> tuple[str, str, float, dict[str, Any]] | None:
    link = _configured_record_link(record, mapping)
    if link is None:
        return None

    source_key = str(link["source_key"])
    external_id = str(link["external_id"])
    relationship_type = str(link.get("relationship_type", "evidence_for"))
    confidence = float(link.get("confidence", 1))
    evidence = dict(link.get("evidence") or {})
    cursor = await conn.execute(
        """
        SELECT p.id
        FROM source s
        JOIN source_record sr ON sr.source_id = s.id
        JOIN project_source_record psr ON psr.source_record_id = sr.id
        JOIN project p ON p.id = psr.project_id
        WHERE s.source_key = %s AND sr.external_id = %s
        ORDER BY CASE WHEN psr.relationship_type = 'evidence_for' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (source_key, external_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Configured project anchor was not found: {source_key}/{external_id}")
    return str(row["id"]), relationship_type, confidence, evidence


async def _insert_mapped_events(
    conn: psycopg.AsyncConnection,
    *,
    project_id: str,
    source_record_id: str,
    record: NormalizedRecord,
    mapping: dict[str, Any],
) -> None:
    event_mapping = mapping.get("events") or {}
    items = _value(record, event_mapping.get("items_field"))
    if not isinstance(items, list):
        return

    identity_field = str(event_mapping.get("identity_field", "identity"))
    significance = float(event_mapping.get("significance", 0.5))
    for item in items:
        if not isinstance(item, dict):
            continue
        identity = item.get(identity_field)
        event_type = item.get(str(event_mapping.get("type_field", "event_type")))
        title = item.get(str(event_mapping.get("title_field", "title")))
        if not identity or not event_type or not title:
            continue
        metadata = dict(item.get(str(event_mapping.get("metadata_field", "metadata"))) or {})
        metadata["source_event_identity"] = str(identity)
        await conn.execute(
            """
            INSERT INTO project_event (
                project_id, event_type, occurred_at, title, summary,
                source_record_id, significance, metadata
            )
            SELECT
                %(project_id)s, %(event_type)s, %(occurred_at)s, %(title)s, %(summary)s,
                %(source_record_id)s, %(significance)s, %(metadata)s::jsonb
            WHERE NOT EXISTS (
                SELECT 1 FROM project_event
                WHERE project_id = %(project_id)s
                  AND source_record_id = %(source_record_id)s
                  AND metadata ->> 'source_event_identity' = %(identity)s
            )
            """,
            {
                "project_id": project_id,
                "event_type": str(event_type),
                "occurred_at": item.get(str(event_mapping.get("occurred_at_field", "occurred_at"))),
                "title": str(title),
                "summary": item.get(str(event_mapping.get("summary_field", "summary"))),
                "source_record_id": source_record_id,
                "significance": significance,
                "metadata": json.dumps(metadata, separators=(",", ":")),
                "identity": str(identity),
            },
        )


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
        SELECT p.id, psr.relationship_type
        FROM project p
        JOIN project_source_record psr ON psr.project_id = p.id
        WHERE psr.source_record_id = %s
        LIMIT 1
        """,
        (source_record_id,),
    )
    linked = await cursor.fetchone()
    anchor = (
        await _anchored_project(conn, record=record, mapping=mapping)
        if _configured_record_link(record, mapping) is not None
        else None
    )
    if linked is not None and anchor is not None and str(linked["id"]) != anchor[0]:
        raise RuntimeError(
            "Configured project anchor conflicts with an existing source-record link: "
            f"{record.source_key}/{record.external_id}"
        )
    created = linked is None and anchor is None
    anchored = anchor is not None or (
        linked is not None and linked["relationship_type"] != "evidence_for"
    )

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
                    record.location_accuracy.value
                    if record.location_accuracy
                    else "approximate_area"
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
        if anchor is not None:
            project_id, relationship_type, confidence, evidence = anchor
            await conn.execute(
                """
                INSERT INTO project_source_record (
                    project_id, source_record_id, relationship_type, confidence, evidence
                ) VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (project_id, source_record_id, relationship_type) DO UPDATE SET
                    confidence = EXCLUDED.confidence,
                    evidence = EXCLUDED.evidence
                """,
                (
                    project_id,
                    source_record_id,
                    relationship_type,
                    confidence,
                    json.dumps(evidence, separators=(",", ":")),
                ),
            )
        else:
            project_id = str(linked["id"])
        await conn.execute(
            """
            UPDATE project p SET
                canonical_name = CASE WHEN %(anchored)s THEN p.canonical_name ELSE %(name)s END,
                primary_geometry = COALESCE(p.primary_geometry, sr.geometry),
                last_activity_at = GREATEST(
                    COALESCE(p.last_activity_at, '-infinity'::timestamptz),
                    COALESCE(sr.source_updated_at, sr.fetched_at)
                ),
                updated_at = now()
            FROM source_record sr
            WHERE p.id = %(project_id)s AND sr.id = %(source_record_id)s
            """,
            {
                "project_id": project_id,
                "source_record_id": source_record_id,
                "name": str(name),
                "anchored": anchored,
            },
        )
        await conn.execute(
            """
            INSERT INTO project_location (
                project_id, geometry, geometry_method, geometry_source,
                location_accuracy, is_primary
            )
            SELECT
                %(project_id)s, sr.geometry, 'source_coordinate', %(geometry_source)s,
                %(location_accuracy)s::location_accuracy, true
            FROM source_record sr
            WHERE sr.id = %(source_record_id)s
              AND sr.geometry IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM project_location
                  WHERE project_id = %(project_id)s AND is_primary
              )
            """,
            {
                "project_id": project_id,
                "source_record_id": source_record_id,
                "geometry_source": record.geometry_source or record.source_key,
                "location_accuracy": (
                    record.location_accuracy.value
                    if record.location_accuracy
                    else "approximate_area"
                ),
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

    await _insert_mapped_events(
        conn,
        project_id=project_id,
        source_record_id=source_record_id,
        record=record,
        mapping=mapping,
    )

    return ProjectMaterialization(
        project_id=project_id,
        created=created,
        status_changed=status_changed,
    )
