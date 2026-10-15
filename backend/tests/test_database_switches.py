from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings, parse_string_set
from app.database import (
    ACTIVE_DATABASES,
    CONCEPT_TERMS,
    DERIVED_METRIC_TERMS,
    FIELD_TERMS,
    load_database_catalog,
)
from app.database_sources import DatabaseSource, source_registry
from app.retrieval.service import SchemaIndex


class DatabaseSwitchesTest(unittest.TestCase):
    def test_parse_database_switches_as_string_set(self) -> None:
        self.assertEqual(
            parse_string_set(" trade_data,other,trade_data "),
            {"trade_data", "other"},
        )
        with patch.dict(os.environ, {"DATABASE_SWITCHES": "alpha,beta,alpha"}):
            self.assertEqual(Settings().database_switches, {"alpha", "beta"})

    def test_default_database_switch(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings().database_switches, {"trade_data"})

    def test_trade_data_root_is_reported_without_exposing_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"TRADE_DATA_ROOT": temp_dir}):
                config = Settings()

            self.assertEqual(config.trade_data_path, Path(temp_dir))
            self.assertEqual(
                config.trade_data_status(),
                {"configured": True, "available": True},
            )
            self.assertNotIn(temp_dir, str(config.public_status()["trade_data"]))

    def test_trade_data_root_is_optional(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Settings()

            self.assertIsNone(config.trade_data_path)
            self.assertEqual(
                config.trade_data_status(),
                {"configured": False, "available": False},
            )

    def test_curated_data_root_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"CURATED_DATA_ROOT": temp_dir}):
                config = Settings()

            self.assertEqual(config.curated_data_path, Path(temp_dir))
            self.assertEqual(
                config.curated_data_status(),
                {"configured": True, "available": True},
            )

    def test_empty_and_unknown_database_switches_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要包含一个"):
            load_database_catalog(set())
        with self.assertRaisesRegex(ValueError, "未知数据库"):
            load_database_catalog({"missing_database"})

    def test_trade_data_uses_external_curated_query_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = source_registry(root / "schemas", root / "curated")

            self.assertEqual(
                registry["trade_data"].schema_path,
                root / "schemas" / "trade_data" / "_schema.json",
            )
            self.assertEqual(
                registry["trade_data"].query_folder,
                root / "curated" / "trade_data",
            )

    def test_catalog_loads_only_selected_schema_and_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self._source(root, "first", "first_alias")
            second = self._source(root, "second", "second_alias")

            (
                active,
                schema,
                _,
                field_terms,
                role_tables,
                meta,
                concepts,
                metrics,
            ) = load_database_catalog(
                {"second"},
                {"first": first, "second": second},
            )

            self.assertEqual(active, frozenset({"second"}))
            self.assertEqual([table["id"] for table in schema], ["second.items"])
            self.assertEqual(field_terms, {"second.items.item_id": ["second_alias"]})
            self.assertEqual(schema[0]["business_terms"], ["second业务"])
            self.assertEqual(schema[0]["fields"][0]["aliases"], ["second_alias"])
            self.assertEqual(role_tables["market_analyst"], frozenset({"second.items"}))
            self.assertEqual(
                meta["second"],
                {"scenario": "", "time_coverage": "", "example_questions": []},
            )
            self.assertEqual(concepts["second.point_in_time"]["label"], "时点值")
            self.assertEqual(metrics["second.sample_ratio"]["label"], "示例比率")

    def test_active_terms_and_cache_are_database_scoped(self) -> None:
        self.assertEqual(ACTIVE_DATABASES, frozenset({"trade_data"}))
        self.assertIn("trade_data.stock_daily.close", FIELD_TERMS)
        self.assertEqual(CONCEPT_TERMS["trade_data.trailing_twelve_months"]["label"], "滚动十二个月")
        self.assertEqual(
            DERIVED_METRIC_TERMS["trade_data.pe_ttm"]["label"],
            "滚动市盈率",
        )
        index = SchemaIndex(index_path=None)
        self.assertEqual(index.index_path.name, "schema_store.trade_data.json")

    @staticmethod
    def _source(root: Path, database_id: str, alias: str) -> DatabaseSource:
        folder = root / database_id
        folder.mkdir()
        schema = {
            "database": database_id,
            "tables": [
                {
                    "id": f"{database_id}.items",
                    "name": "items",
                    "database": database_id,
                    "fields": [{"name": "item_id"}],
                }
            ],
            "relations": [],
            "role_tables": {"market_analyst": ["items"]},
        }
        (folder / "_schema.json").write_text(
            json.dumps(schema, ensure_ascii=False),
            encoding="utf-8",
        )
        terms = {
            "schema_version": 1,
            "database": database_id,
            "table_terms": {f"{database_id}.items": [f"{database_id}业务"]},
            "field_terms": {f"{database_id}.items.item_id": [alias]},
            "concept_terms": {
                "point_in_time": {
                    "label": "时点值",
                    "aliases": ["期末值"],
                    "category": "测试",
                    "definition": "测试用概念术语",
                }
            },
            "derived_metric_terms": {
                "sample_ratio": {
                    "label": "示例比率",
                    "aliases": ["示例指标"],
                    "category": "测试",
                    "definition": "测试用派生指标术语",
                    "availability": "A",
                    "status": "planned",
                }
            },
        }
        (folder / "_terms.json").write_text(
            json.dumps(terms, ensure_ascii=False),
            encoding="utf-8",
        )
        return DatabaseSource(
            database_id=database_id,
            folder=folder,
        )


if __name__ == "__main__":
    unittest.main()
