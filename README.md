# NS Trackstar

NS Trackstar is a Napa–Solano local intelligence map that turns fragmented public records into evolving, geographically grounded project timelines.

## Core idea

Government sources → normalized source records → assertions + typed relationships → canonical projects → events/timelines → map + feed.

## What works now

- PostGIS canonical schema
- source run + source health model
- reusable collector interface
- shared ArcGIS FeatureServer collector
- City of Napa Public Works CIP + Water CIP through the same ArcGIS adapter
- CivicClerk public API adapter for Vallejo meetings + structured agenda items
- reusable eTRAKiT adapter with ASP.NET form-state discovery and direct public record parsing
- source-record persistence + semantic change snapshots
- config-driven promotion of authoritative source records into canonical projects
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
8. Ingest Vallejo meetings/agendas: `ns-trackstar-ingest collect config/sources/vallejo.civicclerk.json --write`.
9. Smoke-test Napa eTRAKiT: `ns-trackstar-ingest collect config/smoke/napa-city.etrakit.json`.
10. Smoke-test Vallejo eTRAKiT: `ns-trackstar-ingest collect config/smoke/vallejo.etrakit.json`.
11. Start the API: `python -m ns_trackstar_api`.
12. Install/start the web app: `pnpm install && pnpm dev`.

The implementation source of truth lives in `docs/MASTER_SPEC.md`.
