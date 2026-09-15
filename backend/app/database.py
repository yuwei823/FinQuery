from __future__ import annotations

"""按 DATABASE_SWITCHES 加载本地 CSV 数据库的 Schema、关系和同义词。"""

import json
from typing import Any, Iterable

from .config import BASE_DIR, settings
from .database_sources import DatabaseSource, source_registry


DATABASE_ROOT = BASE_DIR / "data" / "databases"
DATABASE_SOURCES = source_registry(DATABASE_ROOT)


def load_database_catalog(
    enabled: Iterable[str],
    sources: dict[str, DatabaseSource] | None = None,
) -> tuple[
    frozenset[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[str]],
    dict[str, frozenset[str]],
]:
    """加载启用数据库，并验证每个数据库的 Schema 与同义词。"""
    registry = DATABASE_SOURCES if sources is None else sources
    active = frozenset(str(item).strip() for item in enabled if str(item).strip())
    if not active:
        raise ValueError("DATABASE_SWITCHES 至少需要包含一个数据库 key")
    unknown = active - set(registry)
    if unknown:
        raise ValueError(
            f"DATABASE_SWITCHES 包含未知数据库：{', '.join(sorted(unknown))}"
        )

    tables: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    synonyms: dict[str, list[str]] = {}
    role_tables: dict[str, set[str]] = {}

    for database_id in sorted(active):
        source = registry[database_id]
        if not source.schema_path.exists():
            raise FileNotFoundError(f"未找到数据库 Schema：{source.schema_path}")
        payload = json.loads(source.schema_path.read_text(encoding="utf-8"))
        declared_database = str(payload.get("database") or database_id)
        if declared_database != database_id:
            raise ValueError(
                f"Schema 数据库标识不一致：期望 {database_id}，实际 {declared_database}"
            )

        source_tables = list(payload.get("tables") or [])
        for table in source_tables:
            table.setdefault("database", database_id)
        tables.extend(source_tables)
        relations.extend(list(payload.get("relations") or []))

        field_ids = {
            f"{table['id']}.{field['name']}"
            for table in source_tables
            for field in table.get("fields", [])
        }
        invalid_synonyms = set(source.synonyms) - field_ids
        if invalid_synonyms:
            raise ValueError(
                f"数据库 {database_id} 的 SYNONYMS 包含未知字段："
                f"{', '.join(sorted(invalid_synonyms))}"
            )
        duplicates = set(synonyms) & set(source.synonyms)
        if duplicates:
            raise ValueError(f"SYNONYMS 字段重复：{', '.join(sorted(duplicates))}")
        synonyms.update(source.synonyms)

        tables_by_name = {
            str(table.get("name") or table["id"]).split(".")[-1]: str(table["id"])
            for table in source_tables
        }
        for role, names in (payload.get("role_tables") or {}).items():
            selected = role_tables.setdefault(str(role), set())
            selected.update(
                tables_by_name[str(name)]
                for name in names
                if str(name) in tables_by_name
            )

    return (
        active,
        tables,
        relations,
        synonyms,
        {role: frozenset(ids) for role, ids in role_tables.items()},
    )


ACTIVE_DATABASES, SCHEMA, RELATIONS, SYNONYMS, ROLE_TABLES = load_database_catalog(
    settings.database_switches
)
DEFAULT_DATABASE = sorted(ACTIVE_DATABASES)[0]


def physical_table_name(table: dict[str, Any]) -> str:
    return str(table.get("name") or table["id"])
