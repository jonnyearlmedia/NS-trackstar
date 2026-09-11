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

## What works now

- PostGIS canonical schema
- source run + source health model
- reusable collector interface
- ArcGIS FeatureServer collector
- config-driven collector registry
- real MapLibre + OpenFreeMap web map
- persistence path for source records and snapshots

## Local development

1. Copy `.env.example` to `.env`.
2. Start PostGIS with `docker compose up -d db`.
3. Apply `db/migrations/0001_core.sql` to the database.
4. Install Node dependencies with `pnpm install`.
5. Install the Python ingestion service with `pip install -e "services/ingest[dev]"`.
6. Dry-run a source: `ns-trackstar-ingest collect config/sources/napa-county.parcels.json`.
7. Persist it: `ns-trackstar-ingest collect config/sources/napa-county.parcels.json --write`.

The implementation source of truth lives in `docs/MASTER_SPEC.md`.
