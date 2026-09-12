from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/admin/location-debug/{project_id}")
async def location_debug(project_id: UUID, request: Request) -> dict:
    assertions_cursor = await request.app.state.db.execute(
        """
        SELECT value
        FROM assertion
        WHERE project_id = %s AND field = 'apn'
        ORDER BY observed_at DESC
        """,
        (project_id,),
    )
    assertions = await assertions_cursor.fetchall()

    parcel_cursor = await request.app.state.db.execute(
        """
        WITH apns AS (
          SELECT DISTINCT regexp_replace(lower(value), '[^0-9a-z]', '', 'g') AS normalized_apn
          FROM (
            SELECT a.value #>> '{}' AS value
            FROM assertion a
            WHERE a.project_id = %(project_id)s
              AND a.field = 'apn'
              AND jsonb_typeof(a.value) = 'string'
            UNION ALL
            SELECT item.value
            FROM assertion a
            CROSS JOIN LATERAL jsonb_array_elements_text(a.value) AS item(value)
            WHERE a.project_id = %(project_id)s
              AND a.field = 'apn'
              AND jsonb_typeof(a.value) = 'array'
          ) values
        )
        SELECT
          sr.id,
          sr.normalized_payload ->> 'asmt' AS asmt,
          sr.normalized_payload ->> 'asmtwithdash' AS asmtwithdash,
          sr.normalized_payload ->> 'streetaddr' AS streetaddr,
          ST_GeometryType(sr.geometry) AS geometry_type,
          ST_IsValid(sr.geometry) AS geometry_valid,
          ST_AsText(ST_Centroid(ST_Transform(sr.geometry, 4326))) AS centroid
        FROM source_record sr
        JOIN source s ON s.id = sr.source_id
        CROSS JOIN apns
        WHERE s.source_key = 'napa-county.parcels'
          AND (
            regexp_replace(lower(COALESCE(sr.normalized_payload ->> 'asmtwithdash', '')), '[^0-9a-z]', '', 'g') = apns.normalized_apn
            OR regexp_replace(lower(COALESCE(sr.normalized_payload ->> 'asmt', '')), '[^0-9a-z]', '', 'g') = apns.normalized_apn
            OR regexp_replace(lower(COALESCE(sr.normalized_payload ->> 'asmtwithdash', '')), '[^0-9a-z]', '', 'g') = apns.normalized_apn || '000'
            OR regexp_replace(lower(COALESCE(sr.normalized_payload ->> 'asmt', '')), '[^0-9a-z]', '', 'g') = apns.normalized_apn || '000'
          )
        LIMIT 20
        """,
        {"project_id": project_id},
    )
    parcels = await parcel_cursor.fetchall()

    linked_cursor = await request.app.state.db.execute(
        """
        SELECT pp.apn, pp.jurisdiction, pp.source_record_id, ST_GeometryType(pp.parcel_geometry) AS geometry_type
        FROM project_parcel pp
        WHERE pp.project_id = %s
        ORDER BY pp.apn
        """,
        (project_id,),
    )
    linked = await linked_cursor.fetchall()

    return {
        "project_id": str(project_id),
        "apn_assertions": [row["value"] for row in assertions],
        "candidate_parcels": [
            {**row, "id": str(row["id"])}
            for row in parcels
        ],
        "linked_parcels": [
            {**row, "source_record_id": str(row["source_record_id"])}
            for row in linked
        ],
    }
