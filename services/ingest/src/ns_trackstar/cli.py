from __future__ import annotations

import argparse
import asyncio
import json
import os

from ns_trackstar.config import load_source_config
from ns_trackstar.db import connect, ensure_source, persist_collection, start_source_run
from ns_trackstar.registry import build_adapter


async def collect(config_path: str, *, write: bool) -> int:
    adapter_name, config = load_source_config(config_path)
    adapter = build_adapter(adapter_name, config)

    canary_ok = await adapter.canary()
    if not canary_ok:
        print(json.dumps({"source": config.key, "canary_ok": False, "records": 0}))
        return 2

    result = await adapter.collect()
    output = {
        "source": config.key,
        "adapter": adapter_name,
        "canary_ok": True,
        "records": len(result.records),
        "schema_fingerprint": result.schema_fingerprint,
        "parser_yield": result.parser_yield,
        "metadata": result.metadata,
    }

    if write:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required when --write is used")

        async with connect(database_url) as conn:
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
                summary = await persist_collection(
                    conn,
                    source_id=source_id,
                    run_id=run_id,
                    result=result,
                    canary_ok=canary_ok,
                    project_mapping=config.options.get("project_mapping"),
                )
        output["persisted"] = {
            "source_id": summary.source_id,
            "run_id": summary.run_id,
            "records_seen": summary.records_seen,
            "records_changed": summary.records_changed,
            "projects_created": summary.projects_created,
            "projects_touched": summary.projects_touched,
        }

    print(json.dumps(output, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="ns-trackstar-ingest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("config")
    collect_parser.add_argument("--write", action="store_true")

    args = parser.parse_args()
    if args.command == "collect":
        raise SystemExit(asyncio.run(collect(args.config, write=args.write)))


if __name__ == "__main__":
    main()
