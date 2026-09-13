BEGIN;

-- Pictures, and the paperwork that has to come with them.
--
-- A project reads as real when a resident can see it. The constraint that shapes this
-- table is not storage, it is rights: a photograph on a city's website is published,
-- which is not the same as licensed for us to copy. So the asset and the basis for
-- using it are stored together, and nothing is cached without a recorded reason.
--
-- `rights_status` is deliberately not a boolean. "reference_only" means we may point a
-- reader at the agency's own copy with attribution, the way any publication embeds an
-- official photo; "cleared" means we hold a basis to host it ourselves, and that basis
-- must be in `rights_evidence_url`, because a bare "cleared" is an assertion nobody can
-- audit later.
CREATE TABLE project_image (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id                UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,

  -- Where a human can see this image in its own context. Always required: an image
  -- with no page behind it cannot be attributed or checked.
  source_url                TEXT NOT NULL,
  -- The binary itself. Null is a legitimate, meaningful state: it means "we know this
  -- project should have a hero and we know which page to get it from, and we have not
  -- resolved the file". That is a research queue entry, not an image.
  asset_url                 TEXT,
  -- Set only once we host a copy, which requires rights_status = 'cleared'.
  cached_asset_url          TEXT,

  source_name               TEXT,
  publisher                 TEXT,
  attribution               TEXT,
  is_official               BOOLEAN NOT NULL DEFAULT FALSE,

  image_type                TEXT NOT NULL
                            CHECK (image_type IN ('HERO','CURRENT','SITE','DESIGN','CONTEXT')),
  caption                   TEXT,
  why_useful                TEXT,
  pdf_page                  INTEGER,

  captured_at               TIMESTAMPTZ,
  published_at              TIMESTAMPTZ,
  retrieved_at              TIMESTAMPTZ,
  last_verified_at          TIMESTAMPTZ,

  rights_status             TEXT NOT NULL DEFAULT 'unreviewed'
                            CHECK (rights_status IN ('unreviewed','reference_only','cleared','refused')),
  rights_evidence_url       TEXT,
  asset_resolution_status   TEXT NOT NULL DEFAULT 'unresolved'
                            CHECK (asset_resolution_status IN ('unresolved','resolved','dead')),

  is_hero                   BOOLEAN NOT NULL DEFAULT FALSE,
  hero_selected_at          TIMESTAMPTZ,
  sort_order                INTEGER NOT NULL DEFAULT 100,
  content_hash              TEXT,
  supersedes_project_image_id UUID REFERENCES project_image(id) ON DELETE SET NULL,

  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- A row claiming to be a usable image has to actually carry one.
  CONSTRAINT project_image_resolved_has_asset
    CHECK (asset_resolution_status <> 'resolved' OR asset_url IS NOT NULL),
  -- We never hold our own copy without a recorded basis for holding it.
  CONSTRAINT project_image_cached_only_when_cleared
    CHECK (cached_asset_url IS NULL OR (rights_status = 'cleared' AND rights_evidence_url IS NOT NULL)),
  -- "Cleared" without evidence is the claim this table exists to prevent.
  CONSTRAINT project_image_cleared_needs_evidence
    CHECK (rights_status <> 'cleared' OR rights_evidence_url IS NOT NULL)
);

CREATE UNIQUE INDEX project_image_project_asset_idx
  ON project_image (project_id, asset_url)
  WHERE asset_url IS NOT NULL;

-- An unresolved row has no asset to key on, so without this a re-run stacks another
-- copy of the same research task. NULL is not equal to NULL, which means the index
-- above cannot see these at all - the exact case a re-run test caught before this
-- shipped.
CREATE UNIQUE INDEX project_image_unresolved_idx
  ON project_image (project_id, source_url, image_type)
  WHERE asset_url IS NULL;

-- The consumer read is "give me this project's showable images, best first".
CREATE INDEX project_image_display_idx
  ON project_image (project_id, is_hero DESC, sort_order, id)
  WHERE asset_resolution_status = 'resolved' AND rights_status IN ('reference_only','cleared');

-- One hero per project, enforced rather than hoped for.
CREATE UNIQUE INDEX project_image_single_hero_idx
  ON project_image (project_id)
  WHERE is_hero;

COMMIT;
