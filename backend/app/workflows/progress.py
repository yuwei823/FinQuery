from __future__ import annotations

import queue
import threading
import time
from typing import Any

# 查询进度的阶段常量，前端按此渲染阶段清单。
STAGE_SUBMITTED = "submitted"
STAGE_PREPROCESSING = "preprocessing"
STAGE_RESPONDING = "responding"
STAGE_ANALYZING = "analyzing"
STAGE_RETRIEVING = "retrieving_schema"
STAGE_PLANNING_SQL = "planning_sql"
STAGE_SQL_READY = "sql_ready"
STAGE_EXECUTING = "executing_query"
STAGE_FINALIZING = "finalizing"
STAGE_FAILED = "failed"


class ProgressBus:
    """按任务分发的进程内进度事件总线，供 SSE 订阅。"""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._aliases: dict[str, str] = {}
        self._lock = threading.Lock()

    def subscribe(self, task_id: str) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(task_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, task_id: str, subscriber: queue.Queue) -> None:
        with self._lock:
            listeners = self._subscribers.get(task_id)
            if listeners and subscriber in listeners:
                listeners.remove(subscriber)
            if listeners == []:
                del self._subscribers[task_id]
            self._aliases = {source: target for source, target in self._aliases.items() if target != task_id}

    def alias(self, source_task_id: str, target_task_id: str) -> None:
        """澄清续跑沿用旧 task_id，把旧任务的事件转发给新订阅者。"""
        with self._lock:
            self._aliases[source_task_id] = target_task_id

    def emit(self, task_id: str, stage: str, message: str, detail: str = "") -> None:
        with self._lock:
            resolved = self._aliases.get(task_id, task_id)
            listeners = list(self._subscribers.get(resolved, []))
        if not listeners:
            return
        event: dict[str, Any] = {
            "task_id": resolved,
            "stage": stage,
            "message": message,
            "detail": detail,
            "ts": time.time(),
        }
        for listener in listeners:
            listener.put(("progress", event))
