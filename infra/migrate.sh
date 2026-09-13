#!/bin/sh
set -eu

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
database="${POSTGRES_DB:-nstrackstar}"
user="${POSTGRES_USER:-nstrackstar}"
host="${POSTGRES_HOST:-db}"

psql_base="psql --host=$host --username=$user --dbname=$database --no-password --set=ON_ERROR_STOP=1"

$psql_base <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migration (
  filename text PRIMARY KEY,
  checksum text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

for migration in /migrations/*.sql; do
  filename=$(basename "$migration")
  checksum=$(sha256sum "$migration" | cut -d ' ' -f 1)
  applied_checksum=$($psql_base --tuples-only --no-align \
    --command="SELECT checksum FROM schema_migration WHERE filename = '$filename'")
  if [ "$applied_checksum" = "$checksum" ]; then
    echo "migration already applied: $filename"
    continue
  fi
  if [ -n "$applied_checksum" ]; then
    echo "migration changed after it was applied: $filename" >&2
    exit 1
  fi

  echo "applying migration: $filename"
  $psql_base --file="$migration"
  $psql_base \
    --command="INSERT INTO schema_migration (filename, checksum) VALUES ('$filename', '$checksum')"
done
