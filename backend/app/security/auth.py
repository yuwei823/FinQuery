from __future__ import annotations

import os
import secrets
from hashlib import sha256
from pathlib import Path
from dataclasses import dataclass

from .guest_quota import GuestQueryQuota


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    username: str
    display_name: str
    role: str
    quota_key: str | None = None

    def public(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
        }


class AuthService:
    """进程内账号认证；令牌在服务重启后失效。"""

    DEFAULT_ADMIN_PASSWORD = "admin123"
    DEFAULT_MARKET_PASSWORD = "market123"
    DEFAULT_GUEST_DAILY_QUERY_LIMIT = 5

    def __init__(self) -> None:
        public_mode = os.getenv("FINQUERY_PUBLIC_MODE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        admin_password = (
            os.getenv("FINQUERY_ADMIN_PASSWORD", "").strip()
            or self.DEFAULT_ADMIN_PASSWORD
        )
        market_password = (
            os.getenv("FINQUERY_MARKET_PASSWORD", "").strip()
            or self.DEFAULT_MARKET_PASSWORD
        )
        if public_mode:
            weak = [
                name
                for name, password, default in (
                    ("FINQUERY_ADMIN_PASSWORD", admin_password, self.DEFAULT_ADMIN_PASSWORD),
                    ("FINQUERY_MARKET_PASSWORD", market_password, self.DEFAULT_MARKET_PASSWORD),
                )
                if len(password) < 16 or secrets.compare_digest(password, default)
            ]
            if weak:
                raise RuntimeError(
                    "公网预览模式要求设置至少16位的非默认密码：" + ", ".join(weak)
                )
        self._accounts = {
            "admin": {
                "password": admin_password,
                "user": AuthUser("demo_admin", "admin", "系统管理员", "admin"),
            },
            "market": {
                "password": market_password,
                "user": AuthUser(
                    "demo_market_analyst",
                    "market",
                    "行情分析师",
                    "market_analyst",
                ),
            },
        }
        self._tokens: dict[str, AuthUser] = {}
        self._guest_enabled = os.getenv("ENABLE_GUEST", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._guest_daily_query_limit = int(
            os.getenv(
                "GUEST_DAILY_QUERY_LIMIT",
                str(self.DEFAULT_GUEST_DAILY_QUERY_LIMIT),
            )
        )
        self._guest_quota = (
            GuestQueryQuota(
                Path(os.getenv("GUEST_USAGE_PATH", "data/guest_usage.db")),
                self._guest_daily_query_limit,
            )
            if self._guest_enabled
            else None
        )

    @property
    def guest_enabled(self) -> bool:
        return self._guest_enabled

    @property
    def guest_daily_query_limit(self) -> int:
        return self._guest_daily_query_limit

    def login(self, username: str, password: str) -> tuple[str, AuthUser] | None:
        account = self._accounts.get(username.strip())
        if not account or not secrets.compare_digest(str(account["password"]), password):
            return None
        token = secrets.token_urlsafe(32)
        user = account["user"]
        self._tokens[token] = user
        return token, user

    def guest_login(self, guest_id: str, quota_key: str) -> tuple[str, AuthUser] | None:
        if not self._guest_enabled:
            return None
        identity_hash = sha256(guest_id.encode("utf-8")).hexdigest()
        user = AuthUser(
            user_id=f"guest_{identity_hash[:24]}",
            username="guest",
            display_name=f"游客 {identity_hash[:4].upper()}",
            role="guest",
            quota_key=quota_key,
        )
        token = secrets.token_urlsafe(32)
        self._tokens[token] = user
        return token, user

    def consume_guest_query(self, user: AuthUser) -> int | None:
        if user.role != "guest":
            return None
        if not self._guest_quota or not user.quota_key:
            raise RuntimeError("游客查询额度服务未启用")
        return self._guest_quota.consume(user.quota_key)

    def authenticate(self, authorization: str | None) -> AuthUser | None:
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        return self._tokens.get(token)

    def logout(self, authorization: str | None) -> None:
        if not authorization:
            return
        _, _, token = authorization.partition(" ")
        self._tokens.pop(token, None)
