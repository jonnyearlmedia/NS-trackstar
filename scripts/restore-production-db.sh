#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/backup.dump" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
BACKUP_PATH="$1"
POSTGRES_DB="${POSTGRES_DB:-nstrackstar}"
POSTGRES_USER="${POSTGRES_USER:-nstrackstar}"
RESTORE_DATABASE="${RESTORE_DATABASE:-nstrackstar_restore}"

if [[ ! -s "$BACKUP_PATH" ]]; then
  echo "Backup not found or empty: $BACKUP_PATH" >&2
  exit 1
fi

if [[ -f "$BACKUP_PATH.sha256" ]]; then
  (cd "$(dirname "$BACKUP_PATH")" && sha256sum -c "$(basename "$BACKUP_PATH").sha256")
fi

if [[ "$RESTORE_DATABASE" == "$POSTGRES_DB" && "${ALLOW_OVERWRITE_PRIMARY:-0}" != "1" ]]; then
  echo "Refusing to overwrite primary database '$POSTGRES_DB'. Set ALLOW_OVERWRITE_PRIMARY=1 only for an intentional disaster recovery restore." >&2
  exit 1
fi

compose=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  compose+=(--env-file "$ENV_FILE")
fi

"${compose[@]}" exec -T db dropdb --username "$POSTGRES_USER" --if-exists "$RESTORE_DATABASE"
"${compose[@]}" exec -T db createdb --username "$POSTGRES_USER" "$RESTORE_DATABASE"
cat "$BACKUP_PATH" | "${compose[@]}" exec -T db \
  pg_restore \
    --username "$POSTGRES_USER" \
    --dbname "$RESTORE_DATABASE" \
    --no-owner \
    --no-acl \
    --exit-on-error

"${compose[@]}" exec -T db psql --username "$POSTGRES_USER" --dbname "$RESTORE_DATABASE" --command "SELECT PostGIS_Version();"
echo "Restore verification succeeded in database: $RESTORE_DATABASE"
