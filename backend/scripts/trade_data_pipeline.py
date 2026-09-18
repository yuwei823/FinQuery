from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb


DATABASE_ID = "trade_data"
TABLE_NAME = "stock_daily"
SOURCE_ENCODING = "gb18030"


@dataclass(frozen=True)
class ColumnSpec:
    source: str
    target: str
    kind: str


COLUMNS = (
    ColumnSpec("股票代码", "symbol", "text"),
    ColumnSpec("股票名称", "stock_name", "text"),
    ColumnSpec("交易日期", "trade_date", "date"),
    ColumnSpec("开盘价", "open", "number"),
    ColumnSpec("最高价", "high", "number"),
    ColumnSpec("最低价", "low", "number"),
    ColumnSpec("收盘价", "close", "number"),
    ColumnSpec("前收盘价", "previous_close", "number"),
    ColumnSpec("成交量", "volume", "number"),
    ColumnSpec("成交额", "turnover", "number"),
    ColumnSpec("流通市值", "float_market_cap", "number"),
    ColumnSpec("总市值", "total_market_cap", "number"),
    ColumnSpec("净利润TTM", "net_profit_ttm", "number"),
    ColumnSpec("现金流TTM", "cash_flow_ttm", "number"),
    ColumnSpec("净资产", "net_assets", "number"),
    ColumnSpec("总资产", "total_assets", "number"),
    ColumnSpec("总负债", "total_liabilities", "number"),
    ColumnSpec("净利润(当季)", "quarter_net_profit", "number"),
    ColumnSpec("中户资金买入额", "medium_buy_amount", "number"),
    ColumnSpec("中户资金卖出额", "medium_sell_amount", "number"),
    ColumnSpec("大户资金买入额", "large_buy_amount", "number"),
    ColumnSpec("大户资金卖出额", "large_sell_amount", "number"),
    ColumnSpec("散户资金买入额", "retail_buy_amount", "number"),
    ColumnSpec("散户资金卖出额", "retail_sell_amount", "number"),
    ColumnSpec("机构资金买入额", "institution_buy_amount", "number"),
    ColumnSpec("机构资金卖出额", "institution_sell_amount", "number"),
    ColumnSpec("沪深300成分股", "is_csi_300", "boolean"),
    ColumnSpec("上证50成分股", "is_sse_50", "boolean"),
    ColumnSpec("中证500成分股", "is_csi_500", "boolean"),
    ColumnSpec("中证1000成分股", "is_csi_1000", "boolean"),
    ColumnSpec("中证2000成分股", "is_csi_2000", "boolean"),
    ColumnSpec("创业板指成分股", "is_chinext", "boolean"),
    ColumnSpec("新版申万一级行业名称", "industry_level_1", "text"),
    ColumnSpec("新版申万二级行业名称", "industry_level_2", "text"),
    ColumnSpec("新版申万三级行业名称", "industry_level_3", "text"),
    ColumnSpec("09:35收盘价", "close_0935", "number"),
    ColumnSpec("09:45收盘价", "close_0945", "number"),
    ColumnSpec("09:55收盘价", "close_0955", "number"),
)

EXPECTED_HEADER = tuple(column.source for column in COLUMNS)
TARGET_HEADER = tuple(column.target for column in COLUMNS)


def _safe_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _read_header(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding=SOURCE_ENCODING, newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # 数据提供方说明行
        return tuple(next(reader, ()))


def _header_error(header: tuple[str, ...]) -> str | None:
    if len(header) != len(EXPECTED_HEADER):
        return f"期望{len(EXPECTED_HEADER)}列，实际{len(header)}列"
    if len(set(header)) != len(header):
        return "存在重复字段名"
    missing = sorted(set(EXPECTED_HEADER) - set(header))
    extra = sorted(set(header) - set(EXPECTED_HEADER))
    if missing or extra:
        return f"缺少字段={missing}，额外字段={extra}"
    return None


def inventory(source: Path) -> dict[str, Any]:
    files = sorted(source.glob("*.csv"))
    if not source.is_dir():
        raise FileNotFoundError(f"原始行情目录不存在：{source}")
    if not files:
        raise ValueError(f"原始行情目录没有CSV文件：{source}")

    invalid_headers: list[dict[str, Any]] = []
    reordered_headers: list[str] = []
    total_bytes = 0
    latest_mtime_ns = 0
    for path in files:
        stat = path.stat()
        total_bytes += stat.st_size
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        header = _read_header(path)
        error = _header_error(header)
        if error:
            invalid_headers.append(
                {
                    "file": path.name,
                    "error": error,
                    "column_count": len(header),
                    "columns": list(header),
                }
            )
        elif header != EXPECTED_HEADER:
            reordered_headers.append(path.name)

    return {
        "dataset": "stock-trading-data-pro",
        "encoding": SOURCE_ENCODING,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "latest_mtime_ns": latest_mtime_ns,
        "expected_column_count": len(EXPECTED_HEADER),
        "invalid_header_count": len(invalid_headers),
        "invalid_headers": invalid_headers[:100],
        "reordered_header_count": len(reordered_headers),
        "reordered_header_examples": reordered_headers[:100],
    }


def write_inventory(source: Path, destination: Path) -> dict[str, Any]:
    result = inventory(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(destination, result)
    return result


def _projection_sql() -> str:
    expressions: list[str] = []
    for column in COLUMNS:
        quoted = f'"{column.target}"'
        if column.kind == "text":
            expression = f"NULLIF(TRIM({quoted}), '')::VARCHAR"
        elif column.kind == "date":
            expression = f"CAST(NULLIF({quoted}, '') AS DATE)"
        elif column.kind == "number":
            expression = f"CAST(NULLIF({quoted}, '') AS DOUBLE)"
        elif column.kind == "boolean":
            expression = (
                f"CASE WHEN UPPER(TRIM({quoted})) = 'Y' THEN TRUE "
                f"WHEN NULLIF(TRIM({quoted}), '') IS NULL THEN FALSE "
                f"ELSE CAST({quoted} AS BOOLEAN) END"
            )
        else:  # pragma: no cover - ColumnSpec 是模块内固定契约
            raise ValueError(f"未知字段类型：{column.kind}")
        expressions.append(f'{expression} AS "{column.target}"')
    return ",\n            ".join(expressions)


def _normalize_csv(source: Path, destination: Path) -> int:
    row_count = 0
    with source.open("r", encoding=SOURCE_ENCODING, newline="") as input_handle:
        next(input_handle, None)
        reader = csv.DictReader(input_handle)
        header = tuple(reader.fieldnames or ())
        error = _header_error(header)
        if error:
            raise ValueError(f"{source.name}表头不匹配：{error}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.writer(output_handle)
            writer.writerow(TARGET_HEADER)
            for line_number, row in enumerate(reader, start=3):
                values = [str(row.get(column.source) or "") for column in COLUMNS]
                if not any(value.strip() for value in values):
                    continue
                if None in row:
                    raise ValueError(
                        f"{source.name}第{line_number}行包含表头之外的额外列"
                    )
                if values[0].strip() != source.stem:
                    raise ValueError(
                        f"{source.name}第{line_number}行股票代码与文件名不一致"
                    )
                writer.writerow(values)
                row_count += 1
    if row_count == 0:
        raise ValueError(f"{source.name}没有数据行")
    return row_count


def _convert_file(
    connection: duckdb.DuckDBPyConnection,
    source: Path,
    staging_dir: Path,
    table_dir: Path,
) -> dict[str, Any]:
    normalized_csv = staging_dir / f"{source.stem}.csv"
    temporary_parquet = staging_dir / f"{source.stem}.parquet"
    final_parquet = table_dir / f"{source.stem}.parquet"
    normalized_rows = _normalize_csv(source, normalized_csv)
    try:
        connection.execute(
            f"""
            COPY (
                SELECT
                    {_projection_sql()}
                FROM read_csv(
                    '{_safe_path(normalized_csv)}',
                    header=true,
                    all_varchar=true,
                    strict_mode=true
                )
            ) TO '{_safe_path(temporary_parquet)}'
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        row_count, min_date, max_date, symbols = connection.execute(
            f"""
            SELECT COUNT(*), MIN(trade_date), MAX(trade_date), COUNT(DISTINCT symbol)
            FROM read_parquet('{_safe_path(temporary_parquet)}')
            """
        ).fetchone()
        if row_count != normalized_rows:
            raise ValueError(
                f"{source.name}转换前后行数不一致：{normalized_rows} != {row_count}"
            )
        if symbols != 1:
            raise ValueError(f"{source.name}包含{symbols}个股票代码")
        os.replace(temporary_parquet, final_parquet)
        stat = source.stat()
        return {
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "rows": row_count,
            "min_date": min_date.isoformat() if min_date else None,
            "max_date": max_date.isoformat() if max_date else None,
            "parquet": f"{TABLE_NAME}/{final_parquet.name}",
        }
    finally:
        normalized_csv.unlink(missing_ok=True)
        temporary_parquet.unlink(missing_ok=True)


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"database": DATABASE_ID, "table": TABLE_NAME, "files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _selected_files(source: Path, limit_files: int | None) -> list[Path]:
    files = sorted(source.glob("*.csv"))
    if limit_files is not None:
        if limit_files < 1:
            raise ValueError("limit_files必须大于0")
        files = files[:limit_files]
    if not files:
        raise ValueError(f"原始行情目录没有CSV文件：{source}")
    return files


def convert_dataset(
    source: Path,
    output: Path,
    *,
    limit_files: int | None = None,
    force: bool = False,
    workers: int = 1,
    progress: bool = False,
) -> dict[str, Any]:
    if not source.is_dir():
        raise FileNotFoundError(f"原始行情目录不存在：{source}")
    output.mkdir(parents=True, exist_ok=True)
    table_dir = output / TABLE_NAME
    staging_dir = output / ".staging"
    table_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "_pipeline_manifest.json"
    manifest = _load_manifest(manifest_path)
    records: dict[str, dict[str, Any]] = manifest.setdefault("files", {})
    converted = 0
    skipped = 0
    pending: list[Path] = []
    if workers < 1:
        raise ValueError("workers必须大于0")

    for path in _selected_files(source, limit_files):
        stat = path.stat()
        existing = records.get(path.name)
        final_path = table_dir / f"{path.stem}.parquet"
        unchanged = (
            existing
            and existing.get("source_size") == stat.st_size
            and existing.get("source_mtime_ns") == stat.st_mtime_ns
            and final_path.exists()
        )
        if unchanged and not force:
            skipped += 1
        else:
            pending.append(path)

    def convert_one(path: Path) -> tuple[Path, dict[str, Any]]:
        connection = duckdb.connect(":memory:")
        try:
            return path, _convert_file(connection, path, staging_dir, table_dir)
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for path, result in executor.map(convert_one, pending):
                records[path.name] = result
                converted += 1
                if converted % 50 == 0:
                    manifest.update(_manifest_summary(records, converted, skipped))
                    _write_json_atomic(manifest_path, manifest)
                if progress and (converted % 100 == 0 or converted == len(pending)):
                    print(
                        f"converted={converted}/{len(pending)} skipped={skipped}",
                        flush=True,
                    )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    manifest.update(_manifest_summary(records, converted, skipped))
    _write_json_atomic(manifest_path, manifest)
    return manifest


def _manifest_summary(
    records: dict[str, dict[str, Any]],
    converted: int,
    skipped: int,
) -> dict[str, Any]:
    min_dates = [item["min_date"] for item in records.values() if item.get("min_date")]
    max_dates = [item["max_date"] for item in records.values() if item.get("max_date")]
    return {
        "database": DATABASE_ID,
        "table": TABLE_NAME,
        "source_encoding": SOURCE_ENCODING,
        "file_count": len(records),
        "row_count": sum(int(item.get("rows", 0)) for item in records.values()),
        "min_date": min(min_dates) if min_dates else None,
        "max_date": max(max_dates) if max_dates else None,
        "converted_this_run": converted,
        "skipped_this_run": skipped,
        "files": records,
    }


def validate_dataset(output: Path) -> dict[str, Any]:
    manifest_path = output / "_pipeline_manifest.json"
    table_dir = output / TABLE_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"转换manifest不存在：{manifest_path}")
    parquet_files = sorted(table_dir.glob("*.parquet"))
    if not parquet_files:
        raise ValueError(f"没有可验证的Parquet分片：{table_dir}")

    manifest = _load_manifest(manifest_path)
    parquet_glob = _safe_path(table_dir / "*.parquet")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("PRAGMA disable_progress_bar")
        row_count, symbol_count, min_date, max_date, null_key_count = connection.execute(
            f"""
            SELECT
                COUNT(*),
                COUNT(DISTINCT symbol),
                MIN(trade_date),
                MAX(trade_date),
                COUNT(*) FILTER (WHERE symbol IS NULL OR trade_date IS NULL)
            FROM read_parquet('{parquet_glob}', union_by_name=true)
            """
        ).fetchone()
        duplicate_key_groups = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT symbol, trade_date, COUNT(*) AS n
                FROM read_parquet('{parquet_glob}', union_by_name=true)
                GROUP BY symbol, trade_date
                HAVING n > 1
            )
            """
        ).fetchone()[0]
    finally:
        connection.close()

    errors: list[str] = []
    if len(parquet_files) != int(manifest.get("file_count", -1)):
        errors.append("Parquet分片数与manifest不一致")
    if row_count != int(manifest.get("row_count", -1)):
        errors.append("Parquet总行数与manifest不一致")
    if symbol_count != len(parquet_files):
        errors.append("股票代码数与Parquet分片数不一致")
    if null_key_count:
        errors.append(f"存在{null_key_count}行空主键")
    if duplicate_key_groups:
        errors.append(f"存在{duplicate_key_groups}组重复主键")

    return {
        "database": DATABASE_ID,
        "table": TABLE_NAME,
        "parquet_files": len(parquet_files),
        "row_count": row_count,
        "symbol_count": symbol_count,
        "min_date": min_date.isoformat() if min_date else None,
        "max_date": max_date.isoformat() if max_date else None,
        "null_key_count": null_key_count,
        "duplicate_key_groups": duplicate_key_groups,
        "errors": errors,
    }


def _default_source() -> Path:
    root = os.getenv("TRADE_DATA_ROOT", "D:/trade_data")
    return Path(root) / "stock-trading-data-pro"


def _default_output() -> Path:
    return Path(os.getenv("CURATED_DATA_ROOT", "D:/trade_data_curated")) / DATABASE_ID


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FinQuery 行情数据扫描与Parquet转换器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser("inventory", help="扫描原始行情目录")
    inventory_parser.add_argument("--source", type=Path, default=_default_source())
    inventory_parser.add_argument(
        "--output",
        type=Path,
        default=_default_output() / "_inventory.json",
    )

    convert_parser = subparsers.add_parser("convert", help="增量转换为Parquet")
    convert_parser.add_argument("--source", type=Path, default=_default_source())
    convert_parser.add_argument("--output", type=Path, default=_default_output())
    convert_parser.add_argument("--limit-files", type=int)
    convert_parser.add_argument("--force", action="store_true")
    convert_parser.add_argument(
        "--workers",
        type=int,
        default=min(8, os.cpu_count() or 4),
    )
    validate_parser = subparsers.add_parser("validate", help="验证Parquet和manifest")
    validate_parser.add_argument("--output", type=Path, default=_default_output())
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inventory":
        result = write_inventory(args.source, args.output)
    elif args.command == "convert":
        result = convert_dataset(
            args.source,
            args.output,
            limit_files=args.limit_files,
            force=args.force,
            workers=args.workers,
            progress=True,
        )
    else:
        result = validate_dataset(args.output)
    display_result = (
        {key: value for key, value in result.items() if key != "files"}
        if args.command == "convert"
        else result
    )
    print(json.dumps(display_result, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
