from __future__ import annotations

import unittest

from app.mcp_runtime.tools.entity_tools import build_stock_entity_resolver
from app.querying.models import SqlExecution
from app.security import AccessController


class _FakeEngine:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, database: str, sql: str, access_scope: object) -> SqlExecution:
        self.sql = sql
        return SqlExecution(
            sql=sql,
            success=True,
            columns=["symbol", "stock_name", "latest_trade_date"],
            rows=[{
                "symbol": "sh600519",
                "stock_name": "贵州茅台",
                "latest_trade_date": "2026-10-16",
            }],
        )


class StockEntityResolverTest(unittest.TestCase):
    def test_resolves_name_from_local_stock_daily_without_model_conversion(self) -> None:
        engine = _FakeEngine()
        resolver = build_stock_entity_resolver(
            engine,  # type: ignore[arg-type]
            AccessController().resolve(None),
        )

        result = resolver("贵州茅台")

        self.assertEqual(result.matches[0].symbol, "sh600519")
        self.assertIn("FROM stock_daily", engine.sql)
        self.assertIn("stock_name = '贵州茅台'", engine.sql)
        self.assertNotIn("600519.SH", engine.sql)

    def test_escapes_quotes_and_like_wildcards(self) -> None:
        engine = _FakeEngine()
        resolver = build_stock_entity_resolver(
            engine,  # type: ignore[arg-type]
            AccessController().resolve(None),
        )

        resolver("A'B%_")

        self.assertIn("A''B", engine.sql)
        self.assertIn(r"\%", engine.sql)
        self.assertIn(r"\_", engine.sql)


if __name__ == "__main__":
    unittest.main()
