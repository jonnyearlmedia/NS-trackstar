# Trackstar operations and release response

This is the minimum v1 operating contract for a public Trackstar deployment. It intentionally stays small enough to use.

## Health surfaces

- `GET /health` — backend process/database health.
- `GET /api/status/product` — consumer product-path probe.
- `GET /api/status/regression` — flagship regression-path probe.
- `GET /api/status/release-data` — release data quality/freshness gate covering all 23 configured production sources, lifecycle distribution, CivicClerk churn, and canonical quality audit.
- `GET /admin/sources/cadence?days=7` — per-source cadence, missed checks, success rate, latest outcome and policy state.
- `GET /admin/quality/audit` — duplicate-name review groups, unresolved high-confidence entity candidates, conflicting current assertions and rotating manual-QA sample.

## What blocks a release

A release is blocked when any of the following is true:

- backend health is not 200;
- any production source is currently unhealthy;
- any production source has missed its expected check window;
- an active consumer freshness class (`meeting_feed`, `active_project_tracker`, `state_project_watch`, `regulatory_watch`) is `unstable`;
- any configured source cadence is outside its declared freshness policy;
- exact-head CI fails typecheck/build, Python tests/lint, database migration + backup/restore verification, production image/config validation, or cross-browser release QA;
- product/regression probes fail on the exact release deployment.

Slow reference/project-specific sources with weak historical success can be reported as warnings when their latest health is good, they have not missed their expected check, and they do not drive live consumer Updates. Warnings must not be hidden; they simply do not have the same severity as a broken active feed.

## CivicClerk rule

`vallejo.civicclerk` remains suppressed from public Updates until normalized field-level churn is stable. A healthy collector run alone is not permission to re-enable it. Review the cadence audit plus churn-fields endpoint over multiple runs before changing the suppression rule.

## Response expectations

- **Backend unavailable or active source unhealthy:** do not launch a new release. Restore service/source collection first.
- **Missed expected check:** inspect scheduler/container logs and the source run record before changing cadence.
- **Schema/access failure:** do not create aggressive retry loops. Keep normal cadence, diagnose the upstream change, then patch the adapter/config.
- **No-change successful run:** this is healthy and should not create a consumer update.
- **Reference-source warning:** keep visible internally, but do not tell consumers the whole product is stale unless that source contributes to the project they are viewing.
- **Consumer data conflict:** preserve both official assertions/source history, avoid auto-choosing a winner, and review through the quality audit.

## Backup/recovery

Before destructive infrastructure maintenance:

1. Run `./scripts/backup-production-db.sh`.
2. Copy the `.dump` and `.sha256` off the VM.
3. Periodically validate a real backup with `RESTORE_DATABASE=nstrackstar_restore ./scripts/restore-production-db.sh <backup.dump>`.
4. Never overwrite the primary database unless performing intentional disaster recovery with the explicit guard.

CI separately performs a clean `pg_dump` → `pg_restore` round trip after migrations so recovery remains continuously exercised.

## Release sequence

1. Freeze the candidate commit.
2. Require exact-head CI green, including browser/accessibility/network/density QA.
3. Require an exact-head Vercel preview.
4. Probe `/api/status/product`, `/api/status/regression`, and `/api/status/release-data` on that exact preview.
5. Review reference warnings and CivicClerk state; warnings must be understood, not ignored.
6. Do the final human visual/use review on the exact preview.
7. Merge PR #1 only after explicit approval.
8. Publicly launch only after explicit approval.

No automated green check is a substitute for the explicit merge/public-launch approvals.
