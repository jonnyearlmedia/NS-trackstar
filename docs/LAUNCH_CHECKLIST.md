# Trackstar launch checklist

This is the finite release checklist. It is intentionally shorter than the long-term roadmap.

## Automated gates

- [ ] Exact PR head: web TypeScript typecheck passes.
- [ ] Exact PR head: Next.js production build passes.
- [ ] Exact PR head: Python Ruff + full API/ingest pytest suite passes.
- [ ] Exact PR head: all SQL migrations apply cleanly to PostGIS.
- [ ] Exact PR head: database backup → clean restore round trip passes and restored schema matches the source database.
- [ ] Exact PR head: production backend/PostGIS images build, Compose validates and Caddy validates.

## Consumer truth gates

- [ ] Map uses canonical category/lifecycle truth and never invents geometry.
- [ ] Every mapped project has a representative interaction marker; line/polygon projects retain their original geometry for selection.
- [ ] Unknown/unmapped search results remain usable without fake pins.
- [ ] Public Updates excludes known collector churn/noise.
- [ ] Project freshness warns only when source freshness is materially stale for that project.
- [ ] Official sources and public-record limitation copy are reachable from the project experience.
- [ ] Wrong/outdated-information reporting is reachable and carries project context.

## Core journey gates

- [ ] First open clearly frames Napa + Solano and exposes project inventory through clusters/categories.
- [ ] Pan/zoom transitions smoothly to local category pins without a wall of raw GIS geometry.
- [ ] Browse works in dense areas rather than hiding the list.
- [ ] Search handles project/business/address/road/evidence queries and ordinary misspellings.
- [ ] Near Me has a pre-prompt plus denied/error/outside-coverage fallbacks.
- [ ] Project Peek answers “what is this?” and “what's happening?” before technical detail.
- [ ] Expanded project detail exposes facts, status/history, freshness and official sources.
- [ ] Back/close restores the user's previous map/browse context.
- [ ] Updates has intentional loading/error/empty behavior.
- [ ] Briefing remains inside the current viewport and restores the prior map on exit.
- [ ] Share/deep-link `/projects/{id}` routes resolve.
- [ ] Small-phone and desktop layouts retain readable labels and usable touch targets.

## Operational gates

- [ ] Current production source-health snapshot is acceptable for public use; a known noisy source must be suppressed rather than allowed to pollute the consumer feed.
- [ ] A current database backup has been created and copied off the VM before destructive infrastructure maintenance.
- [ ] Exact approved frontend commit is deployed and the public backend health endpoint responds over HTTPS.
- [ ] Product/regression probes return healthy on the release deployment.

## Approval gates

- [ ] Jonny visually/use-checks the exact release deployment.
- [ ] Jonny explicitly approves merging PR #1.
- [ ] Jonny explicitly approves public launch.

**Never merge or launch solely because CI is green.**
