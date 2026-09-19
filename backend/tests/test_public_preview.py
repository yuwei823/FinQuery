from __future__ import annotations

import unittest
from unittest.mock import patch

from app.config import Settings
from app.security.auth import AuthService


class PublicPreviewTest(unittest.TestCase):
    def test_public_mode_is_reported(self) -> None:
        with patch.dict("os.environ", {"FINQUERY_PUBLIC_MODE": "true"}, clear=True):
            settings = Settings()
        self.assertTrue(settings.public_mode)
        self.assertTrue(settings.public_status()["public_mode"])

    def test_public_mode_rejects_default_passwords(self) -> None:
        with patch.dict("os.environ", {"FINQUERY_PUBLIC_MODE": "true"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "至少16位"):
                AuthService()

    def test_public_mode_accepts_overridden_passwords(self) -> None:
        environment = {
            "FINQUERY_PUBLIC_MODE": "true",
            "FINQUERY_ADMIN_PASSWORD": "admin-preview-password-2026",
            "FINQUERY_MARKET_PASSWORD": "market-preview-password-2026",
        }
        with patch.dict("os.environ", environment, clear=True):
            service = AuthService()
            self.assertIsNotNone(
                service.login("market", environment["FINQUERY_MARKET_PASSWORD"])
            )
            self.assertIsNone(service.login("market", "market123"))


if __name__ == "__main__":
    unittest.main()
