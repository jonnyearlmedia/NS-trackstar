from __future__ import annotations

import argparse
import asyncio
import json

from ns_trackstar.config import load_source_config
from ns_trackstar.registry import build_adapter


async def collect(config_path: str) -> int:
    adapter_name, config = load_source_config(config_path)
    adapter = build_adapter(adapter_name, config)

    canary_ok = await adapter.canary()
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="ns-trackstar-ingest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("config")

    args = parser.parse_args()
    if args.command == "collect":
        raise SystemExit(asyncio.run(collect(args.config)))


if __name__ == "__main__":
    main()
