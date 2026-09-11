# NS Trackstar

NS Trackstar is a Napa–Solano local intelligence map that turns fragmented public records into evolving, geographically grounded project timelines.

## Core idea

Government sources → normalized source records → assertions + typed relationships → canonical projects → events/timelines → map + feed.

## Initial coverage

- American Canyon
- Vallejo
- Napa
- Fairfield
- Benicia
- Suisun City
- Napa County
- Solano County

## Phase 0 goals

- establish the canonical evidence/project model
- preserve field-level provenance
- model typed project relationships before merging
- support multidimensional project status
- track collector health and schema drift
- provide a PostGIS-ready local development stack
- create a Next.js web shell and Python ingestion service

## Local development

1. Copy `.env.example` to `.env`.
2. Start PostGIS with `docker compose up -d db`.
3. Apply `db/migrations/0001_core.sql` to the database.
4. Install Node dependencies with `pnpm install`.
5. Install the Python ingestion service with `uv sync --project services/ingest`.

The implementation source of truth lives in `docs/MASTER_SPEC.md`.
