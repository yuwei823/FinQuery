from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.querying.duckdb_engine import DuckDbEngine
from app.retrieval.graph import SchemaGraphBuilder
from app.retrieval.service import SchemaIndex
from scripts.trade_data_pipeline import (
    COLUMNS,
    EXPECTED_HEADER,
    compact_dataset,
    convert_dataset,
    inventory,
    validate_dataset,
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
