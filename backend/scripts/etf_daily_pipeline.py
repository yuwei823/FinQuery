from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

try:
    from scripts.csv_parquet_pipeline import ColumnSpec, DatasetSpec, compact_dataset, convert_dataset, validate_dataset, write_inventory
except ModuleNotFoundError:
    from csv_parquet_pipeline import ColumnSpec, DatasetSpec, compact_dataset, convert_dataset, validate_dataset, write_inventory


SPEC = DatasetSpec(
    dataset="stock-etf-trading-data",
    database="trade_data",
    table="stock_etf_trading_data",
    encoding="gb18030",
    skip_rows=1,
    columns=(
        ColumnSpec("交易日期", "trade_date", "date"),
        ColumnSpec("基金名称", "fund_name", "text"),
        ColumnSpec("基金代码", "fund_code", "text"),
        ColumnSpec("前收盘价", "previous_close", "number"),
        ColumnSpec("开盘价", "open", "number"),
        ColumnSpec("最高价", "high", "number"),
        ColumnSpec("最低价", "low", "number"),
        ColumnSpec("收盘价", "close", "number"),
        ColumnSpec("成交量", "volume", "number"),
        ColumnSpec("成交额", "turnover", "number"),
        ColumnSpec("累计单位净值", "cumulative_nav", "number"),
        ColumnSpec("单位净值", "unit_nav", "number"),
        ColumnSpec("后复权因子", "backward_adjustment_factor", "number", required=False),
        ColumnSpec("复权单位净值", "adjusted_nav", "number", required=False),
        ColumnSpec("换手率", "turnover_rate", "number"),
        ColumnSpec("基金分类", "fund_category", "text"),
        ColumnSpec("详细分类", "detailed_category", "text"),
        ColumnSpec("基金份额合计", "total_fund_shares", "number"),
        ColumnSpec("场内流通份额", "exchange_tradable_shares", "number"),
    ),
    key_fields=("fund_code", "trade_date"),
    identity_field="fund_code",
)


def _default_source() -> Path:
    return Path(os.getenv("TRADE_DATA_ROOT", "D:/trade_data")) / SPEC.dataset


def _default_output() -> Path:
    return Path(os.getenv("CURATED_DATA_ROOT", "D:/trade_data_curated")) / SPEC.database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the ETF daily Parquet table")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--source", type=Path, default=_default_source())
    inventory_parser.add_argument("--output", type=Path, default=_default_output() / "_inventory.stock_etf_trading_data.json")
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
        result = convert_dataset(SPEC, args.source, args.output, force=args.force, workers=args.workers, progress=True)
    elif args.command == "validate":
        result = validate_dataset(SPEC, args.output)
    else:
        result = compact_dataset(SPEC, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
