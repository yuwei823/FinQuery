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
PIPELINE_VERSION = 3
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
    "revenue_yoy",
    "parent_net_profit_yoy",
    "revenue_qoq",
    "profit_qoq",
    "revenue_cagr_3y",
    "profit_cagr_3y",
    "gross_margin_ttm",
    "ebitda_margin_ttm",
    "ev_sales_ttm",
    "ev_ebit_ttm",
    "ev_ebitda_ttm",
    "current_ratio",
    "quick_ratio",
    "debt_to_equity",
    "net_debt_to_ebitda",
    "interest_coverage",
    "dso",
    "dio",
    "dpo",
    "cash_conversion_cycle",
    "fcff_ttm",
    "fcfe_ttm",
    "roic_ttm",
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
    "total_owner_equity",
    "total_current_assets",
    "inventory",
    "prepayments",
    "total_current_liabilities",
    "preferred_shares_equity",
    "minority_interest",
    "cash_and_equivalents",
    "cash_and_equivalents_source",
    "receivables_for_turnover",
    "payables_for_turnover",
    "interest_bearing_debt",
    "operating_working_capital",
    "prior_year_operating_working_capital",
    "invested_capital",
    "avg_invested_capital",
    "avg_receivables_for_turnover",
    "avg_payables_for_turnover",
    "avg_inventory",
    "operating_revenue_ttm",
    "operating_cost_ttm",
    "operating_profit_ttm",
    "total_profit_ttm",
    "net_profit_ttm",
    "parent_net_profit_ttm",
    "operating_cash_flow_ttm",
    "interest_expense_ttm",
    "income_tax_expense_ttm",
    "depreciation_and_amortization_ttm",
    "capital_expenditure_cash_ttm",
    "net_debt_issuance_ttm",
    "operating_revenue_ytd",
    "parent_net_profit_ytd",
    "operating_revenue_quarter",
    "parent_net_profit_quarter",
    "yoy_base_report_date",
    "yoy_base_publish_date",
    "operating_revenue_yoy_base",
    "parent_net_profit_yoy_base",
    "operating_revenue_yoy_change",
    "parent_net_profit_yoy_change",
    "qoq_base_report_date",
    "qoq_base_publish_date",
    "operating_revenue_qoq_base",
    "parent_net_profit_qoq_base",
    "operating_revenue_qoq_change",
    "parent_net_profit_qoq_change",
    "cagr_base_report_date",
    "cagr_base_publish_date",
    "operating_revenue_cagr_3y_base",
    "parent_net_profit_cagr_3y_base",
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
    WITH periods AS (
        SELECT * FROM read_parquet('{_safe_path(period_path)}')
    ),
    prepared_periods AS (
        SELECT *,
          report_date - INTERVAL 1 YEAR AS yoy_date,
          CASE period_type
            WHEN 'Q1' THEN MAKE_DATE(YEAR(report_date) - 1, 12, 31)
            WHEN 'H1' THEN MAKE_DATE(YEAR(report_date), 3, 31)
            WHEN 'Q3' THEN MAKE_DATE(YEAR(report_date), 6, 30)
            WHEN 'FY' THEN MAKE_DATE(YEAR(report_date), 9, 30)
          END AS qoq_date,
          report_date - INTERVAL 3 YEAR AS cagr_date
        FROM periods
    ),
    enriched_periods AS (
        SELECT c.* EXCLUDE (yoy_date, qoq_date, cagr_date),
          y.report_date AS yoy_base_report_date,
          y.publish_date AS yoy_base_publish_date,
          y.operating_revenue_ytd AS operating_revenue_yoy_base,
          y.parent_net_profit_ytd AS parent_net_profit_yoy_base,
          c.operating_revenue_ytd - y.operating_revenue_ytd
            AS operating_revenue_yoy_change,
          c.parent_net_profit_ytd - y.parent_net_profit_ytd
            AS parent_net_profit_yoy_change,
          prior_q.report_date AS qoq_base_report_date,
          prior_q.publish_date AS qoq_base_publish_date,
          prior_q.operating_revenue_quarter AS operating_revenue_qoq_base,
          prior_q.parent_net_profit_quarter AS parent_net_profit_qoq_base,
          c.operating_revenue_quarter - prior_q.operating_revenue_quarter
            AS operating_revenue_qoq_change,
          c.parent_net_profit_quarter - prior_q.parent_net_profit_quarter
            AS parent_net_profit_qoq_change,
          cagr.report_date AS cagr_base_report_date,
          cagr.publish_date AS cagr_base_publish_date,
          cagr.operating_revenue_ttm AS operating_revenue_cagr_3y_base,
          cagr.parent_net_profit_ttm AS parent_net_profit_cagr_3y_base
        FROM prepared_periods c
        ASOF LEFT JOIN periods y
          ON c.symbol = y.symbol
         AND c.statement_format = y.statement_format
         AND c.yoy_date = y.report_date
         AND c.publish_date >= y.publish_date
        ASOF LEFT JOIN periods prior_q
          ON c.symbol = prior_q.symbol
         AND c.statement_format = prior_q.statement_format
         AND c.qoq_date = prior_q.report_date
         AND c.publish_date >= prior_q.publish_date
        ASOF LEFT JOIN periods cagr
          ON c.symbol = cagr.symbol
         AND c.statement_format = cagr.statement_format
         AND c.cagr_date = cagr.report_date
         AND c.publish_date >= cagr.publish_date
    ),
    periods_with_current_report AS (
        SELECT *,
          MAX(report_date) OVER (
            PARTITION BY symbol ORDER BY publish_date
            RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS current_report_date
        FROM enriched_periods
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
          f.total_owner_equity,
          f.total_current_assets,
          f.inventory,
          f.prepayments,
          f.total_current_liabilities,
          f.preferred_shares_equity,
          f.minority_interest,
          f.cash_and_equivalents,
          f.cash_and_equivalents_source,
          f.receivables_for_turnover,
          f.payables_for_turnover,
          f.interest_bearing_debt,
          f.operating_working_capital,
          f.prior_year_operating_working_capital,
          f.invested_capital,
          f.avg_invested_capital,
          f.avg_receivables_for_turnover,
          f.avg_payables_for_turnover,
          f.avg_inventory,
          f.operating_revenue_ttm,
          f.operating_cost_ttm,
          f.operating_profit_ttm,
          f.total_profit_ttm,
          f.net_profit_ttm,
          f.parent_net_profit_ttm,
          f.operating_cash_flow_ttm,
          f.interest_expense_ttm,
          f.income_tax_expense_ttm,
          f.depreciation_and_amortization_ttm,
          f.capital_expenditure_cash_ttm,
          f.net_debt_issuance_ttm,
          f.operating_revenue_ytd,
          f.parent_net_profit_ytd,
          f.operating_revenue_quarter,
          f.parent_net_profit_quarter,
          f.yoy_base_report_date,
          f.yoy_base_publish_date,
          f.operating_revenue_yoy_base,
          f.parent_net_profit_yoy_base,
          f.operating_revenue_yoy_change,
          f.parent_net_profit_yoy_change,
          f.qoq_base_report_date,
          f.qoq_base_publish_date,
          f.operating_revenue_qoq_base,
          f.parent_net_profit_qoq_base,
          f.operating_revenue_qoq_change,
          f.parent_net_profit_qoq_change,
          f.cagr_base_report_date,
          f.cagr_base_publish_date,
          f.operating_revenue_cagr_3y_base,
          f.parent_net_profit_cagr_3y_base
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
              COUNT(*) FILTER (WHERE yoy_base_publish_date > financial_publish_date
                OR qoq_base_publish_date > financial_publish_date
                OR cagr_base_publish_date > financial_publish_date) AS future_comparison_rows,
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
    row_count, null_key_rows, future_rows, future_comparison_rows, *formula_counts = summary
    formula_mismatches = dict(zip(METRIC_IDS, formula_counts))
    errors: list[str] = []
    if null_key_rows:
        errors.append(f"{null_key_rows} rows have null keys")
    if duplicate_groups:
        errors.append(f"{duplicate_groups} duplicate key groups")
    if future_rows:
        errors.append(f"{future_rows} rows use future financial data")
    if future_comparison_rows:
        errors.append(f"{future_comparison_rows} rows use future comparison data")
    if report_date_regressions:
        errors.append(f"{report_date_regressions} financial report date regressions")
    if any(formula_counts):
        errors.append(f"formula mismatches: {formula_mismatches}")
    return {
        "row_count": row_count,
        "null_key_rows": null_key_rows,
        "duplicate_key_groups": duplicate_groups,
        "future_financial_rows": future_rows,
        "future_comparison_rows": future_comparison_rows,
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
