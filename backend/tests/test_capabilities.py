import unittest

from app.capabilities import render_capability_manifest
from app.security import AccessScope

ALL_TABLES = frozenset({
    "trade_data.stock_daily",
    "trade_data.financial_statement",
    "trade_data.index_daily",
    "trade_data.stock_etf_trading_data",
})


def make_scope(tables: frozenset[str]) -> AccessScope:
    return AccessScope(
        user_id="tester",
        roles=("market_analyst",),
        allowed_databases=frozenset({"trade_data"}),
        allowed_tables=tables,
    )


class CapabilityManifestTest(unittest.TestCase):
    def test_full_scope_lists_scenario_tables_and_coverage(self) -> None:
        manifest = render_capability_manifest(make_scope(ALL_TABLES))

        self.assertIn("trade_data", manifest)
        self.assertIn("日线行情", manifest)
        self.assertIn("股票日行情", manifest)
        self.assertIn("主要指数日行情", manifest)
        self.assertIn("ETF基金日行情", manifest)
        self.assertIn("股票财务报表", manifest)
        self.assertIn("时间覆盖", manifest)
        self.assertIn("示例问法", manifest)

    def test_partial_scope_hides_unauthorized_tables(self) -> None:
        manifest = render_capability_manifest(
            make_scope(frozenset({"trade_data.stock_daily"}))
        )

        self.assertIn("股票日行情", manifest)
        self.assertNotIn("主要指数日行情", manifest)
        self.assertNotIn("ETF基金日行情", manifest)
        self.assertNotIn("股票财务报表", manifest)

    def test_empty_scope_reveals_nothing(self) -> None:
        manifest = render_capability_manifest(make_scope(frozenset()))

        self.assertIn("暂无可查询的数据表", manifest)
        self.assertNotIn("股票日行情", manifest)
        self.assertNotIn("trade_data：", manifest)

    def test_manifest_is_cached_per_scope(self) -> None:
        scope = make_scope(ALL_TABLES)

        self.assertIs(
            render_capability_manifest(scope),
            render_capability_manifest(scope),
        )


if __name__ == "__main__":
    unittest.main()
