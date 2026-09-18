from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

try:
    from scripts.csv_parquet_pipeline import (
        ColumnSpec,
        DatasetSpec,
        compact_dataset,
        convert_dataset,
        validate_dataset,
        write_inventory,
    )
except ModuleNotFoundError:  # Direct execution: python scripts/main_index_pipeline.py
    from csv_parquet_pipeline import (
        ColumnSpec,
        DatasetSpec,
        compact_dataset,
        convert_dataset,
        validate_dataset,
        write_inventory,
    )


SPEC = DatasetSpec(
    dataset="stock-main-index-data",
    database="trade_data",
    table="index_daily",
    encoding="utf-8-sig",
    skip_rows=0,
    columns=(
        ColumnSpec("candle_end_time", "trade_date", "date"),
        ColumnSpec("open", "open", "number"),
        ColumnSpec("high", "high", "number"),
        ColumnSpec("low", "low", "number"),
        ColumnSpec("close", "close", "number"),
        ColumnSpec("amount", "turnover", "number"),
        ColumnSpec("volume", "volume", "number"),
        ColumnSpec("index_code", "index_code", "text"),
    ),
    key_fields=("index_code", "trade_date"),
    identity_field="index_code",
)


def _default_source() -> Path:
    return Path(os.getenv("TRADE_DATA_ROOT", "D:/trade_data")) / SPEC.dataset


def _default_output() -> Path:
    return Path(os.getenv("CURATED_DATA_ROOT", "D:/trade_data_curated")) / SPEC.database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the main-index daily Parquet table")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--source", type=Path, default=_default_source())
    inventory_parser.add_argument(
        "--output", type=Path, default=_default_output() / "_inventory.index_daily.json"
    )
    convert_parser = subparsers.add_parser("convert")
    convert_parser.add_argument("--source", type=Path, default=_default_source())
    convert_parser.add_argument("--output", type=Path, default=_default_output())
    convert_parser.add_argument("--force", action="store_true")
    convert_parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    for command in ("validate", "compact"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--output", type=Path, default=_default_output())
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inventory":
        result = write_inventory(SPEC, args.source, args.output)
    elif args.command == "convert":
        result = convert_dataset(
            SPEC,
            args.source,
            args.output,
            force=args.force,
            workers=args.workers,
            progress=True,
        )
    elif args.command == "validate":
        result = validate_dataset(SPEC, args.output)
    else:
        result = compact_dataset(SPEC, args.output)
    displayed = {key: value for key, value in result.items() if key != "files"}
    print(json.dumps(displayed, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
