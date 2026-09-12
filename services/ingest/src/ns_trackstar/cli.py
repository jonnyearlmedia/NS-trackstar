from __future__ import annotations

import argparse
import asyncio
import json
import os

import psycopg

from ns_trackstar.adapters.base import SourceBlockedError, SourceConfig
from ns_trackstar.config import load_source_config
from ns_trackstar.db import (
    connect,
    ensure_source,
    fail_source_run,
    persist_collection,
    start_source_run,
)
from ns_trackstar.enrichment import (
    enrich_napa_projects_from_parcels,
    enrich_one_lake_relationships,
    enrich_solano_projects_from_parcels,
    enrich_sr37_sears_point_corridor,
)
from ns_trackstar.registry import build_adapter


async def _dry_run(adapter_name: str, config: SourceConfig) -> int:
    adapter = build_adapter(adapter_name, config)
    try:
        canary_ok = await adapter.canary()
    except SourceBlockedError as exc:
        print(
            json.dumps(
                {
                    "source": config.key,
                    "canary_ok": None,
                    "records": 0,
                    "health_state": "blocked",
                    "reason": str(exc),
                }
            )
        )
        return 3
    if not canary_ok:
        print(json.dumps({"source": config.key, "canary_ok": False, "records": 0}))
        return 2
    result = await adapter.collect()
    print(
        json.dumps(
            {
                "source": config.key,
                "adapter": adapter_name,
                "canary_ok": True,
                "records": len(result.records),
                "schema_fingerprint": result.schema_fingerprint,
                "parser_yield": result.parser_yield,
                "metadata": result.metadata,
            },
            indent=2,
        )
    )
    return 0


async def _start_run(
    conn: psycopg.AsyncConnection,
    *,
    adapter_name: str,
    config: SourceConfig,
) -> tuple[str, str]:
    async with conn.transaction():
        source_id = await ensure_source(
            conn,
            source_key=config.key,
            name=config.name,
            source_family=adapter_name,
            jurisdiction=config.jurisdiction,
            base_url=config.base_url,
            poll_interval_minutes=config.poll_minutes,
            collector_type=adapter_name,
            config=config.options,
        )
        run_id = await start_source_run(conn, source_id)
    return source_id, run_id


async def collect(config_path: str, *, write: bool) -> int:
    adapter_name, config = load_source_config(config_path)
    if not write:
        return await _dry_run(adapter_name, config)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required when --write is used")

    adapter = build_adapter(adapter_name, config)
    enriched_napa_projects = 0
    enriched_solano_projects = 0
    enriched_corridors = 0
    enriched_relationships = 0
    async with connect(database_url) as conn:
        source_id, run_id = await _start_run(conn, adapter_name=adapter_name, config=config)

        canary_ok: bool | None = None
        try:
            canary_ok = await adapter.canary()
            if not canary_ok:
                async with conn.transaction():
                    await fail_source_run(
                        conn,
                        run_id=run_id,
                        source_id=source_id,
                        error_type="CanaryFailed",
                        error_message="Source canary no longer matches expected public schema",
                        canary_ok=False,
                        health_state="schema_changed",
                    )
                print(json.dumps({"source": config.key, "canary_ok": False, "records": 0}))
                return 2

            result = await adapter.collect()
            async with conn.transaction():
                summary = await persist_collection(
                    conn,
                    source_id=source_id,
                    run_id=run_id,
                    result=result,
                    canary_ok=True,
                    project_mapping=config.options.get("project_mapping"),
                )

                if config.key in {
                    "napa-county.parcels",
                    "california.ceqanet.napa-solano",
                    "napa-county.current-projects-explorer",
                    "napa-county.napa-pipe-development-plan",
                    "napa-city.napa-pipe-amendments",
                }:
                    enriched_napa_projects = await enrich_napa_projects_from_parcels(conn)

                if config.key in {
                    "solano-county.parcels",
                    "fairfield.one-lake-assessor-map",
                    "suisun-city.dutch-bros-public-notice",
                }:
                    enriched_solano_projects = await enrich_solano_projects_from_parcels(conn)

                if config.key == "california.ceqanet.napa-solano":
                    enriched_corridors = await enrich_sr37_sears_point_corridor(conn)

                if config.key in {
                    "fairfield.one-lake-council-goals",
                    "fairfield.one-lake-assessor-map",
                    "fairfield.vanden-canon-overcrossing",
                }:
                    enriched_relationships = await enrich_one_lake_relationships(conn)
        except Exception as exc:
            async with conn.transaction():
                await fail_source_run(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    canary_ok=canary_ok,
                    health_state=(
                        "blocked" if isinstance(exc, SourceBlockedError) else "broken"
                    ),
                )
            raise

    print(
        json.dumps(
            {
                "source": config.key,
                "adapter": adapter_name,
                "canary_ok": True,
                "records": summary.records_seen,
                "persisted": {
                    "source_id": summary.source_id,
                    "run_id": summary.run_id,
                    "records_changed": summary.records_changed,
                    "projects_created": summary.projects_created,
                    "projects_touched": summary.projects_touched,
                    "napa_projects_enriched_from_parcels": enriched_napa_projects,
                    "solano_projects_enriched_from_parcels": enriched_solano_projects,
                    "corridors_enriched": enriched_corridors,
                    "project_relationships_enriched": enriched_relationships,
                },
            },
            indent=2,
        )
    )
    return 0


async def enrich_all() -> int:
    """Run all local, idempotent enrichments without re-crawling upstream sources."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for enrichment")

    async with connect(database_url) as conn, conn.transaction():
        summary = {
            "napa_projects_enriched_from_parcels": await enrich_napa_projects_from_parcels(conn),
            "solano_projects_enriched_from_parcels": await enrich_solano_projects_from_parcels(conn),
            "corridors_enriched": await enrich_sr37_sears_point_corridor(conn),
            "project_relationships_enriched": await enrich_one_lake_relationships(conn),
        }

    print(json.dumps({"enrichment": "complete", **summary}, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="ns-trackstar-ingest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("config")
    collect_parser.add_argument("--write", action="store_true")
    subparsers.add_parser("enrich")

    args = parser.parse_args()
    if args.command == "collect":
        raise SystemExit(asyncio.run(collect(args.config, write=args.write)))
    if args.command == "enrich":
        raise SystemExit(asyncio.run(enrich_all()))


if __name__ == "__main__":
    main()
