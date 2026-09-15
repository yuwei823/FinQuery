from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..database import ACTIVE_DATABASES, ROLE_TABLES, SCHEMA


ALL_DATABASES = ACTIVE_DATABASES
ALL_TABLES = frozenset(str(table["id"]) for table in SCHEMA)
TABLE_DATABASES = {
    str(table["id"]): str(table.get("database") or "")
    for table in SCHEMA
}


def _scenario_tables(role: str) -> frozenset[str]:
    return ROLE_TABLES.get(role, frozenset())


def _scenario_databases(tables: frozenset[str]) -> frozenset[str]:
    return frozenset(TABLE_DATABASES[table_id] for table_id in tables)


GROWTH_OPS_TABLES = _scenario_tables("growth_ops")
CHANNEL_OPS_TABLES = _scenario_tables("channel_ops")
CONTENT_OPS_TABLES = _scenario_tables("content_ops")


@dataclass(frozen=True)
class AccessScope:
    """由后端生成并贯穿查询链路的权限范围。"""

    user_id: str
    roles: tuple[str, ...]
    allowed_databases: frozenset[str]
    allowed_tables: frozenset[str]

    def allows_database(self, database: str) -> bool:
        return database in self.allowed_databases

    def allows_table(self, database: str, table_id: str) -> bool:
        return self.allows_database(database) and table_id in self.allowed_tables

    def public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["roles"] = list(self.roles)
        payload["allowed_databases"] = sorted(self.allowed_databases)
        payload["allowed_tables"] = sorted(self.allowed_tables)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> AccessScope:
        raw = payload or {}
        return cls(
            user_id=str(raw.get("user_id") or "anonymous"),
            roles=tuple(str(item) for item in raw.get("roles") or []),
            allowed_databases=frozenset(
                str(item) for item in raw.get("allowed_databases") or []
            ),
            allowed_tables=frozenset(str(item) for item in raw.get("allowed_tables") or []),
        )


class AccessController:
    """根据用户角色返回数据库和表权限。"""

    DEFAULT_USER = "demo_growth_ops"
    USER_ROLES = {
        "demo_admin": ("admin",),
        "demo_growth_ops": ("growth_ops",),
        "demo_channel_ops": ("channel_ops",),
        "demo_content_ops": ("content_ops",),
    }
    ROLE_POLICIES = {
        "admin": {"databases": ALL_DATABASES, "tables": ALL_TABLES},
        "growth_ops": {
            "databases": _scenario_databases(GROWTH_OPS_TABLES),
            "tables": GROWTH_OPS_TABLES,
        },
        "channel_ops": {
            "databases": _scenario_databases(CHANNEL_OPS_TABLES),
            "tables": CHANNEL_OPS_TABLES,
        },
        "content_ops": {
            "databases": _scenario_databases(CONTENT_OPS_TABLES),
            "tables": CONTENT_OPS_TABLES,
        },
    }

    def resolve(self, user_id: str | None) -> AccessScope:
        resolved_user = (user_id or self.DEFAULT_USER).strip() or self.DEFAULT_USER
        roles = self.USER_ROLES.get(resolved_user, ())
        databases: set[str] = set()
        tables: set[str] = set()
        for role in roles:
            policy = self.ROLE_POLICIES[role]
            databases.update(policy["databases"])
            tables.update(policy["tables"])
        return AccessScope(
            user_id=resolved_user,
            roles=roles,
            allowed_databases=frozenset(databases),
            allowed_tables=frozenset(tables),
        )

    @staticmethod
    def filter_schema(scope: AccessScope) -> list[dict[str, Any]]:
        return [
            table
            for table in SCHEMA
            if scope.allows_table(str(table.get("database") or ""), str(table["id"]))
        ]
