# NS Trackstar — implementation source of truth

## Product

NS Trackstar is a public, mobile-first Napa–Solano intelligence map for understanding what is physically changing across American Canyon, Vallejo, Napa, Fairfield, Benicia, Suisun City and the surrounding county areas.

It is a government-record intelligence system first and a news/discovery system second.

## Durable architecture

The durable abstractions are:

- source provenance
- source runs and source health
- immutable source records + snapshots
- field-level assertions
- canonical projects
- typed project relationships
- multidimensional project status
- semantic project events
- geometry with explicit location accuracy
- evidence-backed timelines

Collectors, government portals and map styles may change without invalidating those abstractions.

## Data flow

```text
Government / regulatory / transportation / discovery sources
                         ↓
                 source records
                         ↓
               normalize + diff
                         ↓
        assertions + relationship candidates
                         ↓
                 canonical projects
                         ↓
             status dimensions + events
                         ↓
                  PostGIS / Martin
                         ↓
               MapLibre web experience
```

## Relationship rule

Matching creates typed edges before it creates merges.

Supported relationships:

- same_physical_project
- parent_child
- alias_of
- supersedes
- related_infrastructure
- permit_for
- environmental_review_for
- litigation_about
- business_within
- spatial_overlap_only
- adjacent_project

APN or geometry overlap alone must never force a project merge when multiple active projects can share the site.

## Status rule

There is no single global project status. Track independent dimensions such as planning, entitlement, environmental, permitting, construction, occupancy, operations, litigation, federal/state authorization, gaming, funding and procurement.

## Retrieval priority

1. documented API
2. ArcGIS REST
3. public structured JSON/XHR
4. structured HTML
5. normal HTTP form submission
6. browser/session automation
7. OCR

Playwright is a fallback or session bootstrap mechanism, not the universal collector.

## Initial map stack

- Next.js
- shadcn/ui
- mapcn components where useful
- MapLibre GL JS
- OpenFreeMap
- Maputnik
- deck.gl where it materially helps
- Terra Draw when area selection/watch zones are exposed
- PMTiles for static/slow GIS
- PostGIS + Martin for dynamic project intelligence

## Initial infrastructure

- Oracle Cloud Free Tier VM: Postgres/PostGIS, collectors, Playwright, Martin, API
- Vercel free tier: web frontend initially
- recurring infrastructure target: $0
- optional AI enrichment: hard cap approximately $5/month

## AI boundary

AI is optional enrichment. Never use it for APN equality, exact IDs, address normalization, geometry intersection, hashing, date parsing or known parent IDs.

Use it selectively for narrative extraction, agenda relevance, legal/regulatory explanation, alias suggestions and readable source-grounded summaries.

If the AI budget is exhausted, ingestion and the map must continue to function.

## MVP experience

- full-screen map
- Today / This Week / Upcoming / All
- category filters
- search and Search This Area
- map/list experience
- truthful geometry highlighting
- project cards
- multidimensional status
- project timeline
- what changed
- source provenance
- location confidence
- shareable project URLs

Post-MVP signatures include cinematic briefings, time slider, parcel history, construction corridors, business-opening predictions, Explain This Site and natural-language search.
