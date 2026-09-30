from __future__ import annotations

"""评测数据集加载与校验。"""

import json
from pathlib import Path
from typing import Any

CATEGORIES = frozenset({
    "chitchat",
    "out_of_scope",
    "simple_query",
    "complex_query",
    "compound",
    "clarification",
})
# 需要标注检索词与期望字段的查询类用例。
QUERY_CATEGORIES = frozenset({"simple_query", "complex_query", "compound"})
REQUIRED_COMMON = ("id", "category", "query", "expected_route")


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测数据集缺少非空 cases 数组")
    seen: set[str] = set()
    for case in cases:
        _validate_case(case)
        if case["id"] in seen:
            raise ValueError(f"评测用例 id 重复：{case['id']}")
        seen.add(case["id"])
    return cases


def _validate_case(case: dict[str, Any]) -> None:
    label = str(case.get("id") or "未知用例")
    for key in REQUIRED_COMMON:
        if not case.get(key):
            raise ValueError(f"{label}：缺少必填字段 {key}")
    category = case["category"]
    if category not in CATEGORIES:
        raise ValueError(f"{label}：未知评测类别 {category}")
    if category in QUERY_CATEGORIES:
        for key in ("retrieval_terms", "expected_tables", "expected_fields"):
            if not case.get(key):
                raise ValueError(f"{label}：查询类用例缺少 {key}")
    if case.get("golden_sql") is not None and not str(case["golden_sql"]).strip():
        raise ValueError(f"{label}：golden_sql 不能为空字符串")
