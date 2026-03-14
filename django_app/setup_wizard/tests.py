from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from setup_wizard.middleware import SetupRequiredMiddleware


class SetupRequiredMiddlewareTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _middleware(self) -> SetupRequiredMiddleware:
        return SetupRequiredMiddleware(lambda request: HttpResponse("ok"))

    def test_skips_redirect_when_setup_is_disabled_for_environment(self):
        request = self.factory.get("/")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("SETUP_COMPLETED=0\n", encoding="utf-8")
            with patch("setup_wizard.middleware._ENV_PATH", env_path), override_settings(
                SETUP_WIZARD_REQUIRED=False
            ):
                response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_redirects_when_setup_is_required_and_not_completed(self):
        request = self.factory.get("/")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("SETUP_COMPLETED=0\n", encoding="utf-8")
            with patch("setup_wizard.middleware._ENV_PATH", env_path), override_settings(
                SETUP_WIZARD_REQUIRED=True
            ):
                response = self._middleware()(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/setup/")

    def test_allows_request_when_setup_is_completed(self):
        request = self.factory.get("/")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("SETUP_COMPLETED=1\n", encoding="utf-8")
            with patch("setup_wizard.middleware._ENV_PATH", env_path), override_settings(
                SETUP_WIZARD_REQUIRED=True
            ):
                response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
