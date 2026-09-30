import unittest

from app.config import settings
from app.errors import PipelineStageError
from app.models import AnalysisReport
from app.querying.data_qa_agent import DataQaResult
from app.workflows.progress import ProgressBus
from app.workflows.query_graph import QueryWorkflow
from app.workflows.result_builder import ResultBuilder


def make_state(presentation: str, success: bool = True, rows: list | None = None) -> dict:
    return {
        "task_id": "task-1",
        "query": "查询销售额并绘制柱状图",
        "intent": {"action": "database_query", "presentation": presentation},
        "mcp_execution": {
            "success": success,
            "sql": "SELECT region, total FROM sales",
            "columns": ["region", "total"],
            "rows": rows if rows is not None else [{"region": "华东", "total": 100}],
        },
        "result": {
            "task_id": "task-1",
            "result_title": "销售额结果",
            "analysis": "华东领先",
            "steps": ["通过MCP数据库工具调用DuckDB并整理结果"],
        },
        "access_scope": {},
    }


def make_workflow(agent: object) -> QueryWorkflow:
    workflow = QueryWorkflow.__new__(QueryWorkflow)
    workflow.progress = ProgressBus()
    workflow.config = settings
    workflow.data_qa_agent = agent
    return workflow


class StubChartAgent:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def run(self, query: str, contexts: dict, access_scope: dict) -> DataQaResult:
        self.queries.append(query)
        report = AnalysisReport(title="销售额图表", markdown="见图", visualizations=[])
        return DataQaResult(
            action="report",
            answer="见图",
            report=report,
            tool_calls=[{"tool": "build_bar_chart", "arguments": {}, "result": {}}],
        )


class FailingChartAgent:
    def run(self, query: str, contexts: dict, access_scope: dict) -> DataQaResult:
        raise PipelineStageError("qa_answer", "图表生成失败")


class AnswerOnlyChartAgent:
    def run(self, query: str, contexts: dict, access_scope: dict) -> DataQaResult:
        return DataQaResult(action="answer", answer="无法生成图表")


class AfterExecuteTest(unittest.TestCase):
    def test_chart_request_with_rows_enters_visualize(self) -> None:
        self.assertEqual(QueryWorkflow._after_execute(make_state("chart")), "visualize_result")
        self.assertEqual(QueryWorkflow._after_execute(make_state("report")), "visualize_result")

    def test_plain_query_goes_to_end(self) -> None:
        self.assertEqual(QueryWorkflow._after_execute(make_state("none")), "end")

    def test_failed_or_empty_execution_skips_visualize(self) -> None:
        self.assertEqual(
            QueryWorkflow._after_execute(make_state("chart", success=False)), "end"
        )
        self.assertEqual(QueryWorkflow._after_execute(make_state("chart", rows=[])), "end")


class AttachReportTest(unittest.TestCase):
    def test_report_is_merged_into_result(self) -> None:
        agent = StubChartAgent()
        result = make_state("chart")["result"]

        merged = ResultBuilder.attach_report(result, agent.run("q", {}, {}))

        self.assertEqual(merged["report"]["title"], "销售额图表")
        self.assertEqual(len(merged["report_tool_calls"]), 1)
        self.assertIn("生成图表", merged["steps"][-1])
        self.assertNotIn("report", result)

    def test_answer_only_keeps_result_unchanged(self) -> None:
        result = make_state("chart")["result"]

        merged = ResultBuilder.attach_report(result, AnswerOnlyChartAgent().run("q", {}, {}))

        self.assertIs(merged, result)


class VisualizeNodeTest(unittest.TestCase):
    def test_report_is_attached_using_original_query(self) -> None:
        agent = StubChartAgent()
        workflow = make_workflow(agent)

        update = workflow._visualize_result(make_state("chart"))

        self.assertEqual(agent.queries, ["查询销售额并绘制柱状图"])
        self.assertEqual(update["result"]["report"]["title"], "销售额图表")

    def test_agent_failure_degrades_to_table_only(self) -> None:
        workflow = make_workflow(FailingChartAgent())
        state = make_state("chart")

        update = workflow._visualize_result(state)

        self.assertNotIn("report", update["result"])
        self.assertEqual(update["result"]["result_title"], "销售额结果")
        self.assertEqual(update["execution_log"][-1]["stage"], "qa_answer")
        self.assertFalse(update["execution_log"][-1]["success"])


if __name__ == "__main__":
    unittest.main()
