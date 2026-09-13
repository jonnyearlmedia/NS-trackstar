BEGIN;

-- Derive images from what the collectors already bring back.
--
-- The first pass at this hand-listed four image URLs from a research report, and three
-- of the four had no project to attach to: the report named projects Trackstar does not
-- collect. A hand-kept list of pictures for projects we do not hold is not a feature,
-- it is a second inventory to maintain.
--
-- This instead reads the `image_url` assertion, which any source can now supply, and
-- attaches it to the project that assertion already belongs to. It cannot attach an
-- image to a project that does not exist, and it cannot drift from the project list,
-- because it is derived from it.
--
-- Two agencies supply one today. Vacaville and Fairfield both run EasyCIP, which
-- publishes a photograph per capital project. Both carry the URL inside an HTML
-- <img src="..."> fragment rather than as a bare URL, so it is extracted rather than
-- stored as written.
--
-- Nothing here is cleared. These are agencies' own photographs on their own hosting.
-- `reference_only` permits pointing a reader at the agency's copy with attribution and
-- forbids copying it to our storage; the schema enforces that rather than trusting it.

INSERT INTO project_image (
  project_id, source_url, asset_url, image_type, publisher, attribution,
  is_official, rights_status, asset_resolution_status, is_hero, hero_selected_at,
  sort_order, retrieved_at, last_verified_at, why_useful
)
SELECT DISTINCT ON (a.project_id)
  a.project_id,
  COALESCE(a.source_url, sr.canonical_url, 'https://' || s.source_key),
  extracted.url,
  'HERO',
  s.name,
  s.name,
  TRUE,
  'reference_only',
  'resolved',
  TRUE,
  now(),
  1,
  a.observed_at,
  now(),
  'Published by the agency on its own capital-project record.'
FROM assertion a
JOIN source s ON s.id = a.source_id
LEFT JOIN source_record sr ON sr.id = a.source_record_id
CROSS JOIN LATERAL (
  SELECT COALESCE(
    -- The value is usually an <img src="..."> fragment; occasionally a bare URL.
    (regexp_match(a.value, 'src="(https?://[^"]+)"'))[1],
    CASE WHEN a.value ~ '^https?://' THEN a.value END
  ) AS url
) AS extracted
WHERE a.field = 'image_url'
  AND extracted.url IS NOT NULL
  -- A project already carrying a hero keeps it; this never overwrites a chosen image.
  AND NOT EXISTS (
    SELECT 1 FROM project_image existing
    WHERE existing.project_id = a.project_id AND existing.is_hero
  )
ORDER BY a.project_id, a.observed_at DESC
ON CONFLICT (project_id, asset_url) WHERE asset_url IS NOT NULL DO NOTHING;

COMMIT;
