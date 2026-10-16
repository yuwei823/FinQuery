from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import duckdb


DATABASE_ID = "trade_data"
SOURCE_TABLE = "financial_statement"
TABLE_NAME = "financial_period"
PIPELINE_VERSION = 2
FLOW_FIELDS = (
    "operating_revenue",
    "net_profit",
    "parent_net_profit",
    "operating_cash_flow",
)
KEY_FIELDS = ("symbol", "statement_format", "report_date", "publish_date")
OUTPUT_COLUMNS = (
    *KEY_FIELDS,
    "fiscal_year",
    "fiscal_quarter",
    "period_type",
    "months_in_period",
    "total_assets",
    "total_liabilities",
    "parent_equity",
    "total_owner_equity",
    "prior_year_total_assets",
    "prior_year_parent_equity",
    "avg_total_assets",
    "avg_parent_equity",
    *(
        f"{field}_{basis}"
        for field in FLOW_FIELDS
        for basis in ("ytd", "quarter", "ttm")
    ),
    "quarter_predecessor_report_date",
    "quarter_predecessor_publish_date",
    "ttm_annual_report_date",
    "ttm_annual_publish_date",
    "ttm_prior_report_date",
    "ttm_prior_publish_date",
    "quarter_components_complete",
    "ttm_components_complete",
)


def _safe_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _derived_columns() -> str:
    expressions: list[str] = []
    for field in FLOW_FIELDS:
        expressions.extend(
            (
                f'c."{field}" AS "{field}_ytd"',
                (
                    f"CASE WHEN c.period_type = 'Q1' THEN c.\"{field}\" "
                    f"WHEN c.period_type IN ('H1', 'Q3', 'FY') "
                    f'THEN c."{field}" - p."{field}" END AS "{field}_quarter"'
                ),
                (
                    f"CASE WHEN c.period_type = 'FY' THEN c.\"{field}\" "
                    f"WHEN c.period_type IN ('Q1', 'H1', 'Q3') "
                    f'THEN a."{field}" + c."{field}" - y."{field}" END '
                    f'AS "{field}_ttm"'
                ),
            )
        )
    return ",\n        ".join(expressions)


def _build_query(source_glob: Path) -> str:
    return f"""
    WITH source AS (
        SELECT * FROM read_parquet('{_safe_path(source_glob)}', union_by_name=true)
    ),
    classified AS (
        SELECT *,
            YEAR(report_date)::INTEGER AS fiscal_year,
            CASE
                WHEN MONTH(report_date) = 3 AND DAY(report_date) = 31 THEN 1
                WHEN MONTH(report_date) = 6 AND DAY(report_date) = 30 THEN 2
                WHEN MONTH(report_date) = 9 AND DAY(report_date) = 30 THEN 3
                WHEN MONTH(report_date) = 12 AND DAY(report_date) = 31 THEN 4
            END AS fiscal_quarter,
            CASE
                WHEN MONTH(report_date) = 3 AND DAY(report_date) = 31 THEN 'Q1'
                WHEN MONTH(report_date) = 6 AND DAY(report_date) = 30 THEN 'H1'
                WHEN MONTH(report_date) = 9 AND DAY(report_date) = 30 THEN 'Q3'
                WHEN MONTH(report_date) = 12 AND DAY(report_date) = 31 THEN 'FY'
                ELSE 'OTHER'
            END AS period_type,
            CASE MONTH(report_date) WHEN 3 THEN 3 WHEN 6 THEN 6
                WHEN 9 THEN 9 WHEN 12 THEN 12 END AS months_in_period,
            CASE MONTH(report_date)
                WHEN 6 THEN MAKE_DATE(YEAR(report_date), 3, 31)
                WHEN 9 THEN MAKE_DATE(YEAR(report_date), 6, 30)
                WHEN 12 THEN MAKE_DATE(YEAR(report_date), 9, 30)
            END AS predecessor_date,
            MAKE_DATE(YEAR(report_date) - 1, 12, 31) AS annual_date,
            MAKE_DATE(YEAR(report_date) - 1, MONTH(report_date), DAY(report_date)) AS prior_date
        FROM source
    ),
    predecessor_keys AS (
        SELECT c.symbol, c.statement_format, c.report_date, c.publish_date,
            MAX(p.publish_date) AS matched_publish_date
        FROM classified c LEFT JOIN source p
          ON p.symbol = c.symbol AND p.statement_format = c.statement_format
         AND p.report_date = c.predecessor_date AND p.publish_date <= c.publish_date
        GROUP BY c.symbol, c.statement_format, c.report_date, c.publish_date
    ),
    annual_keys AS (
        SELECT c.symbol, c.statement_format, c.report_date, c.publish_date,
            MAX(a.publish_date) AS matched_publish_date
        FROM classified c LEFT JOIN source a
          ON a.symbol = c.symbol AND a.statement_format = c.statement_format
         AND a.report_date = c.annual_date AND a.publish_date <= c.publish_date
        GROUP BY c.symbol, c.statement_format, c.report_date, c.publish_date
    ),
    prior_keys AS (
        SELECT c.symbol, c.statement_format, c.report_date, c.publish_date,
            MAX(y.publish_date) AS matched_publish_date
        FROM classified c LEFT JOIN source y
          ON y.symbol = c.symbol AND y.statement_format = c.statement_format
         AND y.report_date = c.prior_date AND y.publish_date <= c.publish_date
        GROUP BY c.symbol, c.statement_format, c.report_date, c.publish_date
    )
    SELECT
        c.symbol, c.statement_format, c.report_date, c.publish_date,
        c.fiscal_year, c.fiscal_quarter, c.period_type, c.months_in_period,
        c.total_assets, c.total_liabilities, c.parent_equity, c.total_owner_equity,
        y.total_assets AS prior_year_total_assets,
        y.parent_equity AS prior_year_parent_equity,
        CASE WHEN c.total_assets > 0 AND y.total_assets > 0
             THEN (c.total_assets + y.total_assets) / 2 END AS avg_total_assets,
        CASE WHEN c.parent_equity > 0 AND y.parent_equity > 0
             THEN (c.parent_equity + y.parent_equity) / 2 END AS avg_parent_equity,
        {_derived_columns()},
        p.report_date AS quarter_predecessor_report_date,
        p.publish_date AS quarter_predecessor_publish_date,
        a.report_date AS ttm_annual_report_date,
        a.publish_date AS ttm_annual_publish_date,
        y.report_date AS ttm_prior_report_date,
        y.publish_date AS ttm_prior_publish_date,
        CASE WHEN c.period_type = 'Q1' THEN TRUE
             WHEN c.period_type IN ('H1', 'Q3', 'FY') THEN p.publish_date IS NOT NULL
             ELSE FALSE END AS quarter_components_complete,
        CASE WHEN c.period_type = 'FY' THEN TRUE
             WHEN c.period_type IN ('Q1', 'H1', 'Q3')
             THEN a.publish_date IS NOT NULL AND y.publish_date IS NOT NULL
             ELSE FALSE END AS ttm_components_complete
    FROM classified c
    LEFT JOIN predecessor_keys pk USING (symbol, statement_format, report_date, publish_date)
    LEFT JOIN source p ON p.symbol = pk.symbol AND p.statement_format = pk.statement_format
        AND p.report_date = c.predecessor_date AND p.publish_date = pk.matched_publish_date
    LEFT JOIN annual_keys ak USING (symbol, statement_format, report_date, publish_date)
    LEFT JOIN source a ON a.symbol = ak.symbol AND a.statement_format = ak.statement_format
        AND a.report_date = c.annual_date AND a.publish_date = ak.matched_publish_date
    LEFT JOIN prior_keys yk USING (symbol, statement_format, report_date, publish_date)
    LEFT JOIN source y ON y.symbol = yk.symbol AND y.statement_format = yk.statement_format
        AND y.report_date = c.prior_date AND y.publish_date = yk.matched_publish_date
    """


def build_dataset(output: Path) -> dict[str, object]:
    source_glob = output / SOURCE_TABLE / "*.parquet"
    if not list((output / SOURCE_TABLE).glob("*.parquet")):
        raise FileNotFoundError(f"financial statement shards not found: {source_glob}")
    destination = output / f"{TABLE_NAME}.parquet"
    temporary = output / f".{TABLE_NAME}.building.parquet"
    temporary.unlink(missing_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("PRAGMA disable_progress_bar")
        connection.execute(
            f"COPY ({_build_query(source_glob)}) TO '{_safe_path(temporary)}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
        )
        row_count = connection.execute(
            f"SELECT COUNT(*) FROM read_parquet('{_safe_path(temporary)}')"
        ).fetchone()[0]
    finally:
        connection.close()
    os.replace(temporary, destination)
    result = {
        "database": DATABASE_ID,
        "table": TABLE_NAME,
        "pipeline_version": PIPELINE_VERSION,
        "row_count": row_count,
        "parquet": destination.name,
        "bytes": destination.stat().st_size,
    }
    manifest = output / f"_pipeline_manifest.{TABLE_NAME}.json"
    temporary_manifest = manifest.with_name(f".{manifest.name}.building")
    temporary_manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary_manifest, manifest)
    return result


def validate_dataset(output: Path) -> dict[str, object]:
    path = output / f"{TABLE_NAME}.parquet"
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = duckdb.connect(":memory:")
    try:
        row_count, null_key_rows, duplicate_groups, future_components = connection.execute(
            f"""
            SELECT COUNT(*),
              COUNT(*) FILTER (WHERE {' OR '.join(f'{field} IS NULL' for field in KEY_FIELDS)}),
              (SELECT COUNT(*) FROM (SELECT {', '.join(KEY_FIELDS)}, COUNT(*) n
                FROM read_parquet('{_safe_path(path)}') GROUP BY ALL HAVING n > 1)),
              COUNT(*) FILTER (WHERE quarter_predecessor_publish_date > publish_date
                OR ttm_annual_publish_date > publish_date OR ttm_prior_publish_date > publish_date)
            FROM read_parquet('{_safe_path(path)}')
            """
        ).fetchone()
    finally:
        connection.close()
    errors = []
    if null_key_rows:
        errors.append(f"{null_key_rows} rows have null keys")
    if duplicate_groups:
        errors.append(f"{duplicate_groups} duplicate key groups")
    if future_components:
        errors.append(f"{future_components} rows use future components")
    return {
        "row_count": row_count,
        "null_key_rows": null_key_rows,
        "duplicate_key_groups": duplicate_groups,
        "future_component_rows": future_components,
        "errors": errors,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build standardized financial periods")
    parser.add_argument("command", choices=("build", "validate"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("CURATED_DATA_ROOT", "D:/trade_data_curated"))
        / DATABASE_ID,
    )
    args = parser.parse_args(argv)
    result = build_dataset(args.output) if args.command == "build" else validate_dataset(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
