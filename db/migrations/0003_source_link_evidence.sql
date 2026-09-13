BEGIN;

ALTER TABLE project_source_record
ADD COLUMN evidence jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMIT;
