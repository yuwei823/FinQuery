from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.querying.duckdb_engine import DuckDbEngine
from app.retrieval.graph import SchemaGraphBuilder
from app.retrieval.service import SchemaIndex
from scripts.stock_daily_pipeline import (
    COLUMNS,
    EXPECTED_HEADER,
    compact_dataset,
    convert_dataset,
    inventory,
    validate_dataset,
)
from scripts.index_daily_pipeline import SPEC as INDEX_SPEC
from scripts.financial_statement_pipeline import SPEC as FINANCIAL_SPEC
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


class TradeDataPipelineTest(unittest.TestCase):
    def test_schema_matches_converter_columns(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        fields = schema["tables"][0]["fields"]
        self.assertEqual(schema["database"], "trade_data")
        self.assertEqual(
            [field["name"] for field in fields],
            [column.target for column in COLUMNS],
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
            [field["name"] for field in financial_table["fields"]],
            [column.target for column in FINANCIAL_SPEC.columns],
        )
        self.assertIn("financial_statement", schema["role_tables"]["market_analyst"])

    def test_schema_only_index_does_not_scan_full_parquet_table(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        table = schema["tables"][0]
        documents: list[dict] = []
        index = object.__new__(SchemaIndex)

        index._append_table_documents(documents, None, table)

        self.assertEqual(table["profile_mode"], "schema_only")
        self.assertEqual(len(documents), len(COLUMNS))
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

            validation = validate_dataset(output)
            self.assertEqual(validation["errors"], [])
            self.assertEqual(validation["parquet_files"], 2)
            self.assertEqual(validation["row_count"], 4)

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
