BEGIN;

-- The two projects this app was started for.
--
-- Written from the research pass, in the words a person would use. Matched on the
-- agency's own name for each; a project that has not been collected gets no row.

INSERT INTO project_curated_content (
  project_id, headline, what_is_this, whats_happening, whats_happening_at,
  whats_next, why_care, written_by, evidence_urls, review_by
)
SELECT p.id, v.headline, v.what_is_this, v.whats_happening, v.happened_on,
       v.whats_next, v.why_care::jsonb, 'trackstar-editorial', v.evidence::jsonb, v.review_by
FROM (
  VALUES
    (
      'Costco',
      'Fairview at Northgate',
      'A bigger Costco and 245 homes are being built here.',
      'Costco is moving to a larger store on the old Northgate site in Vallejo, on about 51 acres. '
      || 'The plan also includes a tire centre, a gas station, four other retail buildings and 245 homes.',
      'Vallejo approved a change that raised the housing from 178 homes to 245 and removed one of the '
      || 'commercial buildings. Construction is underway.',
      DATE '2026-05-27',
      'Building work continues. The store has not opened yet and the city has not published an opening date.',
      '[{"label":"New homes","value":"245 homes"},
        {"label":"Store size","value":"About 153,000 sq ft"},
        {"label":"Site size","value":"About 51 acres"},
        {"label":"Also included","value":"Tire centre, gas station and 4 retail buildings"}]',
      '["https://www.vallejo.gov/our_city/departments_divisions/planning_development_services/community_development_projects",
        "https://ceqanet.opr.ca.gov/2018102007"]',
      DATE '2026-12-01'
    ),
    (
      'Scotts Valley',
      'Scotts Valley Casino and Tribal Housing',
      'A tribal casino and 24 homes are proposed on 160 acres in north Vallejo, and it is currently blocked.',
      'The Scotts Valley Band of Pomo Indians wants to build a casino and 24 homes on a 160-acre site near '
      || 'Columbus Parkway and Admiral Callaghan Lane. For that to happen the federal government has to put '
      || 'the land into trust for the tribe and separately agree the land can be used for gaming.',
      'On 30 July 2026 the Bureau of Indian Affairs reversed itself and ruled the land is not currently '
      || 'eligible for gaming. The tribe filed a federal lawsuit on 7 August 2026 challenging that decision.',
      DATE '2026-08-07',
      'The federal court case decides it. Until that is resolved the casino cannot move forward, and no '
      || 'construction date exists.',
      '[{"label":"Site size","value":"160 acres"},
        {"label":"Homes","value":"24 homes"},
        {"label":"Status","value":"Blocked pending a federal court case"},
        {"label":"Court case","value":"Federal docket 1:26-cv-02814"}]',
      '["https://ceqanet.opr.ca.gov/2024070295",
        "https://www.bia.gov/service/gaming-decisions"]',
      DATE '2026-11-01'
    )
) AS v(match_name, display_name, headline, what_is_this, whats_happening, happened_on,
       whats_next, why_care, evidence, review_by)
JOIN LATERAL (
  SELECT id FROM project
  WHERE canonical_name ILIKE '%' || v.match_name || '%'
  ORDER BY length(canonical_name)
  LIMIT 1
) p ON TRUE
ON CONFLICT (project_id) DO UPDATE SET
  headline           = EXCLUDED.headline,
  what_is_this       = EXCLUDED.what_is_this,
  whats_happening    = EXCLUDED.whats_happening,
  whats_happening_at = EXCLUDED.whats_happening_at,
  whats_next         = EXCLUDED.whats_next,
  why_care           = EXCLUDED.why_care,
  written_at         = now(),
  evidence_urls      = EXCLUDED.evidence_urls,
  review_by          = EXCLUDED.review_by;

COMMIT;
