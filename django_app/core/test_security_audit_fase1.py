"""Regressioni dell'audit sicurezza 09/10, Fase 1 (A4, A5, A10, M6, M8)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, override_settings

from config.env_config import update_env_file_values


class EnvFileInjectionTests(SimpleTestCase):
    """Audit M6: un valore con a-capo non aggiunge righe al .env."""

    def _path(self) -> Path:
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / ".env"
        path.write_text("A=1\n", encoding="utf-8")
        return path

    def test_newline_in_value_is_rejected(self):
        path = self._path()
        with self.assertRaises(ValueError):
            update_env_file_values({"OLLAMA_MODEL": "x\nDJANGO_DEBUG=1"}, dotenv_path=path, apply_to_process=False)
        self.assertEqual(path.read_text(encoding="utf-8"), "A=1\n")

    def test_invalid_key_is_rejected(self):
        path = self._path()
        with self.assertRaises(ValueError):
            update_env_file_values({"BAD KEY": "1"}, dotenv_path=path, apply_to_process=False)

    def test_regular_value_is_written(self):
        path = self._path()
        update_env_file_values({"B": "valore con spazi"}, dotenv_path=path, apply_to_process=False)
        self.assertIn("B=valore con spazi", path.read_text(encoding="utf-8"))


class AxesSettingsTests(SimpleTestCase):
    """Audit A4: lockout per username+IP, IP letto dietro proxy fidato."""

    def test_lockout_is_per_username_and_ip(self):
        self.assertEqual(settings.AXES_LOCKOUT_PARAMETERS, [["username", "ip_address"]])
        self.assertEqual(settings.AXES_CLIENT_IP_CALLABLE, "core.net.client_ip")


class TwoFAExternalEntrypointTests(SimpleTestCase):
    """Audit A5: il traffico via App Proxy resta «esterno» anche da IP di LAN."""

    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(TWOFA_EXTERNAL_HOSTS=["*.msappproxy.net"], TWOFA_EXTERNAL_PROXY_IPS=set(),
                       ALLOWED_HOSTS=["*"])
    def test_app_proxy_host_is_external(self):
        from twofa.utils import is_external_entrypoint

        request = self.factory.get("/", HTTP_HOST="cnhub-example.msappproxy.net", REMOTE_ADDR="10.0.0.9")
        self.assertTrue(is_external_entrypoint(request, "10.0.0.9"))

    @override_settings(TWOFA_EXTERNAL_HOSTS=[], TWOFA_EXTERNAL_PROXY_IPS={"10.0.0.9"}, ALLOWED_HOSTS=["*"])
    def test_connector_ip_is_external(self):
        from twofa.utils import is_external_entrypoint

        request = self.factory.get("/", HTTP_HOST="hub.example.local", REMOTE_ADDR="10.0.0.9")
        self.assertTrue(is_external_entrypoint(request, "10.0.0.9"))

    @override_settings(TWOFA_EXTERNAL_HOSTS=["*.msappproxy.net"], TWOFA_EXTERNAL_PROXY_IPS=set(),
                       ALLOWED_HOSTS=["*"])
    def test_lan_request_is_internal(self):
        from twofa.utils import is_external_entrypoint

        request = self.factory.get("/", HTTP_HOST="hub.example.local", REMOTE_ADDR="10.0.0.20")
        self.assertFalse(is_external_entrypoint(request, "10.0.0.20"))

    @override_settings(TWOFA_EXTERNAL_HOSTS=["*.msappproxy.net"], TWOFA_EXTERNAL_PROXY_IPS=set(),
                       ALLOWED_HOSTS=["*"])
    def test_policy_external_only_requires_2fa_via_app_proxy(self):
        from twofa.models import TwoFactorPolicy
        from twofa.utils import should_require_2fa

        policy = SimpleNamespace(
            enabled=True,
            when_required=TwoFactorPolicy.WHEN_EXTERNAL,
            internal_networks=["10.0.0.0/8"],
            required_role_ids=[],
        )
        user = SimpleNamespace(is_superuser=True, is_staff=False, twofa=SimpleNamespace(is_active=True))
        request = self.factory.get("/", HTTP_HOST="cnhub-example.msappproxy.net", REMOTE_ADDR="10.0.0.9")
        with patch("twofa.models.TwoFactorPolicy.get", return_value=policy), \
             patch("twofa.utils.get_client_ip", return_value="10.0.0.9"):
            self.assertTrue(should_require_2fa(request, user))
        lan = self.factory.get("/", HTTP_HOST="hub.example.local", REMOTE_ADDR="10.0.0.20")
        with patch("twofa.models.TwoFactorPolicy.get", return_value=policy), \
             patch("twofa.utils.get_client_ip", return_value="10.0.0.20"):
            self.assertFalse(should_require_2fa(lan, user))


class LdapTransportTests(SimpleTestCase):
    """Audit A10/S7: TLS verificato su ldaps:// e timeout di lettura."""

    def test_ldaps_server_verifies_certificate(self):
        import ssl

        from core.ldap_conn import build_ldap_server

        server = build_ldap_server("ldaps://dc.example.local", 5)
        self.assertTrue(server.ssl)
        self.assertEqual(server.tls.validate, ssl.CERT_REQUIRED)

    def test_plain_ldap_is_flagged_insecure(self):
        from core.ldap_conn import ldap_transport_is_insecure

        self.assertTrue(ldap_transport_is_insecure("ldap://dc.example.local"))
        self.assertFalse(ldap_transport_is_insecure("ldaps://dc.example.local"))

    @override_settings(LDAP_RECEIVE_TIMEOUT=0, LDAP_TIMEOUT=5)
    def test_receive_timeout_default(self):
        from core.ldap_conn import ldap_receive_timeout

        self.assertEqual(ldap_receive_timeout(), 10)


class ReadyzPublicPayloadTests(SimpleTestCase):
    """Audit M8: la risposta HTTP non contiene i messaggi delle eccezioni."""

    def test_public_payload_has_no_messages(self):
        from monitoring.health import CheckResult, ReadyzReport

        report = ReadyzReport(
            status="fail",
            checks=[CheckResult(name="db_default", status="fail", latency_ms=1, critical=True,
                                message="OperationalError: login failed for user sa on 10.0.0.1")],
        )
        payload = report.to_public_payload()
        self.assertNotIn("message", payload["checks"][0])
        self.assertNotIn("10.0.0.1", str(payload))
