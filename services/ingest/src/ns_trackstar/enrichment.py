from __future__ import annotations

import psycopg


async def _enrich_projects_from_parcel_source(
    conn: psycopg.AsyncConnection,
    *,
    source_key: str,
    jurisdiction: str,
    parcel_apn_fields: tuple[str, ...],
    allow_trailing_zero_suffix: bool = False,
) -> int:
    """Attach official parcel geometry to projects with matching APN assertions.

    APN assertions may be strings or arrays. The matcher extracts both Napa-style
    3-3-3 parcel numbers and Solano-style 4-3-3 parcel numbers without treating the
    punctuation as identity. Napa County's public layer commonly stores the same
    assessor parcel with a trailing ``-000`` suffix while planning records publish
    the 3-3-3 base APN, so that narrowly defined suffix is accepted for Napa only.
    Projects are only enriched when they do not already have primary geometry, so
    source geometry always wins over derived parcel shape.
    """

    parcel_apn_sql = "COALESCE(" + ", ".join(
        f"NULLIF(sr.normalized_payload ->> '{field}', '')" for field in parcel_apn_fields
    ) + ", '')"

    await conn.execute(
        f"""
        WITH raw_apn_values AS (
          SELECT DISTINCT
            a.project_id,
            a.value #>> '{{}}' AS apn_text
          FROM assertion a
          JOIN project p ON p.id = a.project_id
          WHERE a.field = 'apn'
            AND p.primary_geometry IS NULL
            AND jsonb_typeof(a.value) = 'string'

          UNION ALL

          SELECT DISTINCT
            a.project_id,
            value.apn_text
          FROM assertion a
          JOIN project p ON p.id = a.project_id
          CROSS JOIN LATERAL jsonb_array_elements_text(a.value) AS value(apn_text)
          WHERE a.field = 'apn'
            AND p.primary_geometry IS NULL
            AND jsonb_typeof(a.value) = 'array'
        ),
        normalized_apns AS (
          SELECT DISTINCT
            project_id,
            match[1] AS apn,
            regexp_replace(lower(match[1]), '[^0-9a-z]', '', 'g') AS normalized_apn
          FROM raw_apn_values
          CROSS JOIN LATERAL regexp_matches(
            apn_text,
            '([0-9]{{4}}[- ]?[0-9]{{3}}[- ]?[0-9]{{3}}|[0-9]{{3}}[- ]?[0-9]{{3}}[- ]?[0-9]{{3}})',
            'g'
          ) AS match
        ),
        parcel_records AS (
          SELECT
            sr.id AS source_record_id,
            sr.geometry,
            regexp_replace(lower({parcel_apn_sql}), '[^0-9a-z]', '', 'g') AS normalized_apn
          FROM source_record sr
          JOIN source s ON s.id = sr.source_id
          WHERE s.source_key = %(source_key)s
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
            ON (
              pr.normalized_apn = na.normalized_apn
              OR (
                %(allow_trailing_zero_suffix)s
                AND length(na.normalized_apn) = 9
                AND pr.normalized_apn = na.normalized_apn || '000'
              )
            )
           AND pr.normalized_apn <> ''
        )
        INSERT INTO project_parcel (
          project_id, apn, jurisdiction, parcel_geometry, source_record_id
        )
        SELECT
          project_id,
          apn,
          %(jurisdiction)s,
          ST_Multi(ST_CollectionExtract(ST_Force2D(geometry), 3)),
          source_record_id
        FROM matches
        WHERE NOT ST_IsEmpty(ST_CollectionExtract(ST_Force2D(geometry), 3))
        ON CONFLICT (project_id, apn) DO UPDATE SET
          jurisdiction = EXCLUDED.jurisdiction,
          parcel_geometry = EXCLUDED.parcel_geometry,
          source_record_id = EXCLUDED.source_record_id
        """,
        {
            "source_key": source_key,
            "jurisdiction": jurisdiction,
            "allow_trailing_zero_suffix": allow_trailing_zero_suffix,
        },
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
          WHERE pp.jurisdiction = %(jurisdiction)s
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
          %(source_key)s,
          'exact_parcel',
          0.99,
          true,
          jsonb_build_object(
            'matched_parcels', parcel_count,
            'method_note', 'Official project APN evidence matched to public county parcel geometry'
          )
        FROM updated
        ON CONFLICT DO NOTHING
        RETURNING project_id
        """,
        {"source_key": source_key, "jurisdiction": jurisdiction},
    )
    updated = await cursor.fetchall()
    return len(updated)


async def enrich_napa_projects_from_parcels(conn: psycopg.AsyncConnection) -> int:
    return await _enrich_projects_from_parcel_source(
        conn,
        source_key="napa-county.parcels",
        jurisdiction="Napa County",
        parcel_apn_fields=("asmtwithdash", "asmt"),
        allow_trailing_zero_suffix=True,
    )


async def enrich_solano_projects_from_parcels(conn: psycopg.AsyncConnection) -> int:
    return await _enrich_projects_from_parcel_source(
        conn,
        source_key="solano-county.parcels",
        jurisdiction="Solano County",
        parcel_apn_fields=("parcelid", "lowparceli"),
    )


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


async def enrich_one_lake_relationships(conn: psycopg.AsyncConnection) -> int:
    """Create the official One Lake alias and its typed Vanden/Canon relationship.

    The City Council goals report explicitly coordinates the Vanden/Canon work with
    the One Lake developer. This is a relationship, not an identity merge.
    """

    await conn.execute(
        """
        WITH master AS (
          SELECT p.id AS project_id, sr.id AS source_record_id
          FROM source s
          JOIN source_record sr ON sr.source_id = s.id
          JOIN project_source_record psr ON psr.source_record_id = sr.id
          JOIN project p ON p.id = psr.project_id
          WHERE s.source_key = 'fairfield.one-lake-council-goals'
            AND sr.external_id = 'one-lake-vanden-canon-2025-q3'
          ORDER BY p.created_at
          LIMIT 1
        )
        INSERT INTO project_alias (project_id, alias, alias_type, source_record_id)
        SELECT project_id, 'Canon Station', 'official_development_alias', source_record_id
        FROM master
        ON CONFLICT (project_id, alias) DO UPDATE SET
          alias_type = EXCLUDED.alias_type,
          source_record_id = EXCLUDED.source_record_id
        """
    )

    cursor = await conn.execute(
        """
        WITH master AS (
          SELECT p.id AS project_id, sr.id AS source_record_id
          FROM source s
          JOIN source_record sr ON sr.source_id = s.id
          JOIN project_source_record psr ON psr.source_record_id = sr.id
          JOIN project p ON p.id = psr.project_id
          WHERE s.source_key = 'fairfield.one-lake-council-goals'
            AND sr.external_id = 'one-lake-vanden-canon-2025-q3'
          ORDER BY p.created_at
          LIMIT 1
        ),
        infrastructure AS (
          SELECT p.id AS project_id
          FROM source s
          JOIN source_record sr ON sr.source_id = s.id
          JOIN project_source_record psr ON psr.source_record_id = sr.id
          JOIN project p ON p.id = psr.project_id
          WHERE s.source_key = 'fairfield.vanden-canon-overcrossing'
            AND sr.external_id = 'vanden-canon-overcrossing-2025-q3'
          ORDER BY p.created_at
          LIMIT 1
        )
        INSERT INTO project_relationship (
          from_project_id, to_project_id, relationship_type,
          confidence, source_record_id, evidence
        )
        SELECT
          master.project_id,
          infrastructure.project_id,
          'related_infrastructure',
          1,
          master.source_record_id,
          jsonb_build_object(
            'signal', 'Fairfield Council Goals directs coordination with the One Lake developer on Vanden Road widening and grade separation',
            'source', 'Council Goals FY 2023-25 (Mar-25) Report'
          )
        FROM master CROSS JOIN infrastructure
        WHERE master.project_id <> infrastructure.project_id
        ON CONFLICT (from_project_id, to_project_id, relationship_type) DO UPDATE SET
          confidence = EXCLUDED.confidence,
          source_record_id = EXCLUDED.source_record_id,
          evidence = EXCLUDED.evidence,
          updated_at = now()
        RETURNING id
        """
    )
    relationships = await cursor.fetchall()
    return len(relationships)


# Official city-boundary layers, and the field on each that carries the city name.
# Stamping a jurisdiction is a spatial derivation, never a direct agency claim, so it
# is recorded as an inferred assertion with the layer that produced it.
JURISDICTION_BOUNDARY_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("napa-county.city-boundaries", "city", "Napa County"),
    ("solano-county.city-boundaries", "NAME", "Solano County"),
)

# Address points and street centrelines that can place a record precisely.
ADDRESS_POINT_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("napa-county.addresses", ("address",)),
)


def normalize_address(value: str) -> str:
    """Reduce an address to a comparable key.

    Agencies write the same address as "1025 Kaiser Rd", "1025 KAISER ROAD" and
    "1025  Kaiser Rd.". Punctuation, case, runs of whitespace and the common street
    type abbreviations are all noise. Directionals are *not* normalized away, because
    North and South Main Street are different places.
    """

    text = " ".join(str(value or "").lower().replace(".", " ").replace(",", " ").split())
    if not text:
        return ""
    expansions = {
        "st": "street", "str": "street", "rd": "road", "dr": "drive", "ave": "avenue",
        "av": "avenue", "blvd": "boulevard", "ln": "lane", "ct": "court", "cir": "circle",
        "pl": "place", "pkwy": "parkway", "pky": "parkway", "hwy": "highway",
        "ter": "terrace", "trl": "trail", "way": "way",
    }
    words = [expansions.get(word, word) for word in text.split()]
    return " ".join(words)


async def enrich_project_jurisdictions(conn: psycopg.AsyncConnection) -> int:
    """Record which incorporated city, if any, each mapped project falls inside.

    A project whose geometry lands in no city polygon is unincorporated county land,
    which is a real answer rather than a missing one, so it is stamped too.
    """

    stamped = 0
    for source_key, name_field, county in JURISDICTION_BOUNDARY_SOURCES:
        cursor = await conn.execute(
            f"""
            WITH boundaries AS (
              SELECT
                sr.normalized_payload ->> '{name_field}' AS city,
                sr.geometry
              FROM source_record sr
              JOIN source s ON s.id = sr.source_id
              WHERE s.source_key = %(source_key)s
                AND sr.geometry IS NOT NULL
                AND NULLIF(sr.normalized_payload ->> '{name_field}', '') IS NOT NULL
            ),
            county_extent AS (
              SELECT ST_UnaryUnion(ST_Collect(geometry)) AS geometry FROM boundaries
            ),
            candidates AS (
              SELECT
                p.id AS project_id,
                (
                  SELECT b.city FROM boundaries b
                  WHERE ST_Intersects(b.geometry, p.primary_geometry)
                  ORDER BY ST_Area(ST_Intersection(b.geometry, p.primary_geometry)) DESC
                  LIMIT 1
                ) AS city
              FROM project p, county_extent
              WHERE p.primary_geometry IS NOT NULL
                AND ST_Intersects(
                  ST_Expand(county_extent.geometry, 0.15), p.primary_geometry
                )
            ),
            resolved AS (
              SELECT
                project_id,
                COALESCE(city, %(unincorporated)s) AS jurisdiction
              FROM candidates
            ),
            changed AS (
              SELECT r.project_id, r.jurisdiction
              FROM resolved r
              WHERE NOT EXISTS (
                SELECT 1 FROM assertion a
                WHERE a.project_id = r.project_id
                  AND a.field = 'jurisdiction'
                  AND a.value #>> '{{}}' = r.jurisdiction
              )
            )
            INSERT INTO assertion (
              project_id, field, value, source_id, source_url, authority_type,
              confidence, direct, inferred, metadata
            )
            SELECT
              changed.project_id,
              'jurisdiction',
              to_jsonb(changed.jurisdiction),
              s.id,
              s.base_url,
              'derived_spatial',
              0.95,
              false,
              true,
              jsonb_build_object(
                'method', 'point_in_polygon',
                'boundary_source', %(source_key)s,
                'county', %(county)s
              )
            FROM changed
            JOIN source s ON s.source_key = %(source_key)s
            RETURNING project_id
            """,
            {
                "source_key": source_key,
                "county": county,
                "unincorporated": f"Unincorporated {county}",
            },
        )
        stamped += len(await cursor.fetchall())
    return stamped


async def enrich_projects_from_address_points(conn: psycopg.AsyncConnection) -> int:
    """Place location-pending projects on an official address point.

    Only an exact normalized-address match is used. A near match would put a pin on
    the wrong building, which is worse than leaving the project unmapped.
    """

    placed = 0
    for source_key, address_fields in ADDRESS_POINT_SOURCES:
        address_sql = "COALESCE(" + ", ".join(
            f"NULLIF(sr.normalized_payload ->> '{field}', '')" for field in address_fields
        ) + ", '')"
        cursor = await conn.execute(
            f"""
            WITH project_addresses AS (
              SELECT DISTINCT ON (a.project_id)
                a.project_id,
                ns_trackstar_normalize_address(a.value #>> '{{}}') AS address_key
              FROM assertion a
              JOIN project p ON p.id = a.project_id
              WHERE a.field = 'address'
                AND jsonb_typeof(a.value) = 'string'
                AND p.primary_geometry IS NULL
              ORDER BY a.project_id, a.observed_at DESC
            ),
            address_points AS (
              SELECT
                ns_trackstar_normalize_address({address_sql}) AS address_key,
                sr.geometry,
                COUNT(*) OVER (
                  PARTITION BY ns_trackstar_normalize_address({address_sql})
                ) AS duplicates
              FROM source_record sr
              JOIN source s ON s.id = sr.source_id
              WHERE s.source_key = %(source_key)s
                AND sr.geometry IS NOT NULL
            ),
            matches AS (
              SELECT DISTINCT ON (pa.project_id)
                pa.project_id,
                ap.geometry,
                pa.address_key
              FROM project_addresses pa
              JOIN address_points ap ON ap.address_key = pa.address_key
              WHERE pa.address_key <> ''
                -- One address written twice in the layer is still one place; the same
                -- key on genuinely different points is ambiguous and is left alone.
                AND ap.duplicates = 1
            ),
            updated AS (
              UPDATE project p
              SET primary_geometry = matches.geometry, updated_at = now()
              FROM matches
              WHERE p.id = matches.project_id AND p.primary_geometry IS NULL
              RETURNING p.id, p.primary_geometry, matches.address_key
            )
            INSERT INTO project_location (
              project_id, geometry, geometry_method, geometry_source,
              location_accuracy, geometry_confidence, is_primary, metadata
            )
            SELECT
              id,
              primary_geometry,
              'address_point_match',
              %(source_key)s,
              'exact_address',
              0.97,
              true,
              jsonb_build_object(
                'matched_address_key', address_key,
                'method_note',
                  'Official project address matched one unique public address point'
              )
            FROM updated
            ON CONFLICT DO NOTHING
            RETURNING project_id
            """,
            {"source_key": source_key},
        )
        placed += len(await cursor.fetchall())
    return placed
