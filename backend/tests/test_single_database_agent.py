from __future__ import annotations

import json
import unittest

from app.querying.single_database_agent import SingleDatabaseAgent
from app.skills import SkillDefinition


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


if __name__ == "__main__":
    unittest.main()
