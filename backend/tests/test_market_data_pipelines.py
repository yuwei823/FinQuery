from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from app.querying.duckdb_engine import DuckDbEngine
from app.retrieval.graph import SchemaGraphBuilder
from app.retrieval.service import SchemaIndex
from scripts.stock_daily_pipeline import (
    COLUMNS,
    DERIVED_COLUMNS,
    EXPECTED_HEADER,
    OUTPUT_HEADER,
    PIPELINE_VERSION,
    compact_dataset,
    convert_dataset,
    inventory,
    validate_dataset,
)
from scripts.index_daily_pipeline import SPEC as INDEX_SPEC
from scripts.etf_daily_pipeline import SPEC as ETF_SPEC
from scripts.financial_statement_pipeline import SPEC as FINANCIAL_SPEC
from scripts.financial_period_pipeline import (
    OUTPUT_COLUMNS as FINANCIAL_PERIOD_COLUMNS,
    build_dataset as build_financial_period,
    validate_dataset as validate_financial_period,
)
from scripts.stock_financial_daily_pipeline import (
    METRIC_IDS as STOCK_FINANCIAL_METRIC_IDS,
    OUTPUT_COLUMNS as STOCK_FINANCIAL_DAILY_COLUMNS,
    build_dataset as build_stock_financial_daily,
    validate_dataset as validate_stock_financial_daily,
)
from scripts.csv_parquet_pipeline import (
    compact_dataset as compact_configured_dataset,
    convert_dataset as convert_configured_dataset,
    inventory as inventory_configured_dataset,
    validate_dataset as validate_configured_dataset,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "databases"
    / "trade_data"
    / "_schema.json"
)
TERMS_PATH = SCHEMA_PATH.with_name("_terms.json")


class TradeDataPipelineTest(unittest.TestCase):
    def test_stock_financial_daily_is_point_in_time_and_does_not_regress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "trade_data"
            output.mkdir(parents=True)
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    """
                    CREATE TABLE stocks AS SELECT * FROM (VALUES
                      ('sh600000', DATE '2024-03-30', '样本银行', '银行', '银行Ⅱ', '股份制银行', 1000.0),
                      ('sh600000', DATE '2024-03-31', '样本银行', '银行', '银行Ⅱ', '股份制银行', 1000.0),
                      ('sh600000', DATE '2024-05-01', '样本银行', '银行', '银行Ⅱ', '股份制银行', 1200.0),
                      ('sh600000', DATE '2024-05-16', '样本银行', '银行', '银行Ⅱ', '股份制银行', 1300.0),
                      ('sh600001', DATE '2024-05-01', '样本公司', '机械设备', '通用设备', '机床工具', 1500.0)
                    ) t(symbol, trade_date, stock_name, industry_level_1,
                        industry_level_2, industry_level_3, total_market_cap)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE periods AS SELECT * FROM (VALUES
                      ('sh600000','商业银行',DATE '2021-03-31',DATE '2021-04-30','Q1',TRUE,
                       160.0,80.0,150.0,75.0,80.0,8.0,5.0,9.0,20.0,2.0,20.0,2.0),
                      ('sh600000','商业银行',DATE '2023-03-31',DATE '2023-04-30','Q1',TRUE,
                       180.0,90.0,170.0,85.0,100.0,10.0,8.0,11.0,25.0,2.5,25.0,2.5),
                      ('sh600000','商业银行',DATE '2023-12-31',DATE '2024-03-31','FY',TRUE,
                       200.0,100.0,180.0,90.0,100.0,10.0,8.0,12.0,100.0,8.0,30.0,3.0),
                      ('sh600000','商业银行',DATE '2024-03-31',DATE '2024-04-30','Q1',TRUE,
                       220.0,110.0,200.0,100.0,120.0,12.0,10.0,15.0,30.0,3.0,30.0,3.0),
                      ('sh600000','商业银行',DATE '2023-12-31',DATE '2024-05-15','FY',TRUE,
                       2000.0,1000.0,1800.0,900.0,1000.0,100.0,80.0,120.0,1000.0,80.0,300.0,30.0),
                      ('sh600001','一般企业',DATE '2023-12-31',DATE '2024-03-31','FY',TRUE,
                       300.0,100.0,280.0,90.0,200.0,20.0,18.0,25.0,200.0,18.0,50.0,5.0)
                    ) t(symbol,statement_format,report_date,publish_date,period_type,
                        ttm_components_complete,total_assets,parent_equity,avg_total_assets,
                        avg_parent_equity,operating_revenue_ttm,net_profit_ttm,
                        parent_net_profit_ttm,operating_cash_flow_ttm,
                        operating_revenue_ytd,parent_net_profit_ytd,
                        operating_revenue_quarter,parent_net_profit_quarter)
                    """
                )
                for column in (
                    "total_owner_equity",
                    "total_current_assets",
                    "inventory",
                    "prepayments",
                    "total_current_liabilities",
                    "preferred_shares_equity",
                    "minority_interest",
                    "cash_and_equivalents",
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
                    "operating_cost_ttm",
                    "operating_profit_ttm",
                    "total_profit_ttm",
                    "interest_expense_ttm",
                    "income_tax_expense_ttm",
                    "depreciation_and_amortization_ttm",
                    "capital_expenditure_cash_ttm",
                    "net_debt_issuance_ttm",
                ):
                    connection.execute(
                        f'ALTER TABLE periods ADD COLUMN "{column}" DOUBLE'
                    )
                connection.execute(
                    "ALTER TABLE periods ADD COLUMN cash_and_equivalents_source VARCHAR"
                )
                connection.execute(
                    """
                    UPDATE periods SET
                      total_owner_equity = 105,
                      total_current_assets = 100,
                      inventory = 20,
                      prepayments = 5,
                      total_current_liabilities = 50,
                      preferred_shares_equity = 2,
                      minority_interest = 3,
                      cash_and_equivalents = 10,
                      cash_and_equivalents_source = 'ending_cash_balance',
                      receivables_for_turnover = 30,
                      payables_for_turnover = 25,
                      interest_bearing_debt = 40,
                      operating_working_capital = 20,
                      prior_year_operating_working_capital = 15,
                      invested_capital = 135,
                      avg_invested_capital = 120,
                      avg_receivables_for_turnover = 25,
                      avg_payables_for_turnover = 20,
                      avg_inventory = 15,
                      operating_cost_ttm = 120,
                      operating_profit_ttm = 35,
                      total_profit_ttm = 30,
                      interest_expense_ttm = 5,
                      income_tax_expense_ttm = 6,
                      depreciation_and_amortization_ttm = 10,
                      capital_expenditure_cash_ttm = 12,
                      net_debt_issuance_ttm = 4
                    WHERE symbol = 'sh600001'
                    """
                )
                connection.execute(
                    f"COPY stocks TO '{(output / 'stock_daily.parquet').as_posix()}' (FORMAT PARQUET)"
                )
                connection.execute(
                    f"COPY periods TO '{(output / 'financial_period.parquet').as_posix()}' (FORMAT PARQUET)"
                )
            finally:
                connection.close()

            result = build_stock_financial_daily(output)
            self.assertEqual(result["row_count"], 5)
            validation = validate_stock_financial_daily(output)
            self.assertEqual(validation["errors"], [])
            self.assertEqual(validation["non_general_metric_rows"], 0)
            self.assertEqual(
                validation["metric_profiles"]["gross_margin_ttm"]["non_null_count"],
                1,
            )
            self.assertEqual(
                validation["metric_profiles"]["gross_margin_ttm"]["non_finite_count"],
                0,
            )
            connection = duckdb.connect(":memory:")
            try:
                rows = connection.execute(
                    f"SELECT trade_date, financial_report_date, pe_parent_ttm, roe_ttm, "
                    f"revenue_yoy, parent_net_profit_yoy, revenue_qoq, profit_qoq, "
                    f"revenue_cagr_3y, profit_cagr_3y "
                    f"FROM read_parquet('{(output / 'stock_financial_daily.parquet').as_posix()}') "
                    f"WHERE symbol = 'sh600000' ORDER BY trade_date"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(str(rows[0][1]), "2023-03-31")
            self.assertEqual(str(rows[1][1]), "2023-12-31")
            self.assertEqual(str(rows[2][1]), "2024-03-31")
            self.assertEqual(str(rows[3][1]), "2024-03-31")
            self.assertEqual(rows[3][2:4], (130.0, 0.1))
            self.assertAlmostEqual(rows[3][4], 0.2)
            self.assertAlmostEqual(rows[3][5], 0.2)
            self.assertEqual(rows[3][6:8], (0.0, 0.0))
            self.assertAlmostEqual(rows[3][8], (1.5 ** (1 / 3)) - 1)
            self.assertAlmostEqual(rows[3][9], (2.0 ** (1 / 3)) - 1)
            connection = duckdb.connect(":memory:")
            try:
                p2 = connection.execute(
                    f"SELECT gross_margin_ttm, ebitda_margin_ttm, ev_sales_ttm, "
                    f"ev_ebit_ttm, ev_ebitda_ttm, current_ratio, quick_ratio, "
                    f"debt_to_equity, net_debt_to_ebitda, interest_coverage, "
                    f"dso, dio, dpo, cash_conversion_cycle, fcff_ttm, fcfe_ttm, roic_ttm "
                    f"FROM read_parquet('{(output / 'stock_financial_daily.parquet').as_posix()}') "
                    f"WHERE symbol = 'sh600001'"
                ).fetchone()
                bank_p2 = connection.execute(
                    f"SELECT gross_margin_ttm, current_ratio, roic_ttm "
                    f"FROM read_parquet('{(output / 'stock_financial_daily.parquet').as_posix()}') "
                    f"WHERE symbol = 'sh600000' ORDER BY trade_date DESC LIMIT 1"
                ).fetchone()
            finally:
                connection.close()
            expected = (
                0.4,
                0.225,
                1535 / 200,
                1535 / 35,
                1535 / 45,
                2.0,
                1.6,
                0.4,
                30 / 45,
                7.0,
                25 / 200 * 365,
                15 / 120 * 365,
                20 / 120 * 365,
                25 / 200 * 365 + 15 / 120 * 365 - 20 / 120 * 365,
                21.0,
                17.0,
                28 / 120,
            )
            for actual, wanted in zip(p2, expected):
                self.assertAlmostEqual(actual, wanted)
            self.assertEqual(bank_p2, (None, None, None))

    def test_financial_period_builds_quarter_and_point_in_time_ttm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "trade_data"
            source_dir = output / "financial_statement"
            source_dir.mkdir(parents=True)
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    """
                    CREATE TABLE source AS SELECT * FROM (VALUES
                      ('sh600000','商业银行',DATE '2024-06-30',DATE '2024-08-30',1,1,1,1,40,40,40,40),
                      ('sh600000','商业银行',DATE '2024-12-31',DATE '2025-03-30',1,1,1,1,100,100,100,100),
                      ('sh600000','商业银行',DATE '2025-03-31',DATE '2025-04-30',1,1,1,1,25,25,25,25),
                      ('sh600000','商业银行',DATE '2025-06-30',DATE '2025-08-30',1,1,1,1,60,60,60,60),
                      ('sh600000','商业银行',DATE '2024-06-30',DATE '2025-09-01',1,1,1,1,400,400,400,400),
                      ('sh600000','商业银行',DATE '2024-12-31',DATE '2025-09-01',1,1,1,1,1000,1000,1000,1000)
                    ) t(symbol,statement_format,report_date,publish_date,total_assets,
                        total_liabilities,parent_equity,total_owner_equity,
                        operating_revenue,net_profit,parent_net_profit,operating_cash_flow)
                    """
                )
                existing_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info('source')").fetchall()
                }
                for column in FINANCIAL_SPEC.columns:
                    if column.target not in existing_columns:
                        connection.execute(
                            f'ALTER TABLE source ADD COLUMN "{column.target}" DOUBLE'
                        )
                connection.execute(
                    """
                    UPDATE source SET
                      ending_cash_balance = 10,
                      monetary_funds = 12,
                      notes_and_accounts_receivable = 20,
                      accounts_receivable = 200,
                      receivables_financing = 0,
                      notes_and_accounts_payable = 10,
                      inventory = 8,
                      short_term_borrowings = 5,
                      long_term_borrowings = 15,
                      depreciation_fixed_assets = 4,
                      amortization_intangible_assets = 0.5,
                      amortization_long_term_deferred_expenses = 0.2,
                      cash_proceeds_from_borrowings = 8,
                      cash_proceeds_from_bond_issuance = 2,
                      cash_repayment_of_debt = 4
                    WHERE report_date = DATE '2024-06-30'
                      AND publish_date = DATE '2024-08-30';
                    UPDATE source SET
                      depreciation_fixed_assets = 10,
                      amortization_intangible_assets = 2,
                      amortization_long_term_deferred_expenses = 1,
                      cash_proceeds_from_borrowings = 20,
                      cash_proceeds_from_bond_issuance = 5,
                      cash_repayment_of_debt = 10
                    WHERE report_date = DATE '2024-12-31'
                      AND publish_date = DATE '2025-03-30';
                    UPDATE source SET
                      ending_cash_balance = 20,
                      monetary_funds = 25,
                      notes_and_accounts_receivable = 30,
                      accounts_receivable = 300,
                      receivables_financing = 2,
                      notes_and_accounts_payable = 15,
                      notes_payable = 3,
                      accounts_payable = 7,
                      inventory = 12,
                      prepayments = 2,
                      other_receivables_total = 1,
                      contract_liabilities = 4,
                      employee_benefits_payable = 1,
                      taxes_payable = 1,
                      other_payables_total = 2,
                      short_term_borrowings = 10,
                      short_term_bonds_payable = 1,
                      current_portion_noncurrent_liabilities = 2,
                      long_term_borrowings = 20,
                      bonds_payable = 5,
                      lease_liabilities = 3,
                      depreciation_fixed_assets = 6,
                      amortization_intangible_assets = 1,
                      amortization_long_term_deferred_expenses = 0.5,
                      cash_proceeds_from_borrowings = 12,
                      cash_proceeds_from_bond_issuance = 3,
                      cash_repayment_of_debt = 6
                    WHERE report_date = DATE '2025-06-30';
                    """
                )
                connection.execute(
                    f"COPY source TO '{(source_dir / 'sample.parquet').as_posix()}' (FORMAT PARQUET)"
                )
            finally:
                connection.close()

            result = build_financial_period(output)
            self.assertEqual(result["row_count"], 6)
            self.assertEqual(validate_financial_period(output)["errors"], [])
            connection = duckdb.connect(":memory:")
            try:
                row = connection.execute(
                    f"SELECT operating_revenue_quarter, operating_revenue_ttm, "
                    f"avg_total_assets, avg_parent_equity, "
                    f"quarter_predecessor_publish_date, ttm_annual_publish_date, "
                    f"cash_and_equivalents, cash_and_equivalents_source, "
                    f"receivables_for_turnover, payables_for_turnover, "
                    f"interest_bearing_debt, operating_working_capital, "
                    f"invested_capital, avg_receivables_for_turnover, "
                    f"avg_payables_for_turnover, avg_inventory, avg_invested_capital, "
                    f"depreciation_and_amortization_ttm, net_debt_issuance_ttm "
                    f"FROM read_parquet('{(output / 'financial_period.parquet').as_posix()}') "
                    f"WHERE report_date = DATE '2025-06-30'"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[:4], (35.0, 120.0, 1.0, 1.0))
            self.assertEqual(str(row[4]), "2025-04-30")
            self.assertEqual(str(row[5]), "2025-03-30")
            self.assertEqual(row[6:13], (20.0, "ending_cash_balance", 32.0, 15.0, 41.0, 24.0, 22.0))
            self.assertEqual(row[13:17], (26.0, 12.5, 10.0, 16.5))
            self.assertAlmostEqual(row[17], 15.8)
            self.assertEqual(row[18], 18.0)

    def test_trade_data_terms_are_clean_utf8(self) -> None:
        raw = TERMS_PATH.read_bytes()
        decoded = raw.decode("utf-8", errors="strict")
        terms = json.loads(decoded)

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn("\ufffd", decoded)
        self.assertEqual(
            terms["table_terms"]["trade_data.stock_daily"][:3],
            ["股票行情", "个股行情", "股票日线"],
        )
        self.assertIn(
            "市盈率", terms["field_terms"]["trade_data.stock_daily.pe_ttm"]
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        for table in schema["tables"]:
            for field in table["fields"]:
                field_id = f"{table['id']}.{field['name']}"
                self.assertEqual(terms["field_terms"][field_id][0], field["label"])

    def test_active_metric_registry_drives_pipeline_contract(self) -> None:
        terms = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
        registry = terms["derived_metric_terms"]

        self.assertEqual(terms["schema_version"], 2)
        for column in DERIVED_COLUMNS:
            metric = registry[column.target]
            self.assertEqual(metric["status"], "active")
            self.assertEqual(
                metric["field_id"], f"trade_data.stock_daily.{column.target}"
            )
            self.assertEqual(metric["sql_expression"], column.expression)
            self.assertEqual(metric["invalid_when"], column.invalid_when)
        for metric_id in STOCK_FINANCIAL_METRIC_IDS:
            metric = registry[metric_id]
            self.assertEqual(metric["status"], "active")
            self.assertEqual(
                metric["field_id"],
                f"trade_data.stock_financial_daily.{metric_id}",
            )
            self.assertTrue(metric["sql_expression"])
            self.assertTrue(metric["invalid_when"])

    def test_schema_matches_converter_columns(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        fields = schema["tables"][0]["fields"]
        self.assertEqual(schema["database"], "trade_data")
        self.assertEqual(
            [field["name"] for field in fields],
            list(OUTPUT_HEADER),
        )

        index_table = next(
            table for table in schema["tables"] if table["name"] == "index_daily"
        )
        self.assertEqual(
            [field["name"] for field in index_table["fields"]],
            [column.target for column in INDEX_SPEC.columns],
        )
        self.assertIn("index_daily", schema["role_tables"]["market_analyst"])

        financial_table = next(
            table for table in schema["tables"] if table["name"] == "financial_statement"
        )
        self.assertEqual(
            financial_table["primary_key"],
            ["symbol", "statement_format", "report_date", "publish_date"],
        )
        self.assertEqual(
            [field["name"] for field in financial_table["fields"]],
            [column.target for column in FINANCIAL_SPEC.columns],
        )
        self.assertIn("financial_statement", schema["role_tables"]["market_analyst"])

        financial_period_table = next(
            table for table in schema["tables"] if table["name"] == "financial_period"
        )
        self.assertEqual(
            [field["name"] for field in financial_period_table["fields"]],
            list(FINANCIAL_PERIOD_COLUMNS),
        )
        self.assertIn("financial_period", schema["role_tables"]["market_analyst"])

        stock_financial_table = next(
            table for table in schema["tables"] if table["name"] == "stock_financial_daily"
        )
        self.assertEqual(
            [field["name"] for field in stock_financial_table["fields"]],
            list(STOCK_FINANCIAL_DAILY_COLUMNS),
        )
        self.assertIn("stock_financial_daily", schema["role_tables"]["market_analyst"])

        etf_table = next(
            table for table in schema["tables"] if table["name"] == "stock_etf_trading_data"
        )
        self.assertEqual(
            [field["name"] for field in etf_table["fields"]],
            [column.target for column in ETF_SPEC.columns],
        )
        self.assertIn("stock_etf_trading_data", schema["role_tables"]["market_analyst"])

    def test_schema_only_index_does_not_scan_full_parquet_table(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        table = schema["tables"][0]
        documents: list[dict] = []
        index = object.__new__(SchemaIndex)

        index._append_table_documents(documents, None, table)

        self.assertEqual(table["profile_mode"], "schema_only")
        self.assertEqual(len(documents), len(OUTPUT_HEADER))
        self.assertTrue(
            all("未在Schema索引阶段扫描全表" in item["profile"] for item in documents)
        )

    def test_schema_graph_always_includes_entity_identity_fields(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        table = schema["tables"][0]
        builder = SchemaGraphBuilder()
        builder.tables = {table["id"]: table}
        graph = builder.build(
            [
                {
                    "doc_id": "trade_data.stock_daily.close",
                    "table_id": "trade_data.stock_daily",
                    "database_id": "trade_data",
                    "field_name": "close",
                    "field_label": "收盘价",
                    "field_type": "数值",
                }
            ]
        )

        field_names = {field["name"] for field in graph["fields"]}
        self.assertIn("symbol", field_names)
        self.assertIn("stock_name", field_names)

    def test_inventory_and_incremental_parquet_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "raw"
            database_root = root / "databases"
            output = database_root / "trade_data"
            source.mkdir()
            self._write_source(source / "sh600000.csv")
            self._write_source(source / "bj920000.csv", reordered=True)

            report = inventory(source)
            self.assertEqual(report["file_count"], 2)
            self.assertEqual(report["invalid_header_count"], 0)
            self.assertEqual(report["reordered_header_count"], 1)

            first = convert_dataset(source, output, workers=2)
            self.assertEqual(first["converted_this_run"], 2)
            self.assertEqual(first["row_count"], 4)
            self.assertEqual(first["min_date"], "2026-09-16")
            self.assertEqual(first["max_date"], "2026-09-17")

            second = convert_dataset(source, output)
            self.assertEqual(second["converted_this_run"], 0)
            self.assertEqual(second["skipped_this_run"], 2)

            manifest_path = output / "_pipeline_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["sh600000.csv"].pop("pipeline_version")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            refreshed = convert_dataset(source, output)
            self.assertEqual(refreshed["pipeline_version"], PIPELINE_VERSION)
            self.assertEqual(refreshed["converted_this_run"], 1)
            self.assertEqual(refreshed["skipped_this_run"], 1)

            validation = validate_dataset(output)
            self.assertEqual(validation["errors"], [])
            self.assertEqual(validation["parquet_files"], 2)
            self.assertEqual(validation["row_count"], 4)
            self.assertTrue(
                all(count == 0 for count in validation["formula_mismatch_rows"].values())
            )

            compact = compact_dataset(output)
            self.assertEqual(compact["row_count"], 4)
            self.assertTrue((output / "stock_daily.parquet").is_file())

            engine = DuckDbEngine(database_root=database_root)
            with engine.connect("trade_data") as connection:
                rows = connection.execute(
                    "SELECT symbol, trade_date, close, is_csi_300 "
                    "FROM stock_daily ORDER BY trade_date"
                ).fetchall()
            self.assertEqual(len(rows), 4)
            self.assertEqual(str(rows[0][1]), "2026-09-16")
            self.assertIn(rows[0][0], {"bj920000", "sh600000"})
            self.assertEqual(rows[-1][2], 9.06)
            self.assertTrue(rows[0][3])

            with engine.connect("trade_data") as connection:
                metrics = connection.execute(
                    "SELECT pe_ttm, pb, pcf_ttm, earnings_yield_ttm, "
                    "liabilities_to_assets, liabilities_to_equity "
                    "FROM stock_daily WHERE symbol = 'sh600000' "
                    "ORDER BY trade_date"
                ).fetchall()
            self.assertEqual(metrics[0], (10.0, 2.0, 5.0, 0.1, 0.4, 1.6))
            self.assertEqual(metrics[1][:3], (None, None, None))
            self.assertEqual(metrics[1][3], -0.05)
            self.assertEqual(metrics[1][4:], (None, None))

    def test_index_daily_pipeline_and_duckdb_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "raw"
            database_root = root / "databases"
            output = database_root / "trade_data"
            source.mkdir()
            for index_code in ("sh000001", "sz399006"):
                with (source / f"{index_code}.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.writer(handle)
                    writer.writerow(column.source for column in INDEX_SPEC.columns)
                    writer.writerow(
                        ["2026-09-16", "100", "103", "99", "102", "5000", "300", index_code]
                    )
                    writer.writerow(
                        ["2026-09-17", "102", "104", "101", "103", "6000", "350", index_code]
                    )

            report = inventory_configured_dataset(INDEX_SPEC, source)
            self.assertEqual(report["invalid_header_count"], 0)
            first = convert_configured_dataset(INDEX_SPEC, source, output, workers=2)
            self.assertEqual(first["converted_this_run"], 2)
            second = convert_configured_dataset(INDEX_SPEC, source, output)
            self.assertEqual(second["skipped_this_run"], 2)
            validation = validate_configured_dataset(INDEX_SPEC, output)
            self.assertEqual(validation["errors"], [])
            self.assertEqual(validation["row_count"], 4)
            compact_configured_dataset(INDEX_SPEC, output)

            engine = DuckDbEngine(database_root=database_root)
            with engine.connect("trade_data") as connection:
                rows = connection.execute(
                    "SELECT index_code, trade_date, close FROM index_daily "
                    "ORDER BY index_code, trade_date"
                ).fetchall()
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0][0], "sh000001")
            self.assertEqual(rows[-1][2], 103.0)

    def test_financial_statement_pipeline_supports_nested_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "stock-fin-data-xbx"
            company = source / "sh600000"
            output = root / "trade_data"
            company.mkdir(parents=True)
            path = company / "sh600000_一般企业.csv"
            header = [column.source for column in FINANCIAL_SPEC.columns]
            header.insert(4, "抓取时间")
            values = {column.source: "1" for column in FINANCIAL_SPEC.columns}
            values.update(
                {
                    "stock_code": "sh600000",
                    "statement_format": "一般企业",
                    "report_date": "20251231",
                    "publish_date": "2026-03-31",
                }
            )
            with path.open("w", encoding="gb18030", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["数据说明"])
                writer.writerow(header)
                writer.writerow(
                    ["2026-04-01 01:00:00" if name == "抓取时间" else values[name] for name in header]
                )

            report = inventory_configured_dataset(FINANCIAL_SPEC, source)
            self.assertEqual(report["file_count"], 1)
            self.assertEqual(report["invalid_header_count"], 0)
            self.assertEqual(report["duplicate_shard_count"], 0)
            converted = convert_configured_dataset(FINANCIAL_SPEC, source, output)
            self.assertEqual(converted["converted_this_run"], 1)
            unchanged = convert_configured_dataset(FINANCIAL_SPEC, source, output)
            self.assertEqual(unchanged["skipped_this_run"], 1)
            manifest_path = output / FINANCIAL_SPEC.manifest_name
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("contract_signature")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            contract_refresh = convert_configured_dataset(
                FINANCIAL_SPEC, source, output
            )
            self.assertEqual(contract_refresh["converted_this_run"], 1)
            validation = validate_configured_dataset(FINANCIAL_SPEC, output)
            self.assertEqual(validation["errors"], [])
            compact_configured_dataset(FINANCIAL_SPEC, output)

            engine = DuckDbEngine(database_root=root)
            with engine.connect("trade_data") as connection:
                row = connection.execute(
                    "SELECT symbol, report_date, publish_date, total_assets "
                    "FROM financial_statement"
                ).fetchone()
            self.assertEqual(row[0], "sh600000")
            self.assertEqual(str(row[1]), "2025-12-31")
            self.assertEqual(str(row[2]), "2026-03-31")
            self.assertEqual(row[3], 1.0)

    def test_etf_pipeline_supports_both_adjustment_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "raw"
            output = root / "trade_data"
            source.mkdir()
            defaults = {column.source: "" for column in ETF_SPEC.columns}
            defaults.update({
                "交易日期": "2026-09-17", "基金名称": "ETF测试基金",
                "前收盘价": "1", "开盘价": "1", "最高价": "1.1",
                "最低价": "0.9", "收盘价": "1.05", "成交量": "100",
                "成交额": "105", "累计单位净值": "1.2", "单位净值": "1.1",
                "换手率": "2", "基金分类": "股票型基金", "详细分类": "指数型",
                "基金份额合计": "1000", "场内流通份额": "900",
            })
            for code, optional_name, optional_value in (
                ("510001.SH", "后复权因子", "1.3"),
                ("sh510002", "复权单位净值", "1.4"),
            ):
                header = [
                    column.source for column in ETF_SPEC.columns
                    if column.required or column.source == optional_name
                ]
                values = {**defaults, "基金代码": code, optional_name: optional_value}
                with (source / f"{code}.csv").open("w", encoding="gb18030", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["数据说明", *([""] * (len(header) - 1))])
                    writer.writerow(header)
                    writer.writerow([values[name] for name in header])

            report = inventory_configured_dataset(ETF_SPEC, source)
            self.assertEqual(report["invalid_header_count"], 0)
            convert_configured_dataset(ETF_SPEC, source, output, workers=2)
            validation = validate_configured_dataset(ETF_SPEC, output)
            self.assertEqual(validation["errors"], [])
            compact_configured_dataset(ETF_SPEC, output)

            engine = DuckDbEngine(database_root=root)
            with engine.connect("trade_data") as connection:
                rows = connection.execute(
                    "SELECT fund_code, backward_adjustment_factor, adjusted_nav "
                    "FROM stock_etf_trading_data ORDER BY fund_code"
                ).fetchall()
            self.assertEqual(rows, [("510001.SH", 1.3, None), ("sh510002", None, 1.4)])

    @staticmethod
    def _write_source(path: Path, *, reordered: bool = False) -> None:
        defaults = {column.source: "" for column in COLUMNS}
        rows = []
        for trade_date, close in (("2026-09-16", "9.10"), ("2026-09-17", "9.06")):
            row = dict(defaults)
            row.update(
                {
                    "股票代码": path.stem,
                    "股票名称": "浦发银行",
                    "交易日期": trade_date,
                    "开盘价": "9.17",
                    "最高价": "9.20",
                    "最低价": "9.00",
                    "收盘价": close,
                    "前收盘价": "9.18",
                    "成交量": "72340449.0",
                    "成交额": "656348140.0",
                    "总市值": "1000",
                    "净利润TTM": "100" if trade_date == "2026-09-16" else "-50",
                    "现金流TTM": "200" if trade_date == "2026-09-16" else "0",
                    "净资产": "500" if trade_date == "2026-09-16" else "-20",
                    "总资产": "2000" if trade_date == "2026-09-16" else "0",
                    "总负债": "800" if trade_date == "2026-09-16" else "900",
                    "沪深300成分股": "Y",
                    "新版申万一级行业名称": "银行",
                }
            )
            rows.append(row)

        with path.open("w", encoding="gb18030", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["数据说明", *([""] * (len(COLUMNS) - 1))])
            header = list(EXPECTED_HEADER)
            if reordered:
                header[29], header[31] = header[31], header[29]
            writer.writerow(header)
            for row in rows:
                writer.writerow([row[column] for column in header])


if __name__ == "__main__":
    unittest.main()
