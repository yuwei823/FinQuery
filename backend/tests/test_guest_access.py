from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import routes
from app.config import Settings
from app.main import app
from app.models import QueryResult
from app.security.access_control import AccessController, MARKET_ANALYST_TABLES
from app.security.auth import AuthService
from app.security.guest_quota import GuestQueryQuota


class GuestAccessTest(unittest.TestCase):
    def test_guest_feature_is_disabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            service = AuthService()
            settings = Settings()
        self.assertFalse(service.guest_enabled)
        self.assertFalse(settings.guest_enabled)
        self.assertIsNone(service.guest_login("9d5ef2c3-088f-48bd-9b66-503a841f00aa", "ip"))

    def test_guest_identity_is_stable_and_uses_market_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = {
                "ENABLE_GUEST": "true",
                "GUEST_USAGE_PATH": str(Path(temp_dir) / "usage.db"),
            }
            with patch.dict("os.environ", environment, clear=True):
                service = AuthService()
            first = service.guest_login(
                "9d5ef2c3-088f-48bd-9b66-503a841f00aa", "source-a"
            )
            second = service.guest_login(
                "9d5ef2c3-088f-48bd-9b66-503a841f00aa", "source-a"
            )
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first is not None and second is not None
            self.assertEqual(first[1].user_id, second[1].user_id)
            self.assertEqual(first[1].role, "guest")
            scope = AccessController().resolve(first[1].user_id)
            self.assertEqual(scope.roles, ("market_analyst",))
            self.assertEqual(scope.allowed_tables, MARKET_ANALYST_TABLES)

    def test_guest_daily_limit_is_enforced_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "usage.db"
            quota = GuestQueryQuota(path, daily_limit=5)
            self.assertEqual([quota.consume("source-a") for _ in range(5)], [4, 3, 2, 1, 0])
            self.assertIsNone(quota.consume("source-a"))
            self.assertEqual(GuestQueryQuota(path, daily_limit=5).remaining("source-a"), 0)
            self.assertEqual(GuestQueryQuota(path, daily_limit=5).remaining("source-b"), 5)

    def test_guest_query_route_allows_five_then_returns_429(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = {
                "ENABLE_GUEST": "true",
                "GUEST_USAGE_PATH": str(Path(temp_dir) / "usage.db"),
            }
            with patch.dict("os.environ", environment, clear=True):
                auth_service = AuthService()
            query_service = Mock()
            query_service.submit.return_value = QueryResult(
                task_id="guest-test",
                status="completed",
                route="direct_response",
                message="ok",
            )
            with (
                patch.object(routes, "auth_service", auth_service),
                patch.object(routes, "service", query_service),
                TestClient(app) as client,
            ):
                login = client.post(
                    "/api/auth/guest",
                    json={"guest_id": str(uuid4())},
                )
                self.assertEqual(login.status_code, 200)
                headers = {
                    "Authorization": f"Bearer {login.json()['access_token']}"
                }
                for expected_remaining in range(4, -1, -1):
                    response = client.post(
                        "/api/query",
                        headers=headers,
                        json={"query": "测试", "session_id": "guest-test"},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        response.headers["x-guest-queries-remaining"],
                        str(expected_remaining),
                    )
                blocked = client.post(
                    "/api/query",
                    headers=headers,
                    json={"query": "第六次", "session_id": "guest-test"},
                )
                self.assertEqual(blocked.status_code, 429)
                self.assertIn("每日最多查询5次", blocked.json()["detail"])
                self.assertEqual(query_service.submit.call_count, 5)


if __name__ == "__main__":
    unittest.main()
