from __future__ import annotations

import json
import unittest

import sqlglot

from app.querying.single_database_agent import SingleDatabaseAgent
from app.skills import SkillDefinition
from app.errors import PipelineStageError


def _contract(*, filters: list[dict] | None = None) -> dict:
    return {
        "grain": "实体排行",
        "source_tables": ["stock_daily"],
        "filters": filters or [],
        "metrics": ["close"],
        "output_columns": ["close"],
    }


class _FakeModel:
    """第一次返回会失败的 SQL，第二次返回成功 SQL，并记录收到的 payload。"""

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def chat_json(self, system: str, user: str) -> dict:
        payload = json.loads(user)
        self.payloads.append(payload)
        attempt = len(self.payloads)
        sql = (
            "SELECT not_a_column FROM stock_daily"
            if attempt == 1
            else "SELECT close FROM stock_daily"
        )
        return {
            "action": "call_tool",
            "tool_name": "query_trade_data",
            "arguments": {"sql": sql},
            "query_contract": _contract(),
            "reason": "测试",
        }


class _FakeMcpClient:
    def __init__(self) -> None:
        self.calls = 0

    def list_tools(self) -> list[dict]:
        return [{"name": "query_trade_data", "description": "查询", "inputSchema": {}}]

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"success": False, "error": "column not found"}
        return {
            "success": True,
            "sql": arguments["sql"],
            "columns": ["close"],
            "rows": [{"close": 10.5}],
        }


class SingleDatabaseAgentRetryTest(unittest.TestCase):
    def test_retry_after_sql_failure_uses_slim_payload(self) -> None:
        model = _FakeModel()
        agent = SingleDatabaseAgent(
            model,
            lambda _scope: _FakeMcpClient(),
            SkillDefinition(
                name="database_query",
                description="",
                instructions="",
                allowed_tools=("query_*",),
                max_tool_calls=3,
                output_actions=("call_tool", "clarify"),
            ),
        )

        result = agent.prepare(
            "查询收盘价",
            "trade_data",
            {"tables": [], "fields": [], "joins": []},
            "表结构文本",
            {"selected_fields": [], "low_confidence_candidates": [{"field": "x"}]},
            {},
            {},
        )

        self.assertEqual(result["action"], "executed")
        self.assertEqual(len(model.payloads), 2)

        first, second = model.payloads
        self.assertIn("mcp_tools", first)
        self.assertIn("low_confidence_candidates", first.get("retrieval", {}))

        # 修正调用不带工具目录和低置信候选，但保留校验所需的 selected_fields。
        self.assertNotIn("mcp_tools", second)
        self.assertNotIn("low_confidence_candidates", second.get("retrieval", {}))
        self.assertIn("selected_fields", second.get("retrieval", {}))
        self.assertEqual(second["schema_text"], "表结构文本")
        self.assertTrue(second["tool_results"])


class _SequenceModel:
    def __init__(self, decisions: list[dict]) -> None:
        self.decisions = decisions
        self.payloads: list[dict] = []

    def chat_json(self, system: str, user: str) -> dict:
        self.payloads.append(json.loads(user))
        index = min(len(self.payloads) - 1, len(self.decisions) - 1)
        return self.decisions[index]


class _SuccessMcpClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def list_tools(self) -> list[dict]:
        return [
            {"name": "resolve_stock_entity", "description": "解析股票", "inputSchema": {}},
            {"name": "query_trade_data", "description": "查询", "inputSchema": {}},
        ]

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.calls.append({"tool": tool_name, "arguments": arguments})
        if tool_name == "resolve_stock_entity":
            return {
                "query": arguments["name"],
                "matches": [{
                    "symbol": "sh600519",
                    "stock_name": "贵州茅台",
                    "latest_trade_date": "2026-10-16",
                }],
                "error": None,
            }
        return {
            "success": True,
            "sql": arguments["sql"],
            "columns": ["symbol"],
            "rows": [{"symbol": "sh600000"}],
        }


class SingleDatabaseAgentSemanticContractTest(unittest.TestCase):
    @staticmethod
    def _agent(model: _SequenceModel, client: _SuccessMcpClient) -> SingleDatabaseAgent:
        return SingleDatabaseAgent(
            model,
            lambda _scope: client,
            SkillDefinition(
                name="database_query",
                description="",
                instructions="",
                allowed_tools=("resolve_stock_entity", "query_*"),
                max_tool_calls=3,
                output_actions=("call_tool", "clarify"),
            ),
        )

    @staticmethod
    def _decision(sql: str, filters: list[dict]) -> dict:
        contract = _contract(filters=filters)
        contract["source_tables"] = ["stock_financial_daily"]
        contract["metrics"] = ["roic_ttm"]
        contract["output_columns"] = ["symbol", "roic_ttm"]
        return {
            "action": "call_tool",
            "tool_name": "query_trade_data",
            "arguments": {"sql": sql},
            "query_contract": contract,
            "reason": "测试显式条件",
        }

    def test_repairs_missing_latest_date_and_statement_format_before_execution(self) -> None:
        invalid = self._decision(
            "SELECT symbol, roic_ttm FROM stock_financial_daily "
            "WHERE roic_ttm > 0.1 ORDER BY roic_ttm DESC LIMIT 20",
            [],
        )
        valid = self._decision(
            "SELECT symbol, roic_ttm FROM stock_financial_daily "
            "WHERE trade_date = (SELECT MAX(trade_date) FROM stock_financial_daily) "
            "AND statement_format = '一般企业' AND roic_ttm > 0.1 "
            "ORDER BY roic_ttm DESC, symbol ASC LIMIT 20",
            [
                {
                    "phrase": "最新交易日",
                    "field": "trade_date",
                    "operator": "=",
                    "value": "MAX(trade_date)",
                },
                {
                    "phrase": "一般企业",
                    "field": "statement_format",
                    "operator": "=",
                    "value": "一般企业",
                },
            ],
        )
        model = _SequenceModel([invalid, valid])
        client = _SuccessMcpClient()

        result = self._agent(model, client).prepare(
            "查询一般企业，按ROIC排序",
            "trade_data",
            {"tables": [], "fields": [], "joins": []},
            "表结构文本",
            {"hits": [], "low_confidence_candidates": []},
            {},
            {},
            original_query="查询最新交易日的一般企业，按ROIC排序",
        )

        self.assertEqual(result["action"], "executed")
        self.assertEqual(len(model.payloads), 2)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("output_validation_error", model.payloads[1])
        self.assertIn("MAX(trade_date)", client.calls[0]["arguments"]["sql"])
        self.assertIn("statement_format = '一般企业'", client.calls[0]["arguments"]["sql"])

    def test_order_by_latest_date_does_not_satisfy_global_date_filter(self) -> None:
        invalid = self._decision(
            "SELECT symbol, roic_ttm FROM stock_financial_daily "
            "ORDER BY trade_date DESC LIMIT 20",
            [{
                "phrase": "最新交易日",
                "field": "trade_date",
                "operator": "order by",
                "value": "最新",
            }],
        )
        model = _SequenceModel([invalid])
        client = _SuccessMcpClient()

        with self.assertRaises(PipelineStageError) as caught:
            self._agent(model, client).prepare(
                "查询最新交易日的股票",
                "trade_data",
                {"tables": [], "fields": [], "joins": []},
                "表结构文本",
                {"hits": [], "low_confidence_candidates": []},
                {},
                {},
            )

        self.assertIn("MAX(trade_date)", str(caught.exception))
        self.assertEqual(len(client.calls), 0)

    def test_fixed_date_query_is_not_forced_to_use_latest_date(self) -> None:
        decision = self._decision(
            "SELECT symbol, roic_ttm FROM stock_financial_daily "
            "WHERE trade_date = DATE '2026-10-15' ORDER BY roic_ttm DESC LIMIT 20",
            [{
                "phrase": "2026-10-15",
                "field": "trade_date",
                "operator": "=",
                "value": "2026-10-15",
            }],
        )
        model = _SequenceModel([decision])
        client = _SuccessMcpClient()

        result = self._agent(model, client).prepare(
            "查询2026-10-15的股票",
            "trade_data",
            {"tables": [], "fields": [], "joins": []},
            "表结构文本",
            {"hits": [], "low_confidence_candidates": []},
            {},
            {},
        )

        self.assertEqual(result["action"], "executed")
        self.assertEqual(len(client.calls), 1)

    def test_resolves_stock_name_before_financial_period_query(self) -> None:
        resolve = {
            "action": "call_tool",
            "tool_name": "resolve_stock_entity",
            "arguments": {"name": "贵州茅台"},
            "reason": "目标表没有股票名称，先从本地数据解析代码",
        }
        query = self._decision(
            "SELECT report_date, publish_date FROM financial_period "
            "WHERE symbol = 'sh600519' ORDER BY report_date DESC LIMIT 1",
            [{
                "phrase": "贵州茅台",
                "field": "symbol",
                "operator": "=",
                "value": "sh600519",
            }],
        )
        query["query_contract"]["output_columns"] = ["report_date", "publish_date"]
        model = _SequenceModel([resolve, query])
        client = _SuccessMcpClient()

        result = self._agent(model, client).prepare(
            "查询贵州茅台最新一期财报",
            "trade_data",
            {"tables": [], "fields": [], "joins": []},
            "表结构文本",
            {"hits": [], "low_confidence_candidates": []},
            {},
            {},
        )

        self.assertEqual(result["action"], "executed")
        self.assertEqual([call["tool"] for call in client.calls], [
            "resolve_stock_entity",
            "query_trade_data",
        ])
        self.assertIn("sh600519", client.calls[1]["arguments"]["sql"])

    def test_repairs_recent_financial_period_shape_before_execution(self) -> None:
        graph = {
            "tables": [{"id": "trade_data.financial_period", "name": "financial_period"}],
            "fields": [
                {
                    "table_id": "trade_data.financial_period",
                    "table_name": "financial_period",
                    "name": name,
                }
                for name in (
                    "symbol",
                    "report_date",
                    "publish_date",
                    "operating_revenue_ytd",
                )
            ],
            "joins": [],
        }
        wrong_fields = self._decision(
            "SELECT report_period, disclose_date, operating_revenue_ytd "
            "FROM financial_period WHERE symbol = '600519.SH' "
            "ORDER BY report_period ASC LIMIT 12",
            [],
        )
        wrong_fields["query_contract"]["output_columns"] = [
            "report_period", "disclose_date", "operating_revenue_ytd",
        ]
        wrong_order = self._decision(
            "SELECT report_date, publish_date, operating_revenue_ytd "
            "FROM financial_period WHERE symbol = 'sh600519' "
            "ORDER BY report_date ASC LIMIT 12",
            [],
        )
        wrong_order["query_contract"]["output_columns"] = [
            "report_date", "publish_date", "operating_revenue_ytd",
        ]
        valid = self._decision(
            "SELECT report_date, publish_date, operating_revenue_ytd, "
            "operating_revenue_quarter, operating_revenue_ttm, "
            "parent_net_profit_ytd, parent_net_profit_quarter, "
            "parent_net_profit_ttm, operating_cash_flow_ttm, "
            "capital_expenditure_cash_ttm, invested_capital FROM ("
            "SELECT fp.report_date, fp.publish_date, fp.operating_revenue_ytd, "
            "fp.operating_revenue_quarter, fp.operating_revenue_ttm, "
            "fp.parent_net_profit_ytd, fp.parent_net_profit_quarter, "
            "fp.parent_net_profit_ttm, fp.operating_cash_flow_ttm, "
            "fp.capital_expenditure_cash_ttm, fp.invested_capital "
            "FROM financial_period AS fp WHERE fp.symbol = 'sh600519' "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY report_date "
            "ORDER BY publish_date DESC) = 1 "
            "ORDER BY report_date DESC LIMIT 12"
            ") recent ORDER BY report_date ASC",
            [],
        )
        valid["query_contract"]["output_columns"] = [
            "report_date", "publish_date", "operating_revenue_ytd",
            "operating_revenue_quarter", "operating_revenue_ttm",
            "parent_net_profit_ytd", "parent_net_profit_quarter",
            "parent_net_profit_ttm", "operating_cash_flow_ttm",
            "capital_expenditure_cash_ttm", "invested_capital",
        ]
        model = _SequenceModel([wrong_fields, wrong_order, valid])
        client = _SuccessMcpClient()

        result = self._agent(model, client).prepare(
            "查询贵州茅台最近12个已披露报告期，按报告期升序排列",
            "trade_data",
            graph,
            "表结构文本",
            {"hits": [], "low_confidence_candidates": []},
            {},
            {},
        )

        self.assertEqual(result["action"], "executed")
        self.assertEqual(len(model.payloads), 3)
        self.assertIn("注册Schema中不存在的字段", model.payloads[1]["output_validation_error"])
        self.assertIn("不能直接升序LIMIT", model.payloads[2]["output_validation_error"])
        self.assertEqual(len(client.calls), 1)
        self.assertIn("QUALIFY ROW_NUMBER()", client.calls[0]["arguments"]["sql"])

    def test_deterministically_repairs_repeated_simple_ascending_period_query(self) -> None:
        graph = {
            "tables": [{"id": "trade_data.financial_period", "name": "financial_period"}],
            "fields": [
                {
                    "table_id": "trade_data.financial_period",
                    "table_name": "financial_period",
                    "name": name,
                }
                for name in ("symbol", "report_date", "publish_date")
            ],
            "joins": [],
        }
        invalid = self._decision(
            "SELECT report_date, publish_date FROM financial_period "
            "WHERE symbol = 'sh600519' ORDER BY report_date ASC LIMIT 12",
            [],
        )
        invalid["query_contract"]["output_columns"] = ["report_date", "publish_date"]
        model = _SequenceModel([invalid])
        client = _SuccessMcpClient()

        result = self._agent(model, client).prepare(
            "查询贵州茅台最近12个已披露报告期，按报告期升序排列",
            "trade_data",
            graph,
            "表结构文本",
            {"hits": [], "low_confidence_candidates": []},
            {},
            {},
        )

        self.assertEqual(result["action"], "executed")
        self.assertEqual(len(model.payloads), 3)
        self.assertIn("SELECT ... FROM (SELECT ...", model.payloads[1]["output_validation_instruction"])
        self.assertEqual(len(client.calls), 1)
        repaired_sql = client.calls[0]["arguments"]["sql"]
        self.assertNotIn("SELECT *", repaired_sql)
        self.assertTrue(repaired_sql.startswith("SELECT report_date, publish_date FROM"))
        self.assertIn("QUALIFY ROW_NUMBER()", repaired_sql)
        self.assertIn("ORDER BY report_date DESC LIMIT 12", repaired_sql)
        self.assertTrue(repaired_sql.endswith("ORDER BY report_date ASC"))

    def test_repairs_missing_outer_ascending_order_after_recent_period_selection(self) -> None:
        graph = {
            "tables": [{"id": "trade_data.financial_period", "name": "financial_period"}],
            "fields": [
                {
                    "table_id": "trade_data.financial_period",
                    "table_name": "financial_period",
                    "name": name,
                }
                for name in ("symbol", "report_date", "publish_date")
            ],
            "joins": [],
        }
        missing_outer_order = self._decision(
            "SELECT report_date AS report_period, publish_date FROM ("
            "SELECT report_date, publish_date FROM financial_period "
            "WHERE symbol = 'sh600519' "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY report_date "
            "ORDER BY publish_date DESC) = 1 "
            "ORDER BY report_date DESC LIMIT 12) recent",
            [],
        )
        missing_outer_order["query_contract"]["output_columns"] = [
            "report_period", "publish_date",
        ]
        model = _SequenceModel([missing_outer_order])
        client = _SuccessMcpClient()

        result = self._agent(model, client).prepare(
            "查询贵州茅台最近12个已披露报告期，按报告期升序排列",
            "trade_data",
            graph,
            "表结构文本",
            {"hits": [], "low_confidence_candidates": []},
            {},
            {},
        )

        self.assertEqual(result["action"], "executed")
        self.assertEqual(len(model.payloads), 3)
        self.assertIn("最外层SELECT末尾", model.payloads[1]["output_validation_instruction"])
        repaired_sql = client.calls[0]["arguments"]["sql"]
        self.assertTrue(repaired_sql.endswith("ORDER BY report_period ASC"))

    def test_accepts_outer_order_by_report_date_alias_or_position(self) -> None:
        alias_order = sqlglot.parse_one(
            "SELECT report_date AS report_period FROM financial_period "
            "ORDER BY report_period ASC",
            read="duckdb",
        )
        position_order = sqlglot.parse_one(
            "SELECT report_date, publish_date FROM financial_period ORDER BY 1 ASC",
            read="duckdb",
        )

        self.assertTrue(SingleDatabaseAgent._orders_by(alias_order, "report_date", descending=False))
        self.assertTrue(SingleDatabaseAgent._orders_by(position_order, "report_date", descending=False))


if __name__ == "__main__":
    unittest.main()
