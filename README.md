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
- reusable official PDF project-tracker adapter with document hashing and parser canaries
- CEQAnet CSV ingestion grouped by SCH number with document timeline events
- source-record persistence + semantic change snapshots
- config-driven promotion and explicit typed source-record links into canonical projects
- read API for map projects, project detail, events and source health
- deterministic project/business/address/permit/case/APN/road search
- real MapLibre + OpenFreeMap web map
- selected project geometry glow, geometry-aware framing, timelines and source provenance

## Local development

1. Copy `.env.example` to `.env`.
2. Start PostGIS with `docker compose up -d db`.
3. Apply every `db/migrations/*.sql` file in filename order.
4. Install the ingestion service: `pip install -e "services/ingest[dev]"`.
5. Install the API: `pip install -e "services/api[dev]"`.
6. Ingest Napa Public Works CIP: `ns-trackstar-ingest collect config/sources/napa-city.public-works-cip.json --write`.
7. Ingest Napa Water CIP: `ns-trackstar-ingest collect config/sources/napa-city.water-cip.json --write`.
8. Ingest Vallejo meetings/agendas: `ns-trackstar-ingest collect config/sources/vallejo.civicclerk.json --write`.
9. Ingest Suisun's official Development Calendar: `ns-trackstar-ingest collect config/sources/suisun-city.development-calendar.json --write`.
10. Ingest City of Napa Legistar: `ns-trackstar-ingest collect config/sources/napa-city.legistar.json --write`.
11. Ingest Solano County Legistar: `ns-trackstar-ingest collect config/sources/solano-county.legistar.json --write`.
12. Ingest Napa/Solano CEQAnet: `ns-trackstar-ingest collect config/sources/california.ceqanet.napa-solano.json --write`.
13. Smoke-test Napa eTRAKiT: `ns-trackstar-ingest collect config/smoke/napa-city.etrakit.json`.
14. Smoke-test Vallejo eTRAKiT: `ns-trackstar-ingest collect config/smoke/vallejo.etrakit.json`.
15. Start the API: `python -m ns_trackstar_api`.
16. Install/start the web app: `pnpm install && pnpm dev`.

The implementation source of truth lives in `docs/MASTER_SPEC.md`.

## Deployment

Production deployment is defined in `docker-compose.production.yml` and
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The Oracle VM setup is interactive:
it creates a protected environment file, applies tracked migrations, starts the
API and scheduled collectors behind automatic HTTPS, and verifies `/health`.
The Vercel project continues to use `apps/web` as its root directory.

The upstream PostGIS 16 image is amd64-only as of this setup. Compose pins
`POSTGIS_PLATFORM=linux/amd64` by default so Docker Desktop or Colima can run it on Apple
Silicon. Override the variable only when using a compatible alternate image/platform.
