from __future__ import annotations

import unittest

from app.mcp_runtime.tools import (
    build_area_chart,
    build_candlestick_chart,
    build_heatmap,
    build_line_chart,
    build_pie_chart,
    build_scatter_chart,
)
from app.querying.data_qa_agent import DataQaAgent


class PresentationToolsTest(unittest.TestCase):
    def test_new_chart_tools_return_matching_type(self) -> None:
        line = build_line_chart("趋势", "task-1", "trade_date", "close")
        self.assertEqual(line.type, "line")
        self.assertEqual(line.category_field, "trade_date")

        area = build_area_chart("总量", "task-1", "trade_date", "turnover")
        self.assertEqual(area.type, "area")

        scatter = build_scatter_chart("关系", "task-1", "turnover", "close")
        self.assertEqual(scatter.type, "scatter")

        heatmap = build_heatmap("矩阵", "task-1", "industry", "report_date", "net_profit")
        self.assertEqual(heatmap.type, "heatmap")
        self.assertEqual(heatmap.y_field, "report_date")

        candlestick = build_candlestick_chart(
            "行情", "task-1", "trade_date", "open", "high", "low", "close"
        )
        self.assertEqual(candlestick.type, "candlestick")
        self.assertEqual(candlestick.open_field, "open")
        self.assertEqual(candlestick.close_field, "close")

    def test_pie_chart_still_works(self) -> None:
        pie = build_pie_chart("占比", "task-1", "industry", "total_market_cap")
        self.assertEqual(pie.type, "pie")
        self.assertIsNone(pie.y_field)


class ChartSourceValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = {
            "task-1": {
                "task_id": "task-1",
                "title": "行情",
                "query": "查询行情",
                "columns": ["trade_date", "open", "high", "low", "close", "industry"],
                "row_count": 10,
            }
        }

    def _validate(self, name: str, arguments: dict) -> None:
        DataQaAgent._validate_chart_source(name, arguments, self.catalog)

    def test_bar_chart_requires_existing_category_and_value(self) -> None:
        self._validate(
            "build_bar_chart",
            {"source_task_id": "task-1", "category_field": "industry", "value_field": "close"},
        )
        with self.assertRaisesRegex(ValueError, "图表字段不在查询结果中"):
            self._validate(
                "build_bar_chart",
                {"source_task_id": "task-1", "category_field": "industry", "value_field": "volume"},
            )

    def test_heatmap_requires_y_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "y_field"):
            self._validate(
                "build_heatmap",
                {
                    "source_task_id": "task-1",
                    "category_field": "industry",
                    "value_field": "close",
                },
            )
        self._validate(
            "build_heatmap",
            {
                "source_task_id": "task-1",
                "category_field": "industry",
                "y_field": "trade_date",
                "value_field": "close",
            },
        )

    def test_candlestick_requires_ohlc_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "low_field"):
            self._validate(
                "build_candlestick_chart",
                {
                    "source_task_id": "task-1",
                    "category_field": "trade_date",
                    "open_field": "open",
                    "high_field": "high",
                    "close_field": "close",
                },
            )
        self._validate(
            "build_candlestick_chart",
            {
                "source_task_id": "task-1",
                "category_field": "trade_date",
                "open_field": "open",
                "high_field": "high",
                "low_field": "low",
                "close_field": "close",
            },
        )


if __name__ == "__main__":
    unittest.main()
