from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.models import QueryResult
from app.security.auth import AuthService
from app.workflows.progress import ProgressBus


class ProgressBusTest(unittest.TestCase):
    def test_emit_reaches_subscriber_and_stops_after_unsubscribe(self) -> None:
        bus = ProgressBus()
        events = bus.subscribe("task-a")
        bus.emit("task-a", "preprocessing", "正在理解问题")
        bus.emit("task-b", "preprocessing", "其他任务")

        kind, event = events.get_nowait()
        self.assertEqual(kind, "progress")
        self.assertEqual(event["stage"], "preprocessing")
        self.assertEqual(event["task_id"], "task-a")
        self.assertTrue(events.empty())

        bus.unsubscribe("task-a", events)
        bus.emit("task-a", "finalizing", "正在整理查询结果")
        self.assertTrue(events.empty())

    def test_alias_forwards_clarification_resume_events(self) -> None:
        bus = ProgressBus()
        events = bus.subscribe("new-task")
        bus.alias("old-task", "new-task")
        bus.emit("old-task", "retrieving_schema", "正在检索相关数据表")

        _, event = events.get_nowait()
        self.assertEqual(event["task_id"], "new-task")
        self.assertEqual(event["stage"], "retrieving_schema")


class _StubService:
    """模拟服务：回放两个进度事件后返回固定结果。"""

    def __init__(self) -> None:
        self.workflow = SimpleNamespace(progress=ProgressBus())

    def submit(self, query, session_id, workspace, user_id, task_id=None):
        bus = self.workflow.progress
        bus.emit(task_id, "preprocessing", "正在理解问题")
        bus.emit(task_id, "retrieving_schema", "正在检索相关数据表")
        return QueryResult(
            task_id=task_id or "stub",
            status="completed",
            route="direct_response",
            message="ok",
        )


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        event_name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        if event_name:
            events.append((event_name, json.loads(data)))
    return events


class QueryProgressStreamTest(unittest.TestCase):
    def test_query_streams_progress_then_result(self) -> None:
        stub = _StubService()
        with patch.object(routes, "service", stub), TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": AuthService.DEFAULT_ADMIN_PASSWORD},
            )
            self.assertEqual(login.status_code, 200)
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            response = client.post(
                "/api/query",
                headers=headers,
                json={"query": "测试", "session_id": "progress-test"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers.get("x-accel-buffering"), "no")

        events = _parse_sse(response.text)
        kinds = [kind for kind, _ in events]
        self.assertEqual(kinds, ["progress", "progress", "result"])
        self.assertEqual(
            [event["stage"] for _, event in events[:2]],
            ["preprocessing", "retrieving_schema"],
        )
        self.assertEqual(events[-1][1]["status"], "completed")
        self.assertEqual(events[-1][1]["task_id"], events[0][1]["task_id"])


if __name__ == "__main__":
    unittest.main()
