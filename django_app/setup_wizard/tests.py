from __future__ import annotations

import json
import os
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
            with patch.dict(os.environ, {"PORTAL_CONFIG_ENV_FILE": str(env_path)}), override_settings(
                SETUP_WIZARD_REQUIRED=False
            ):
                response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class SetupWizardEndpointGatingTests(SimpleTestCase):
    """Gli endpoint mutanti/di test del wizard sono attivi solo durante la finestra
    di setup: a installazione completata (SETUP_COMPLETED=1) devono rispondere 403,
    altrimenti restano sfruttabili da utenti non autenticati (prefisso /setup/ esente
    da auth/ACL). Regressione per SEC: create-admin/migrate/finalize non autenticati."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _post(self, path):
        return self.factory.post(path, data=b"{}", content_type="application/json")

    def test_mutating_endpoints_blocked_when_setup_completed(self):
        targets = [
            (views.api_test_db, "/setup/api/test-db/"),
            (views.api_test_ldap, "/setup/api/test-ldap/"),
            (views.api_test_smtp, "/setup/api/test-smtp/"),
            (views.api_run_migrations, "/setup/api/run-migrations/"),
            (views.api_finalize_database, "/setup/api/finalize-database/"),
            (views.api_create_admin, "/setup/api/create-admin/"),
            (views.api_set_modules, "/setup/api/set-modules/"),
        ]
        with patch("setup_wizard.views._setup_needed", return_value=False):
            for view, path in targets:
                response = view(self._post(path))
                self.assertEqual(
                    response.status_code, 403,
                    f"{path} dovrebbe rispondere 403 a setup completato",
                )
                self.assertFalse(json.loads(response.content)["ok"])

    def test_safe_branding_ext_rejects_path_traversal(self):
        self.assertEqual(views._safe_branding_ext("png", "png"), "png")
        self.assertEqual(views._safe_branding_ext("SVG", "png"), "svg")
        self.assertEqual(views._safe_branding_ext(".JPG", "png"), "jpg")
        # Separatori di percorso / '..' non sono in allowlist: ricaduta sul default
        self.assertEqual(views._safe_branding_ext("x/../../../evil.py", "png"), "png")
        self.assertEqual(views._safe_branding_ext("..\\..\\shell", "ico"), "ico")
        self.assertEqual(views._safe_branding_ext("", "ico"), "ico")
        self.assertEqual(views._safe_branding_ext(None, "ico"), "ico")


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

        with patch("setup_wizard.views._setup_needed", return_value=True), \
             patch("setup_wizard.views._settings_module_from_env", return_value="config.settings.prod"), \
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

        with patch("setup_wizard.views._setup_needed", return_value=True), \
             patch("setup_wizard.views._settings_module_from_env", return_value="config.settings.prod"), \
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
            with patch.dict(os.environ, {"PORTAL_CONFIG_ENV_FILE": str(env_path)}), override_settings(
                SETUP_WIZARD_REQUIRED=True
            ):
                response = self._middleware()(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/setup/")

    def test_persistent_env_wins_over_release_copy(self):
        """Il flag nel .env persistente (ENV/config/.env) basta: una copia nella
        release senza SETUP_COMPLETED non deve riaprire il wizard anonimo."""
        from setup_wizard.state import setup_needed

        with tempfile.TemporaryDirectory() as tmpdir:
            persistent = Path(tmpdir) / "config.env"
            persistent.write_text("SETUP_COMPLETED=1\n", encoding="utf-8")
            with patch.dict(os.environ, {"PORTAL_CONFIG_ENV_FILE": str(persistent)}):
                self.assertFalse(setup_needed())
            persistent.write_text("SETUP_COMPLETED=0\n", encoding="utf-8")
            with patch.dict(os.environ, {"PORTAL_CONFIG_ENV_FILE": str(persistent)}):
                self.assertTrue(setup_needed())

    def test_allows_request_when_setup_is_completed(self):
        request = self.factory.get("/")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("SETUP_COMPLETED=1\n", encoding="utf-8")
            with patch.dict(os.environ, {"PORTAL_CONFIG_ENV_FILE": str(env_path)}), override_settings(
                SETUP_WIZARD_REQUIRED=True
            ):
                response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class SetupWizardTestDbOdbcTests(SimpleTestCase):
    """Stringa ODBC con valori tra {} e niente testo grezzo del driver al client."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _chiama(self, dati, connect):
        import sys
        from types import SimpleNamespace

        finto = SimpleNamespace(connect=connect)
        req = self.factory.post("/setup/api/test-db/", data=json.dumps(dati), content_type="application/json")
        with patch("setup_wizard.views._setup_needed", return_value=True), \
                patch.dict(sys.modules, {"pyodbc": finto}):
            return json.loads(views.api_test_db(req).content)

    def test_valori_tra_graffe_e_connessione_chiusa(self):
        visti = {}

        class _Cur:
            def execute(self, _q):
                return None

            def fetchone(self):
                return ["Microsoft SQL Server sintetico\nriga 2"]

        class _Conn:
            timeout = 0
            chiusa = False

            def cursor(self):
                return _Cur()

            def close(self):
                _Conn.chiusa = True

        def connect(conn_str, timeout=None):
            visti["cs"] = conn_str
            return _Conn()

        esito = self._chiama({"host": "srv", "name": "db;x=1", "user": "u", "password": "p}w;Encrypt=no"}, connect)
        self.assertTrue(esito["ok"])
        self.assertIn("DATABASE={db;x=1}", visti["cs"])
        self.assertIn("PWD={p}}w;Encrypt=no}", visti["cs"])
        self.assertTrue(_Conn.chiusa)

    def test_errore_senza_testo_grezzo(self):
        def connect(conn_str, timeout=None):
            raise RuntimeError("[28000] Login failed for user 'utente-segreto' su host-interno")

        esito = self._chiama({"host": "srv", "name": "db", "user": "u", "password": "p"}, connect)
        self.assertFalse(esito["ok"])
        self.assertNotIn("utente-segreto", esito["error"])
        self.assertIn("Accesso negato", esito["error"])
