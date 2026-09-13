BEGIN;

-- The four images that actually resolve, attached to the projects they belong to.
--
-- These are seeded as a migration rather than loaded by a script because the database
-- lives on a host the build cannot reach, and a picture that only exists on somebody's
-- laptop is not a feature. Each row is matched to a project by the agency's own name
-- for it; a project that has not been collected yet simply gets no row, and re-running
-- is harmless.
--
-- Nothing here is marked cleared. Every one is an agency's own photograph on the
-- agency's own server. Published is not licensed. `reference_only` permits pointing a
-- reader at the agency's copy with attribution - what any publication does when it
-- embeds an official photo - and forbids copying it onto our storage. The schema
-- enforces that rather than trusting it.

INSERT INTO project_image (
  project_id, source_url, asset_url, image_type, caption, publisher, attribution,
  is_official, rights_status, asset_resolution_status, is_hero, hero_selected_at,
  sort_order, retrieved_at, last_verified_at
)
SELECT
  p.id, v.source_url, v.asset_url, v.image_type, v.caption, v.publisher, v.publisher,
  TRUE, 'reference_only', 'resolved', v.is_hero,
  CASE WHEN v.is_hero THEN now() END,
  v.sort_order, now(), now()
FROM (
  VALUES
    ('Harvest Park',
     'https://www.cityofnapa.org/1392/Harvest-Park-Project',
     'https://www.cityofnapa.org/ImageRepository/Document?documentId=15871',
     'HERO', 'Current site of the future Harvest Park', 'City of Napa', TRUE, 1),
    ('Montebello Vista',
     'https://www.suisun.com/Departments/Parks-Recreation/Upcoming-Park-Projects',
     'https://www.suisun.com/files/assets/suisuncity/v/1/dji_20260521152411_0069_d.jpg',
     'HERO', 'Aerial view of construction progress, May 2026', 'City of Suisun City', TRUE, 1),
    ('Montebello Vista',
     'https://www.suisun.com/Departments/Parks-Recreation/Upcoming-Park-Projects',
     'https://www.suisun.com/files/assets/suisuncity/v/1/dji_20260521153238_0082_d.jpg',
     'CURRENT', 'Second aerial view during earthwork, May 2026', 'City of Suisun City', FALSE, 2),
    ('Montebello Vista',
     'https://www.suisun.com/Departments/Parks-Recreation/Upcoming-Park-Projects',
     'https://www.suisun.com/files/assets/suisuncity/v/1/phasing-plan.jpg?h=3300&w=5100',
     'SITE', 'The city''s phasing plan for the park', 'City of Suisun City', FALSE, 3)
) AS v(match_name, source_url, asset_url, image_type, caption, publisher, is_hero, sort_order)
JOIN LATERAL (
  SELECT id FROM project
  WHERE canonical_name ILIKE '%' || v.match_name || '%'
  ORDER BY length(canonical_name)
  LIMIT 1
) p ON TRUE
ON CONFLICT (project_id, asset_url) WHERE asset_url IS NOT NULL DO NOTHING;

-- Fairfield's five resolved URLs are real and unreachable: www.fairfield.ca.gov answers
-- 403 from Akamai to every automated client, browser user agent included. Recording
-- them as resolved would put five broken images in front of a resident, so they are
-- recorded as what they are - a known page, an unresolved asset - which also stops the
-- next person resolving them a second time.
INSERT INTO project_image (
  project_id, source_url, asset_url, image_type, caption, publisher, attribution,
  is_official, rights_status, asset_resolution_status, sort_order, last_verified_at,
  why_useful
)
SELECT
  p.id,
  'https://www.fairfield.ca.gov/government/city-departments/public-works',
  NULL, 'HERO',
  NULL, 'City of Fairfield', 'City of Fairfield', TRUE,
  'reference_only', 'unresolved', 1, now(),
  'The city publishes construction progress photography, a completion layout and '
  || 'corridor context for this corridor. Five exact asset URLs are known and all five '
  || 'answer 403 to automated clients, so they need a route that is not this one.'
FROM project p
WHERE p.canonical_name ILIKE '%West Texas%'
ORDER BY length(p.canonical_name)
LIMIT 1
ON CONFLICT (project_id, source_url, image_type) WHERE asset_url IS NULL DO NOTHING;

COMMIT;
