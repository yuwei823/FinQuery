from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings, parse_string_set
from app.database import ACTIVE_DATABASES, SYNONYMS, load_database_catalog
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

    def test_catalog_loads_only_selected_schema_and_synonyms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self._source(root, "first", "first_alias")
            second = self._source(root, "second", "second_alias")

            active, schema, _, synonyms, role_tables = load_database_catalog(
                {"second"},
                {"first": first, "second": second},
            )

            self.assertEqual(active, frozenset({"second"}))
            self.assertEqual([table["id"] for table in schema], ["second.items"])
            self.assertEqual(synonyms, {"second.items.item_id": ["second_alias"]})
            self.assertEqual(role_tables["market_analyst"], frozenset({"second.items"}))

    def test_active_synonyms_and_cache_are_database_scoped(self) -> None:
        self.assertEqual(ACTIVE_DATABASES, frozenset({"trade_data"}))
        self.assertIn("trade_data.stock_daily.close", SYNONYMS)
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
        return DatabaseSource(
            database_id=database_id,
            folder=folder,
            synonyms={f"{database_id}.items.item_id": [alias]},
        )


if __name__ == "__main__":
    unittest.main()
