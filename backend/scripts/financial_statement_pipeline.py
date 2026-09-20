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
except ModuleNotFoundError:  # Direct execution: python scripts/financial_statement_pipeline.py
    from csv_parquet_pipeline import (
        ColumnSpec,
        DatasetSpec,
        compact_dataset,
        convert_dataset,
        validate_dataset,
        write_inventory,
    )


SPEC = DatasetSpec(
    dataset="stock-fin-data-xbx-daily",
    database="trade_data",
    table="financial_statement",
    encoding="gb18030",
    skip_rows=1,
    columns=(
        ColumnSpec("stock_code", "symbol", "text"),
        ColumnSpec("statement_format", "statement_format", "text"),
        ColumnSpec("report_date", "report_date", "compact_date"),
        ColumnSpec("publish_date", "publish_date", "date"),
        ColumnSpec("B_total_assets@xbx", "total_assets", "number"),
        ColumnSpec("B_total_liab@xbx", "total_liabilities", "number"),
        ColumnSpec("B_total_equity_atoopc@xbx", "parent_equity", "number"),
        ColumnSpec("B_total_owner_equity@xbx", "total_owner_equity", "number"),
        ColumnSpec("R_revenue@xbx", "operating_revenue", "number"),
        ColumnSpec("R_op@xbx", "operating_profit", "number"),
        ColumnSpec("R_total_profit@xbx", "total_profit", "number"),
        ColumnSpec("R_np@xbx", "net_profit", "number"),
        ColumnSpec("R_np_atoopc@xbx", "parent_net_profit", "number"),
        ColumnSpec("R_basic_eps@xbx", "basic_eps", "number"),
        ColumnSpec("R_dlt_earnings_per_share@xbx", "diluted_eps", "number"),
        ColumnSpec("C_ncf_from_oa@xbx", "operating_cash_flow", "number"),
        ColumnSpec("C_ncf_from_ia@xbx", "investing_cash_flow", "number"),
        ColumnSpec("C_ncf_from_fa@xbx", "financing_cash_flow", "number"),
        ColumnSpec("C_net_increase_in_cce@xbx", "net_cash_increase", "number"),
        ColumnSpec("C_final_balance_of_cce@xbx", "ending_cash_balance", "number"),
    ),
    key_fields=("symbol", "report_date", "publish_date"),
    identity_field="symbol",
    recursive=True,
    identity_from_parent=True,
    allow_extra_columns=True,
)


def _default_source() -> Path:
    return Path(os.getenv("TRADE_DATA_ROOT", "D:/trade_data")) / "stock-fin-data-xbx"


def _default_output() -> Path:
    return Path(os.getenv("CURATED_DATA_ROOT", "D:/trade_data_curated")) / SPEC.database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the XBX financial statement table")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--source", type=Path, default=_default_source())
    inventory_parser.add_argument(
        "--output",
        type=Path,
        default=_default_output() / "_inventory.financial_statement.json",
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
