# NS Trackstar

NS Trackstar is a Napa–Solano local intelligence map that turns fragmented public records into evolving, geographically grounded project timelines.

## Core idea

Government sources → normalized source records → assertions + typed relationships → canonical projects → events/timelines → map + feed.

## What works now

- PostGIS canonical schema
- source run + source health model
- reusable collector interface
- shared ArcGIS FeatureServer collector
- source-record persistence + semantic change snapshots
- config-driven promotion of authoritative source records into canonical projects
- City of Napa Public Works CIP project ingestion
- City of Napa Water CIP project ingestion through the same ArcGIS adapter
- read API for map projects, project detail, events and source health
- real MapLibre + OpenFreeMap web map
- selected project geometry glow + geometry-aware camera framing

## Local development

1. Copy `.env.example` to `.env`.
2. Start PostGIS with `docker compose up -d db`.
3. Apply `db/migrations/0001_core.sql` to the database.
4. Install the ingestion service: `pip install -e "services/ingest[dev]"`.
5. Install the API: `pip install -e "services/api[dev]"`.
6. Ingest Napa Public Works CIP: `ns-trackstar-ingest collect config/sources/napa-city.public-works-cip.json --write`.
7. Ingest Napa Water CIP: `ns-trackstar-ingest collect config/sources/napa-city.water-cip.json --write`.
8. Start the API: `python -m ns_trackstar_api`.
9. Install/start the web app: `pnpm install && pnpm dev`.

The implementation source of truth lives in `docs/MASTER_SPEC.md`.
