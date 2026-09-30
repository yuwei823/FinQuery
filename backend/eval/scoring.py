from __future__ import annotations

"""离线评测的确定性指标：检索召回与结果集比对。"""

from typing import Any


def field_recall(expected_doc_ids: list[str], hits: list[dict[str, Any]]) -> float:
    """期望字段进入最终 hits 的比例。"""
    expected = set(expected_doc_ids)
    if not expected:
        return 1.0
    found = {str(hit.get("doc_id")) for hit in hits}
    return len(expected & found) / len(expected)


def table_hit_rate(expected_table_ids: list[str], hits: list[dict[str, Any]]) -> float:
    """期望表进入最终 hits 的比例。"""
    expected = set(expected_table_ids)
    if not expected:
        return 1.0
    found = {str(hit.get("table_id")) for hit in hits}
    return len(expected & found) / len(expected)


def mrr(expected_doc_ids: list[str], hits: list[dict[str, Any]]) -> float:
    """第一个期望字段在 hits 中的倒数排名。"""
    expected = set(expected_doc_ids)
    for rank, hit in enumerate(hits, 1):
        if str(hit.get("doc_id")) in expected:
            return 1.0 / rank
    return 0.0


def compare_result_sets(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    float_tol: float = 1e-6,
) -> tuple[bool, str]:
    """列名集合 + 行多重集比对，数值按容差判定，列序行序不敏感。"""
    columns = sorted(str(column) for column in expected.get("columns") or [])
    if columns != sorted(str(column) for column in actual.get("columns") or []):
        return False, (
            f"列不一致：期望 {columns}，"
            f"实际 {sorted(str(column) for column in actual.get('columns') or [])}"
        )
    expected_rows = sorted(
        (_row_key(row, columns) for row in expected.get("rows") or []), key=repr
    )
    actual_rows = sorted(
        (_row_key(row, columns) for row in actual.get("rows") or []), key=repr
    )
    if len(expected_rows) != len(actual_rows):
        return False, f"行数不一致：期望 {len(expected_rows)}，实际 {len(actual_rows)}"
    for index, (expected_row, actual_row) in enumerate(zip(expected_rows, actual_rows), 1):
        for column, (expected_kind, expected_value), (_, actual_value) in zip(
            columns, expected_row, actual_row
        ):
            if expected_kind == "num":
                if abs(expected_value - actual_value) > float_tol:
                    return False, (
                        f"第 {index} 行 {column} 数值不一致："
                        f"期望 {expected_value}，实际 {actual_value}"
                    )
            elif expected_value != actual_value:
                return False, (
                    f"第 {index} 行 {column} 不一致："
                    f"期望 {expected_value!r}，实际 {actual_value!r}"
                )
    return True, ""


def _row_key(row: Any, columns: list[str]) -> tuple[tuple[str, Any], ...]:
    if isinstance(row, dict):
        return tuple(_normalize_value(row.get(column)) for column in columns)
    return tuple(_normalize_value(value) for value in row)


def _normalize_value(value: Any) -> tuple[str, Any]:
    if isinstance(value, bool):
        return ("val", value)
    if isinstance(value, (int, float)):
        return ("num", float(value))
    if value is None:
        return ("val", None)
    return ("val", str(value))
