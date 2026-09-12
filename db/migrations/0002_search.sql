BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX project_name_trgm_idx
ON project USING gin (canonical_name gin_trgm_ops);

CREATE INDEX project_alias_text_trgm_idx
ON project_alias USING gin ((alias::text) gin_trgm_ops);

CREATE INDEX assertion_search_value_trgm_idx
ON assertion USING gin ((value #>> '{}') gin_trgm_ops)
WHERE jsonb_typeof(value) = 'string'
  AND field IN (
    'address', 'apn', 'business_name', 'description', 'location_description',
    'owner_applicant', 'permit_number', 'planning_case', 'project_number', 'road'
  );

COMMIT;
