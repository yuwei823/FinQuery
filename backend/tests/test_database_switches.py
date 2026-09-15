from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings, parse_string_set
from app.database import ACTIVE_DATABASES, SYNONYMS, load_database_catalog
from app.database_sources import DatabaseSource
from app.retrieval.service import SchemaIndex


class DatabaseSwitchesTest(unittest.TestCase):
    def test_parse_database_switches_as_string_set(self) -> None:
        self.assertEqual(
            parse_string_set(" short_video_ops,other,short_video_ops "),
            {"short_video_ops", "other"},
        )
        with patch.dict(os.environ, {"DATABASE_SWITCHES": "alpha,beta,alpha"}):
            self.assertEqual(Settings().database_switches, {"alpha", "beta"})

    def test_default_database_switch(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings().database_switches, {"short_video_ops"})

    def test_empty_and_unknown_database_switches_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要包含一个"):
            load_database_catalog(set())
        with self.assertRaisesRegex(ValueError, "未知数据库"):
            load_database_catalog({"missing_database"})

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
            self.assertEqual(role_tables["growth_ops"], frozenset({"second.items"}))

    def test_active_synonyms_and_cache_are_database_scoped(self) -> None:
        self.assertEqual(ACTIVE_DATABASES, frozenset({"short_video_ops"}))
        self.assertIn("short_video_ops.growth_daily_metrics.daily_active_users", SYNONYMS)
        index = SchemaIndex(index_path=None)
        self.assertEqual(index.index_path.name, "schema_store.short_video_ops.json")

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
            "role_tables": {"growth_ops": ["items"]},
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
