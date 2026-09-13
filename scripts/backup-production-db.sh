#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
POSTGRES_DB="${POSTGRES_DB:-nstrackstar}"
POSTGRES_USER="${POSTGRES_USER:-nstrackstar}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="${BACKUP_PATH:-$BACKUP_DIR/nstrackstar-$TIMESTAMP.dump}"

mkdir -p "$(dirname "$BACKUP_PATH")"

compose=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  compose+=(--env-file "$ENV_FILE")
fi

"${compose[@]}" exec -T db \
  pg_dump \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --format custom \
    --compress 9 \
    --no-owner \
    --no-acl \
  > "$BACKUP_PATH"

if [[ ! -s "$BACKUP_PATH" ]]; then
  echo "Backup is empty: $BACKUP_PATH" >&2
  exit 1
fi

sha256sum "$BACKUP_PATH" > "$BACKUP_PATH.sha256"
echo "$BACKUP_PATH"
