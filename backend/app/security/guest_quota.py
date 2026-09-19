from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class GuestQueryQuota:
    """Persistent, process-safe daily quota for guest query submissions."""

    QUOTA_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")

    def __init__(self, path: str | Path, daily_limit: int = 5) -> None:
        if daily_limit < 1:
            raise ValueError("游客每日查询上限必须大于0")
        self.path = Path(path)
        self.daily_limit = daily_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def _today() -> str:
        return datetime.now(GuestQueryQuota.QUOTA_TIMEZONE).date().isoformat()

    def remaining(self, quota_key: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT query_count FROM guest_query_usage WHERE usage_day = ? AND quota_key = ?",
                (self._today(), quota_key),
            ).fetchone()
        used = int(row[0]) if row else 0
        return max(0, self.daily_limit - used)

    def consume(self, quota_key: str) -> int | None:
        """Consume one query and return the remaining count, or None if exhausted."""
        today = self._today()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT query_count FROM guest_query_usage WHERE usage_day = ? AND quota_key = ?",
                (today, quota_key),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used >= self.daily_limit:
                connection.rollback()
                return None
            updated = used + 1
            connection.execute(
                """
                INSERT INTO guest_query_usage (usage_day, quota_key, query_count)
                VALUES (?, ?, ?)
                ON CONFLICT (usage_day, quota_key)
                DO UPDATE SET query_count = excluded.query_count
                """,
                (today, quota_key, updated),
            )
            connection.execute(
                "DELETE FROM guest_query_usage WHERE usage_day < date(?, '-8 days')",
                (today,),
            )
            connection.commit()
        return self.daily_limit - updated

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS guest_query_usage (
                    usage_day TEXT NOT NULL,
                    quota_key TEXT NOT NULL,
                    query_count INTEGER NOT NULL CHECK (query_count >= 0),
                    PRIMARY KEY (usage_day, quota_key)
                )
                """
            )
