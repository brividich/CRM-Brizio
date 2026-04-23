from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from setup_wizard import views
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


class SetupWizardFinalizeDatabaseTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _middleware(self) -> SetupRequiredMiddleware:
        return SetupRequiredMiddleware(lambda request: HttpResponse("ok"))

    def test_finalize_database_runs_runtime_schema_before_bootstrap(self):
        request = self.factory.post(
            "/setup/api/finalize-database/",
            data=b"{}",
            content_type="application/json",
        )
        calls: list[list[str]] = []

        def fake_run(args, *, timeout=180):
            calls.append(args)
            return True, "ok"

        with patch("setup_wizard.views._settings_module_from_env", return_value="config.settings.prod"), \
             patch("setup_wizard.views._env_uses_sqlserver", return_value=True), \
             patch("setup_wizard.views._run_manage_command", side_effect=fake_run):
            response = views.api_finalize_database(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["ok"])
        command_names = [args[0] for args in calls]
        self.assertEqual(command_names[0], "ensure_legacy_schema")
        self.assertIn("createcachetable", command_names)
        self.assertIn("apply_sql_triggers", command_names)
        self.assertIn("bootstrap_acl_v2", command_names)

    def test_finalize_database_blocks_on_runtime_schema_failure(self):
        request = self.factory.post(
            "/setup/api/finalize-database/",
            data=b"{}",
            content_type="application/json",
        )

        with patch("setup_wizard.views._settings_module_from_env", return_value="config.settings.prod"), \
             patch("setup_wizard.views._env_uses_sqlserver", return_value=True), \
             patch("setup_wizard.views._run_manage_command", return_value=(False, "schema ko")):
            response = views.api_finalize_database(request)

        payload = json.loads(response.content)
        self.assertFalse(payload["ok"])
        self.assertIn("Schema legacy runtime", payload["error"])

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
