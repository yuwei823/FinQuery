from __future__ import annotations

"""按 DATABASE_SWITCHES 加载本地数据库的 Schema、关系和统一术语表。"""

import json
from typing import Any, Iterable

from .config import BASE_DIR, settings
from .database_sources import DatabaseSource, source_registry


DATABASE_ROOT = BASE_DIR / "data" / "databases"
DATABASE_SOURCES = source_registry(DATABASE_ROOT, settings.curated_data_path)


def _term_list(value: Any, *, target: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"术语 {target} 必须是字符串数组")
    return list(
        dict.fromkeys(str(item).strip() for item in value if str(item).strip())
    )


def load_database_catalog(
    enabled: Iterable[str],
    sources: dict[str, DatabaseSource] | None = None,
) -> tuple[
    frozenset[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[str]],
    dict[str, frozenset[str]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    """加载启用数据库，并验证 Schema 与统一术语表。"""
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
    field_terms: dict[str, list[str]] = {}
    role_tables: dict[str, set[str]] = {}
    database_meta: dict[str, dict[str, Any]] = {}
    concept_terms: dict[str, dict[str, Any]] = {}
    derived_metric_terms: dict[str, dict[str, Any]] = {}

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

        if not source.terms_path.exists():
            raise FileNotFoundError(f"未找到数据库术语表：{source.terms_path}")
        terms_payload = json.loads(source.terms_path.read_text(encoding="utf-8"))
        terms_database = str(terms_payload.get("database") or database_id)
        if terms_database != database_id:
            raise ValueError(
                f"术语表数据库标识不一致：期望 {database_id}，实际 {terms_database}"
            )

        database_meta[database_id] = {
            "scenario": str(payload.get("scenario") or ""),
            "time_coverage": str(payload.get("time_coverage") or ""),
            "example_questions": [
                str(item) for item in payload.get("example_questions") or []
            ],
        }
        source_tables = list(payload.get("tables") or [])
        for table in source_tables:
            table.setdefault("database", database_id)

        table_ids = {str(table["id"]) for table in source_tables}
        field_ids = {
            f"{table['id']}.{field['name']}"
            for table in source_tables
            for field in table.get("fields", [])
        }
        source_table_terms = {
            str(key): _term_list(value, target=str(key))
            for key, value in (terms_payload.get("table_terms") or {}).items()
        }
        source_field_terms = {
            str(key): _term_list(value, target=str(key))
            for key, value in (terms_payload.get("field_terms") or {}).items()
        }
        invalid_table_terms = set(source_table_terms) - table_ids
        if invalid_table_terms:
            raise ValueError(
                f"数据库 {database_id} 的 table_terms 包含未知表："
                f"{', '.join(sorted(invalid_table_terms))}"
            )
        invalid_field_terms = set(source_field_terms) - field_ids
        if invalid_field_terms:
            raise ValueError(
                f"数据库 {database_id} 的 field_terms 包含未知字段："
                f"{', '.join(sorted(invalid_field_terms))}"
            )
        duplicates = set(field_terms) & set(source_field_terms)
        if duplicates:
            raise ValueError(f"field_terms 字段重复：{', '.join(sorted(duplicates))}")
        field_terms.update(source_field_terms)

        for table in source_tables:
            table["business_terms"] = source_table_terms.get(str(table["id"]), [])
            for field in table.get("fields", []):
                field_id = f"{table['id']}.{field['name']}"
                field["aliases"] = source_field_terms.get(field_id, [])

        source_concept_terms = terms_payload.get("concept_terms") or {}
        if not isinstance(source_concept_terms, dict):
            raise ValueError(f"数据库 {database_id} 的 concept_terms 必须是对象")
        for concept_id, entry in source_concept_terms.items():
            if not isinstance(entry, dict) or not str(entry.get("label") or "").strip():
                raise ValueError(f"数据库 {database_id} 的概念术语无有效标签：{concept_id}")
            normalized_entry = {
                **entry,
                "label": str(entry["label"]).strip(),
                "aliases": _term_list(
                    entry.get("aliases") or [],
                    target=f"{database_id}.{concept_id}.aliases",
                ),
            }
            qualified_id = f"{database_id}.{concept_id}"
            if qualified_id in concept_terms:
                raise ValueError(f"概念术语重复：{qualified_id}")
            concept_terms[qualified_id] = {
                **normalized_entry,
                "concept_id": str(concept_id),
                "database": database_id,
            }

        source_metric_terms = terms_payload.get("derived_metric_terms") or {}
        if not isinstance(source_metric_terms, dict):
            raise ValueError(f"数据库 {database_id} 的 derived_metric_terms 必须是对象")
        for metric_id, entry in source_metric_terms.items():
            if not isinstance(entry, dict) or not str(entry.get("label") or "").strip():
                raise ValueError(f"数据库 {database_id} 的派生指标术语无有效标签：{metric_id}")
            normalized_entry = {
                **entry,
                "label": str(entry["label"]).strip(),
                "aliases": _term_list(
                    entry.get("aliases") or [],
                    target=f"{database_id}.{metric_id}.aliases",
                ),
            }
            qualified_id = f"{database_id}.{metric_id}"
            if qualified_id in derived_metric_terms:
                raise ValueError(f"派生指标术语重复：{qualified_id}")
            derived_metric_terms[qualified_id] = {
                **normalized_entry,
                "metric_id": str(metric_id),
                "database": database_id,
            }

        fields_by_id = {
            f"{table['id']}.{field['name']}": field
            for table in source_tables
            for field in table.get("fields", [])
        }
        for qualified_metric_id, metric in tuple(derived_metric_terms.items()):
            if metric.get("database") != database_id or metric.get("status") != "active":
                continue
            field_id = str(metric.get("field_id") or "").strip()
            if not field_id:
                raise ValueError(f"已启用派生指标缺少 field_id：{qualified_metric_id}")
            field = fields_by_id.get(field_id)
            if field is None:
                raise ValueError(
                    f"已启用派生指标 {qualified_metric_id} 指向未知字段：{field_id}"
                )
            metric_aliases = [metric["label"], *metric.get("aliases", [])]
            field["aliases"] = list(
                dict.fromkeys([*field.get("aliases", []), *metric_aliases])
            )
            field["derived_metric"] = {
                key: metric[key]
                for key in (
                    "metric_id",
                    "label",
                    "aliases",
                    "category",
                    "definition",
                    "availability",
                    "sql_expression",
                    "invalid_when",
                    "unit",
                    "period_basis",
                    "formula_version",
                    "quality_note",
                )
                if metric.get(key) not in (None, "", [])
            }

        tables.extend(source_tables)
        relations.extend(list(payload.get("relations") or []))

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
        field_terms,
        {role: frozenset(ids) for role, ids in role_tables.items()},
        database_meta,
        concept_terms,
        derived_metric_terms,
    )


(
    ACTIVE_DATABASES,
    SCHEMA,
    RELATIONS,
    FIELD_TERMS,
    ROLE_TABLES,
    DATABASE_META,
    CONCEPT_TERMS,
    DERIVED_METRIC_TERMS,
) = load_database_catalog(settings.database_switches)

TERM_CATALOG = {
    "fields": FIELD_TERMS,
    "concepts": CONCEPT_TERMS,
    "derived_metrics": DERIVED_METRIC_TERMS,
}
DEFAULT_DATABASE = sorted(ACTIVE_DATABASES)[0]


def physical_table_name(table: dict[str, Any]) -> str:
    return str(table.get("name") or table["id"])


def database_query_folder(database: str) -> Path:
    try:
        return DATABASE_SOURCES[database].query_folder
    except KeyError as exc:
        raise ValueError(f"未知数据库：{database}") from exc
