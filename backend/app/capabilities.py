from __future__ import annotations

"""按用户权限把已启用数据库渲染成预处理器的"能力清单"文本。"""

from .database import ACTIVE_DATABASES, DATABASE_META, SCHEMA
from .security import AccessScope

_DESCRIPTION_LIMIT = 60
_EMPTY_MANIFEST = "当前账号暂无可查询的数据表。"

_cache: dict[tuple[tuple[str, ...], tuple[str, ...]], str] = {}


def render_capability_manifest(scope: AccessScope) -> str:
    """返回该用户可见数据库能力的紧凑文本；结果按权限范围缓存。"""
    key = (tuple(sorted(scope.allowed_databases)), tuple(sorted(scope.allowed_tables)))
    cached = _cache.get(key)
    if cached is None:
        cached = _build(scope)
        _cache[key] = cached
    return cached


def _build(scope: AccessScope) -> str:
    visible = [
        table
        for table in SCHEMA
        if scope.allows_table(str(table.get("database") or ""), str(table["id"]))
    ]
    if not visible:
        return _EMPTY_MANIFEST

    lines: list[str] = []
    for database in sorted(ACTIVE_DATABASES):
        tables = [table for table in visible if str(table.get("database")) == database]
        if not tables:
            continue
        meta = DATABASE_META.get(database) or {}
        scenario = str(meta.get("scenario") or "")
        lines.append(f"数据库 {database}：{scenario}" if scenario else f"数据库 {database}")
        time_coverage = str(meta.get("time_coverage") or "")
        if time_coverage:
            lines.append(f"时间覆盖：{time_coverage}")
        for table in tables:
            label = str(table.get("label") or table["id"])
            domain = str(table.get("domain") or "")
            description = str(table.get("description") or "")
            if len(description) > _DESCRIPTION_LIMIT:
                description = description[:_DESCRIPTION_LIMIT] + "…"
            prefix = f"- {label}（{domain}）" if domain else f"- {label}"
            lines.append(f"{prefix}：{description}" if description else prefix)
        examples = [str(item) for item in meta.get("example_questions") or [] if str(item).strip()]
        if examples:
            lines.append("示例问法：" + "；".join(examples))
    return "\n".join(lines)
