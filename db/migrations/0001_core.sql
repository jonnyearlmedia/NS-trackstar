BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE source_health_state AS ENUM (
  'healthy', 'delayed', 'degraded', 'broken', 'blocked', 'schema_changed', 'disabled'
);

CREATE TYPE location_accuracy AS ENUM (
  'exact_source_geometry', 'exact_parcel', 'exact_address', 'intersection',
  'street_segment', 'approximate_area', 'city_only'
);

CREATE TYPE project_relationship_type AS ENUM (
  'same_physical_project', 'parent_child', 'alias_of', 'supersedes',
  'related_infrastructure', 'permit_for', 'environmental_review_for',
  'litigation_about', 'business_within', 'spatial_overlap_only', 'adjacent_project'
);

CREATE TYPE match_state AS ENUM ('candidate', 'soft_link', 'confirmed', 'rejected');

CREATE TABLE source (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_key text NOT NULL UNIQUE,
  name text NOT NULL,
  source_family text NOT NULL,
  jurisdiction text,
  base_url text,
  authority_class text,
  poll_interval_minutes integer NOT NULL CHECK (poll_interval_minutes > 0),
  collector_type text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  success boolean,
  http_status integer,
  records_returned integer NOT NULL DEFAULT 0 CHECK (records_returned >= 0),
  records_changed integer NOT NULL DEFAULT 0 CHECK (records_changed >= 0),
  attachments_returned integer NOT NULL DEFAULT 0 CHECK (attachments_returned >= 0),
  response_latency_ms integer CHECK (response_latency_ms >= 0),
  schema_fingerprint text,
  parser_yield numeric CHECK (parser_yield IS NULL OR (parser_yield >= 0 AND parser_yield <= 1)),
  canary_ok boolean,
  error_type text,
  error_message text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX source_run_source_started_idx ON source_run(source_id, started_at DESC);

CREATE TABLE source_health (
  source_id uuid PRIMARY KEY REFERENCES source(id) ON DELETE CASCADE,
  last_attempt_at timestamptz,
  last_success_at timestamptz,
  last_successful_parse_at timestamptz,
  last_record_seen_at timestamptz,
  last_content_change_at timestamptz,
  last_http_status integer,
  response_latency_ms integer,
  records_returned integer,
  attachments_returned integer,
  consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
  schema_fingerprint text,
  parser_yield numeric CHECK (parser_yield IS NULL OR (parser_yield >= 0 AND parser_yield <= 1)),
  expected_poll_interval_minutes integer NOT NULL CHECK (expected_poll_interval_minutes > 0),
  health_state source_health_state NOT NULL DEFAULT 'delayed',
  health_reason text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_record (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  external_id text NOT NULL,
  canonical_url text,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  fetched_at timestamptz NOT NULL DEFAULT now(),
  raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  normalized_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  content_hash text NOT NULL,
  geometry geometry(Geometry, 4326),
  geometry_source text,
  location_accuracy location_accuracy,
  geometry_accuracy_meters numeric,
  geometry_confidence numeric CHECK (geometry_confidence IS NULL OR (geometry_confidence >= 0 AND geometry_confidence <= 1)),
  UNIQUE(source_id, external_id)
);

CREATE INDEX source_record_source_updated_idx ON source_record(source_id, source_updated_at DESC NULLS LAST);
CREATE INDEX source_record_geometry_gix ON source_record USING gist(geometry);
CREATE INDEX source_record_payload_gin ON source_record USING gin(normalized_payload);

CREATE TABLE source_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_record_id uuid NOT NULL REFERENCES source_record(id) ON DELETE CASCADE,
  observed_at timestamptz NOT NULL DEFAULT now(),
  content_hash text NOT NULL,
  raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  normalized_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  geometry geometry(Geometry, 4326),
  UNIQUE(source_record_id, content_hash)
);

CREATE INDEX source_snapshot_record_observed_idx ON source_snapshot(source_record_id, observed_at DESC);

CREATE TABLE organization (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name citext NOT NULL,
  organization_type text,
  aliases text[] NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX organization_name_idx ON organization(canonical_name);

CREATE TABLE project (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name text NOT NULL,
  project_type text NOT NULL,
  primary_geometry geometry(Geometry, 4326),
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_activity_at timestamptz,
  importance_score numeric NOT NULL DEFAULT 0,
  summary_cache text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX project_geometry_gix ON project USING gist(primary_geometry);
CREATE INDEX project_last_activity_idx ON project(last_activity_at DESC NULLS LAST);

CREATE TABLE project_alias (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  alias citext NOT NULL,
  alias_type text,
  source_record_id uuid REFERENCES source_record(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, alias)
);

CREATE INDEX project_alias_alias_idx ON project_alias(alias);

CREATE TABLE project_relationship (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  to_project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  relationship_type project_relationship_type NOT NULL,
  confidence numeric NOT NULL DEFAULT 1 CHECK (confidence >= 0 AND confidence <= 1),
  source_record_id uuid REFERENCES source_record(id) ON DELETE SET NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (from_project_id <> to_project_id),
  UNIQUE(from_project_id, to_project_id, relationship_type)
);

CREATE INDEX project_relationship_from_idx ON project_relationship(from_project_id, relationship_type);
CREATE INDEX project_relationship_to_idx ON project_relationship(to_project_id, relationship_type);

CREATE TABLE project_location (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  geometry geometry(Geometry, 4326) NOT NULL,
  geometry_method text NOT NULL,
  geometry_source text NOT NULL,
  location_accuracy location_accuracy NOT NULL,
  geometry_accuracy_meters numeric,
  geometry_confidence numeric CHECK (geometry_confidence IS NULL OR (geometry_confidence >= 0 AND geometry_confidence <= 1)),
  is_primary boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX project_location_geometry_gix ON project_location USING gist(geometry);
CREATE UNIQUE INDEX project_location_one_primary_idx ON project_location(project_id) WHERE is_primary;

CREATE TABLE project_parcel (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  apn text NOT NULL,
  jurisdiction text,
  parcel_geometry geometry(MultiPolygon, 4326),
  source_record_id uuid REFERENCES source_record(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, apn)
);

CREATE INDEX project_parcel_apn_idx ON project_parcel(apn);
CREATE INDEX project_parcel_geometry_gix ON project_parcel USING gist(parcel_geometry);

CREATE TABLE project_source_record (
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  source_record_id uuid NOT NULL REFERENCES source_record(id) ON DELETE CASCADE,
  relationship_type text NOT NULL DEFAULT 'evidence_for',
  confidence numeric NOT NULL DEFAULT 1 CHECK (confidence >= 0 AND confidence <= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(project_id, source_record_id, relationship_type)
);

CREATE TABLE document (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_record_id uuid REFERENCES source_record(id) ON DELETE SET NULL,
  canonical_url text NOT NULL,
  title text,
  mime_type text,
  etag text,
  last_modified text,
  sha256 text,
  extracted_text text,
  permanently_archived boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX document_sha_idx ON document(sha256) WHERE sha256 IS NOT NULL;

CREATE TABLE assertion (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  field text NOT NULL,
  value jsonb NOT NULL,
  source_id uuid NOT NULL REFERENCES source(id) ON DELETE RESTRICT,
  source_record_id uuid REFERENCES source_record(id) ON DELETE SET NULL,
  source_url text,
  source_published_at timestamptz,
  observed_at timestamptz NOT NULL DEFAULT now(),
  authority_type text NOT NULL,
  confidence numeric NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  direct boolean NOT NULL DEFAULT true,
  inferred boolean NOT NULL DEFAULT false,
  evidence_hash text,
  supersedes_assertion_id uuid REFERENCES assertion(id) ON DELETE SET NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX assertion_project_field_idx ON assertion(project_id, field, observed_at DESC);
CREATE INDEX assertion_source_record_idx ON assertion(source_record_id) WHERE source_record_id IS NOT NULL;

CREATE TABLE project_status_dimension (
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  dimension text NOT NULL,
  value text NOT NULL,
  effective_at timestamptz,
  assertion_id uuid REFERENCES assertion(id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(project_id, dimension)
);

CREATE TABLE project_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  event_type text NOT NULL,
  occurred_at timestamptz,
  observed_at timestamptz NOT NULL DEFAULT now(),
  title text NOT NULL,
  summary text,
  source_record_id uuid REFERENCES source_record(id) ON DELETE SET NULL,
  assertion_id uuid REFERENCES assertion(id) ON DELETE SET NULL,
  significance numeric NOT NULL DEFAULT 0.5 CHECK (significance >= 0 AND significance <= 1),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX project_event_project_time_idx ON project_event(project_id, COALESCE(occurred_at, observed_at) DESC);
CREATE INDEX project_event_time_idx ON project_event(COALESCE(occurred_at, observed_at) DESC);

CREATE TABLE entity_match_candidate (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  left_project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  right_project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  proposed_relationship project_relationship_type NOT NULL,
  state match_state NOT NULL DEFAULT 'candidate',
  score numeric NOT NULL CHECK (score >= 0 AND score <= 1),
  signals jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  CHECK (left_project_id <> right_project_id),
  UNIQUE(left_project_id, right_project_id, proposed_relationship)
);

CREATE INDEX entity_match_state_score_idx ON entity_match_candidate(state, score DESC);

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER source_set_updated_at BEFORE UPDATE ON source
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER organization_set_updated_at BEFORE UPDATE ON organization
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER project_set_updated_at BEFORE UPDATE ON project
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER project_relationship_set_updated_at BEFORE UPDATE ON project_relationship
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
