from __future__ import annotations

import psycopg


async def enrich_napa_projects_from_parcels(conn: psycopg.AsyncConnection) -> int:
    """Attach authoritative Napa parcel geometry to projects with matching APN evidence.

    This is deliberately conservative: only projects without primary geometry are
    enriched, only APNs asserted by an existing project source record are used, and
    geometry comes from the official Napa County parcel layer already stored in
    source_record. Multi-parcel projects receive the union of every matched parcel.
    """

    await conn.execute(
        """
        WITH apn_values AS (
          SELECT DISTINCT
            a.project_id,
            CASE
              WHEN jsonb_typeof(a.value) = 'string' THEN a.value #>> '{}'
              ELSE NULL
            END AS apn
          FROM assertion a
          JOIN project p ON p.id = a.project_id
          WHERE a.field = 'apn'
            AND p.primary_geometry IS NULL
            AND jsonb_typeof(a.value) = 'string'

          UNION

          SELECT DISTINCT
            a.project_id,
            value.apn
          FROM assertion a
          JOIN project p ON p.id = a.project_id
          CROSS JOIN LATERAL jsonb_array_elements_text(a.value) AS value(apn)
          WHERE a.field = 'apn'
            AND p.primary_geometry IS NULL
            AND jsonb_typeof(a.value) = 'array'
        ),
        normalized_apns AS (
          SELECT
            project_id,
            apn,
            regexp_replace(lower(apn), '[^0-9a-z]', '', 'g') AS normalized_apn
          FROM apn_values
          WHERE apn IS NOT NULL AND btrim(apn) <> ''
        ),
        parcel_records AS (
          SELECT
            sr.id AS source_record_id,
            sr.geometry,
            regexp_replace(
              lower(COALESCE(
                NULLIF(sr.normalized_payload ->> 'asmtwithdash', ''),
                NULLIF(sr.normalized_payload ->> 'asmt', ''),
                ''
              )),
              '[^0-9a-z]', '', 'g'
            ) AS normalized_apn
          FROM source_record sr
          JOIN source s ON s.id = sr.source_id
          WHERE s.source_key = 'napa-county.parcels'
            AND sr.geometry IS NOT NULL
        ),
        matches AS (
          SELECT DISTINCT
            na.project_id,
            na.apn,
            pr.source_record_id,
            pr.geometry
          FROM normalized_apns na
          JOIN parcel_records pr
            ON pr.normalized_apn = na.normalized_apn
           AND pr.normalized_apn <> ''
        )
        INSERT INTO project_parcel (
          project_id, apn, jurisdiction, parcel_geometry, source_record_id
        )
        SELECT
          project_id,
          apn,
          'Napa County',
          ST_Multi(ST_CollectionExtract(ST_Force2D(geometry), 3)),
          source_record_id
        FROM matches
        WHERE NOT ST_IsEmpty(ST_CollectionExtract(ST_Force2D(geometry), 3))
        ON CONFLICT (project_id, apn) DO UPDATE SET
          parcel_geometry = EXCLUDED.parcel_geometry,
          source_record_id = EXCLUDED.source_record_id
        """
    )

    cursor = await conn.execute(
        """
        WITH footprints AS (
          SELECT
            pp.project_id,
            ST_UnaryUnion(ST_Collect(pp.parcel_geometry)) AS geometry,
            COUNT(*)::int AS parcel_count
          FROM project_parcel pp
          JOIN project p ON p.id = pp.project_id
          WHERE pp.jurisdiction = 'Napa County'
            AND p.primary_geometry IS NULL
          GROUP BY pp.project_id
        ),
        updated AS (
          UPDATE project p
          SET
            primary_geometry = footprints.geometry,
            updated_at = now()
          FROM footprints
          WHERE p.id = footprints.project_id
            AND p.primary_geometry IS NULL
          RETURNING p.id, p.primary_geometry, footprints.parcel_count
        )
        INSERT INTO project_location (
          project_id, geometry, geometry_method, geometry_source,
          location_accuracy, geometry_confidence, is_primary, metadata
        )
        SELECT
          id,
          primary_geometry,
          'apn_parcel_match',
          'napa-county.parcels',
          'exact_parcel',
          0.99,
          true,
          jsonb_build_object(
            'matched_parcels', parcel_count,
            'method_note', 'Official project APN matched to Napa County public parcel geometry'
          )
        FROM updated
        ON CONFLICT DO NOTHING
        RETURNING project_id
        """
    )
    updated = await cursor.fetchall()
    return len(updated)


async def enrich_sr37_sears_point_corridor(conn: psycopg.AsyncConnection) -> int:
    """Give the known SR-37 corridor project its truthful corridor-level geometry.

    SCH 2020070226 is the authoritative identity anchor. The line represents the
    published Sears Point-to-Mare Island route limits and is intentionally stored as
    ``street_segment`` rather than exact construction geometry.
    """

    corridor_geojson = (
        '{"type":"LineString","coordinates":'
        '[[-122.451,38.216],[-122.257,38.116]]}'
    )
    cursor = await conn.execute(
        """
        WITH target AS (
          SELECT DISTINCT p.id
          FROM project p
          JOIN assertion a ON a.project_id = p.id
          WHERE a.field = 'sch_number'
            AND a.value #>> '{}' = '2020070226'
        ),
        updated AS (
          UPDATE project p
          SET
            project_type = 'transportation_project',
            primary_geometry = COALESCE(
              p.primary_geometry,
              ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)
            ),
            updated_at = now()
          FROM target
          WHERE p.id = target.id
          RETURNING p.id, p.primary_geometry
        )
        INSERT INTO project_location (
          project_id, geometry, geometry_method, geometry_source,
          location_accuracy, geometry_confidence, is_primary, metadata
        )
        SELECT
          id,
          primary_geometry,
          'official_route_limits_approximation',
          'Caltrans District 4 SR-37 corridor limits',
          'street_segment',
          0.90,
          true,
          jsonb_build_object(
            'sch_number', '2020070226',
            'route', 'SR-37',
            'caltrans_ea', '04-1Q7600',
            'efis', '0418000329',
            'method_note', 'Corridor line follows published Sears Point-to-Mare Island project limits; it is not a surveyed construction footprint',
            'source_url', 'https://dot.ca.gov/caltrans-near-me/district-4/d4-projects/d4-37-corridor-projects/37-projects'
          )
        FROM updated
        WHERE NOT EXISTS (
          SELECT 1 FROM project_location pl
          WHERE pl.project_id = updated.id AND pl.is_primary
        )
        RETURNING project_id
        """,
        {"geometry": corridor_geojson},
    )
    locations = await cursor.fetchall()

    await conn.execute(
        """
        WITH target AS (
          SELECT DISTINCT a.project_id, a.source_record_id
          FROM assertion a
          WHERE a.field = 'sch_number'
            AND a.value #>> '{}' = '2020070226'
            AND a.source_record_id IS NOT NULL
        )
        INSERT INTO project_source_record (
          project_id, source_record_id, relationship_type, confidence, evidence
        )
        SELECT
          project_id,
          source_record_id,
          'environmental_review_for',
          1,
          jsonb_build_object('signal', 'SCH 2020070226 identifies the SR-37 Sears Point to Mare Island corridor project')
        FROM target
        ON CONFLICT (project_id, source_record_id, relationship_type) DO UPDATE SET
          confidence = EXCLUDED.confidence,
          evidence = EXCLUDED.evidence
        """
    )
    return len(locations)
