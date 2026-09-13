BEGIN;

-- Written answers for the projects people actually search for.
--
-- Everything else in this database is evidence: what an agency published, kept in the
-- agency's words. That is the right default and it is why the Costco card currently
-- opens with "153k sq. ft. Costco, 4 retail pads, 178 small-lot SFDs" and the casino
-- card opens with "A environmental review at Columbus Parkway". Both are faithful to
-- their source and neither answers the question a resident asked.
--
-- Composition from evidence gets close and cannot close the gap, for two reasons this
-- pair demonstrates. It cannot know that "SFD" means house. And it cannot know that the
-- home count in the tracker, 178, was superseded in May 2026 by a city approval for
-- 245 - a composer reads the field it has, so the flagship card has been showing a
-- number that is four months stale and looks perfectly confident doing it.
--
-- So this table holds editorial text, kept deliberately separate from evidence rather
-- than mixed into assertions, because a sentence a person wrote and a sentence an
-- agency published are different kinds of claim and the difference must survive in the
-- database. Every row carries who wrote it, when, and the evidence it rests on, so a
-- curated claim can be checked rather than trusted.

CREATE TABLE project_curated_content (
  project_id          UUID PRIMARY KEY REFERENCES project(id) ON DELETE CASCADE,

  -- One sentence, plain, no jargon. This is the first thing a person reads.
  headline            TEXT NOT NULL,
  what_is_this        TEXT,
  whats_happening     TEXT,
  -- The date the thing in whats_happening actually happened, which is not the date we
  -- observed it. A 2021 filing under a present-tense heading is how this app currently
  -- implies activity that is four years old.
  whats_happening_at  DATE,
  whats_next          TEXT,
  -- [{"label": "New homes", "value": "245 homes"}] - ordered, already human-readable.
  why_care            JSONB NOT NULL DEFAULT '[]'::jsonb,

  -- Provenance for the editorial claim itself.
  written_by          TEXT NOT NULL,
  written_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  evidence_urls       JSONB NOT NULL DEFAULT '[]'::jsonb,
  -- Set when the curated text should stop being trusted without a re-read, for a
  -- project whose situation is actively moving.
  review_by           DATE,

  CONSTRAINT project_curated_headline_is_a_sentence
    CHECK (length(btrim(headline)) BETWEEN 10 AND 400),
  -- An editorial claim with nothing behind it is the failure mode this table would
  -- otherwise introduce, so it is not permitted.
  CONSTRAINT project_curated_needs_evidence
    CHECK (jsonb_array_length(evidence_urls) > 0)
);

CREATE INDEX project_curated_review_idx
  ON project_curated_content (review_by)
  WHERE review_by IS NOT NULL;

COMMIT;
