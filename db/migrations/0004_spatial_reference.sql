BEGIN;

-- Address normalization lives in one place so the Python matcher and the SQL join
-- can never drift apart. Agencies write the same address as "1025 Kaiser Rd",
-- "1025 KAISER ROAD" and "1025  Kaiser Rd."; punctuation, case, whitespace runs and
-- the common street-type abbreviations are all noise.
--
-- Directionals are deliberately NOT normalized away. North Main Street and South
-- Main Street are different places, and collapsing them would put pins on the wrong
-- side of town.
CREATE OR REPLACE FUNCTION ns_trackstar_normalize_address(value text)
RETURNS text AS $$
  SELECT COALESCE(
    (
      SELECT string_agg(
        CASE word
          WHEN 'st' THEN 'street'
          WHEN 'str' THEN 'street'
          WHEN 'rd' THEN 'road'
          WHEN 'dr' THEN 'drive'
          WHEN 'ave' THEN 'avenue'
          WHEN 'av' THEN 'avenue'
          WHEN 'blvd' THEN 'boulevard'
          WHEN 'ln' THEN 'lane'
          WHEN 'ct' THEN 'court'
          WHEN 'cir' THEN 'circle'
          WHEN 'pl' THEN 'place'
          WHEN 'pkwy' THEN 'parkway'
          WHEN 'pky' THEN 'parkway'
          WHEN 'hwy' THEN 'highway'
          WHEN 'ter' THEN 'terrace'
          WHEN 'trl' THEN 'trail'
          WHEN 'way' THEN 'way'
          ELSE word
        END,
        ' ' ORDER BY ordinality
      )
      FROM regexp_split_to_table(
        btrim(regexp_replace(lower(replace(replace(value, '.', ' '), ',', ' ')), '\s+', ' ', 'g')),
        ' '
      ) WITH ORDINALITY AS parts(word, ordinality)
      WHERE word <> ''
    ),
    ''
  );
$$ LANGUAGE sql IMMUTABLE;

-- Spatial reference layers are large and are joined on a normalized key rather than
-- scanned, so the key needs its own index on the address-point source records.
CREATE INDEX IF NOT EXISTS source_record_address_key_idx
  ON source_record (
    ns_trackstar_normalize_address(normalized_payload ->> 'address')
  )
  WHERE normalized_payload ? 'address';

-- A derived jurisdiction stamp is looked up per project on every consumer render.
CREATE INDEX IF NOT EXISTS assertion_jurisdiction_idx
  ON assertion (project_id)
  WHERE field = 'jurisdiction';

COMMIT;
