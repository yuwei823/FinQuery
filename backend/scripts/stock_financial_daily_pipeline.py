from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import duckdb


DATABASE_ID = "trade_data"
TABLE_NAME = "stock_financial_daily"
PIPELINE_VERSION = 1
METRIC_IDS = (
    "pe_parent_ttm",
    "pb_parent",
    "ps_ttm",
    "net_margin_ttm",
    "roe_ttm",
    "roa_ttm",
    "asset_turnover_ttm",
    "cfo_to_net_profit",
    "cfo_margin",
)
BASE_COLUMNS = (
    "symbol",
    "trade_date",
    "stock_name",
    "industry_level_1",
    "industry_level_2",
    "industry_level_3",
    "total_market_cap",
    "financial_report_date",
    "financial_publish_date",
    "statement_format",
    "period_type",
    "financial_data_available",
    "total_assets",
    "parent_equity",
    "avg_total_assets",
    "avg_parent_equity",
    "operating_revenue_ttm",
    "net_profit_ttm",
    "parent_net_profit_ttm",
    "operating_cash_flow_ttm",
)
OUTPUT_COLUMNS = BASE_COLUMNS + METRIC_IDS


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    expression: str
    invalid_when: str


def _safe_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _load_metrics() -> tuple[MetricSpec, ...]:
    terms_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "databases"
        / DATABASE_ID
        / "_terms.json"
    )
    registry = json.loads(terms_path.read_text(encoding="utf-8")).get(
        "derived_metric_terms", {}
    )
    metrics: list[MetricSpec] = []
    for metric_id in METRIC_IDS:
        metric = registry.get(metric_id, {})
        expected_field_id = f"{DATABASE_ID}.{TABLE_NAME}.{metric_id}"
        if metric.get("status") != "active" or metric.get("field_id") != expected_field_id:
            raise ValueError(f"派生指标注册不完整：{metric_id}")
        expression = metric.get("sql_expression")
        invalid_when = metric.get("invalid_when")
        if not expression or not invalid_when:
            raise ValueError(f"派生指标缺少公式或异常值规则：{metric_id}")
        metrics.append(MetricSpec(metric_id, expression, invalid_when))
    return tuple(metrics)


def _metric_projection(metrics: tuple[MetricSpec, ...]) -> str:
    return ",\n        ".join(
        f'{metric.expression} AS "{metric.metric_id}"' for metric in metrics
    )


def _build_query(stock_path: Path, period_path: Path, metrics: tuple[MetricSpec, ...]) -> str:
    return f"""
    WITH periods_with_current_report AS (
        SELECT *,
          MAX(report_date) OVER (
            PARTITION BY symbol ORDER BY publish_date
            RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS current_report_date
        FROM read_parquet('{_safe_path(period_path)}')
    ),
    current_report_events AS (
        SELECT *,
          ROW_NUMBER() OVER (
            PARTITION BY symbol, publish_date
            ORDER BY
              ttm_components_complete DESC NULLS LAST,
              ((operating_revenue_ttm IS NOT NULL)::INTEGER
                + (net_profit_ttm IS NOT NULL)::INTEGER
                + (parent_net_profit_ttm IS NOT NULL)::INTEGER
                + (operating_cash_flow_ttm IS NOT NULL)::INTEGER) DESC,
              (statement_format <> '一般企业') DESC,
              statement_format
          ) AS format_rank
        FROM periods_with_current_report
        WHERE report_date = current_report_date
    ),
    snapshots AS (
        SELECT * EXCLUDE (current_report_date, format_rank)
        FROM current_report_events
        WHERE format_rank = 1
    ),
    joined AS (
        SELECT
          s.symbol,
          s.trade_date,
          s.stock_name,
          s.industry_level_1,
          s.industry_level_2,
          s.industry_level_3,
          s.total_market_cap,
          f.report_date AS financial_report_date,
          f.publish_date AS financial_publish_date,
          f.statement_format,
          f.period_type,
          f.publish_date IS NOT NULL AS financial_data_available,
          f.total_assets,
          f.parent_equity,
          f.avg_total_assets,
          f.avg_parent_equity,
          f.operating_revenue_ttm,
          f.net_profit_ttm,
          f.parent_net_profit_ttm,
          f.operating_cash_flow_ttm
        FROM read_parquet('{_safe_path(stock_path)}') s
        ASOF LEFT JOIN snapshots f
          ON s.symbol = f.symbol AND s.trade_date >= f.publish_date
    )
    SELECT *,
        {_metric_projection(metrics)}
    FROM joined
    """


def build_dataset(output: Path) -> dict[str, object]:
    stock_path = output / "stock_daily.parquet"
    period_path = output / "financial_period.parquet"
    for path in (stock_path, period_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{TABLE_NAME}.parquet"
    temporary = output / f".{TABLE_NAME}.building.parquet"
    temporary.unlink(missing_ok=True)
    metrics = _load_metrics()
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("PRAGMA disable_progress_bar")
        connection.execute(
            f"COPY ({_build_query(stock_path, period_path, metrics)}) "
            f"TO '{_safe_path(temporary)}' "
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
    metrics = _load_metrics()
    mismatches = ",\n".join(
        f"COUNT(*) FILTER (WHERE {metric.metric_id} IS DISTINCT FROM "
        f"({metric.expression})) AS {metric.metric_id}_mismatches"
        for metric in metrics
    )
    connection = duckdb.connect(":memory:")
    try:
        summary = connection.execute(
            f"""
            SELECT COUNT(*) AS row_count,
              COUNT(*) FILTER (WHERE symbol IS NULL OR trade_date IS NULL) AS null_key_rows,
              COUNT(*) FILTER (WHERE financial_publish_date > trade_date) AS future_rows,
              {mismatches}
            FROM read_parquet('{_safe_path(path)}')
            """
        ).fetchone()
        duplicate_groups = connection.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT symbol, trade_date, COUNT(*) n
              FROM read_parquet('{_safe_path(path)}')
              GROUP BY 1, 2 HAVING n > 1
            )
            """
        ).fetchone()[0]
        report_date_regressions = connection.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT financial_report_date,
                LAG(financial_report_date) OVER (
                  PARTITION BY symbol ORDER BY trade_date
                ) AS previous_report_date
              FROM read_parquet('{_safe_path(path)}')
            )
            WHERE financial_report_date < previous_report_date
            """
        ).fetchone()[0]
    finally:
        connection.close()
    row_count, null_key_rows, future_rows, *formula_counts = summary
    formula_mismatches = dict(zip(METRIC_IDS, formula_counts))
    errors: list[str] = []
    if null_key_rows:
        errors.append(f"{null_key_rows} rows have null keys")
    if duplicate_groups:
        errors.append(f"{duplicate_groups} duplicate key groups")
    if future_rows:
        errors.append(f"{future_rows} rows use future financial data")
    if report_date_regressions:
        errors.append(f"{report_date_regressions} financial report date regressions")
    if any(formula_counts):
        errors.append(f"formula mismatches: {formula_mismatches}")
    return {
        "row_count": row_count,
        "null_key_rows": null_key_rows,
        "duplicate_key_groups": duplicate_groups,
        "future_financial_rows": future_rows,
        "financial_report_date_regressions": report_date_regressions,
        "formula_mismatches": formula_mismatches,
        "errors": errors,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build point-in-time daily financial metrics")
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
