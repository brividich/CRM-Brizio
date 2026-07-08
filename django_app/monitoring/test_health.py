"""
Test per monitoring/health.py: liveness, readiness, IP allowlist, aggregazione.
"""
from __future__ import annotations

import json
import unittest.mock as mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from monitoring import health
from monitoring.health import (
    STATUS_FAIL,
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_WARN,
    CheckResult,
    _aggregate_status,
    _split_ldap_url,
    http_status_for,
    is_ip_allowed,
    run_readyz_checks,
)


class IpAllowlistTests(TestCase):
    def setUp(self):
        self.client = Client()

    @override_settings(HEALTHZ_ALLOWED_IPS=["127.0.0.1"])
    def test_loopback_is_allowed(self):
        request = self.client.request().wsgi_request
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        self.assertTrue(is_ip_allowed(request))

    @override_settings(HEALTHZ_ALLOWED_IPS=["10.0.0.5"])
    def test_other_ip_is_blocked(self):
        request = self.client.request().wsgi_request
        request.META["REMOTE_ADDR"] = "192.168.1.10"
        self.assertFalse(is_ip_allowed(request))

    @override_settings(HEALTHZ_ALLOWED_IPS=[])
    def test_empty_allowlist_falls_back_to_loopback(self):
        request = self.client.request().wsgi_request
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        self.assertTrue(is_ip_allowed(request))
        request.META["REMOTE_ADDR"] = "192.168.1.10"
        self.assertFalse(is_ip_allowed(request))


class AggregateStatusTests(TestCase):
    def test_all_ok(self):
        results = [
            CheckResult(name="a", status=STATUS_OK, latency_ms=1, critical=True),
            CheckResult(name="b", status=STATUS_OK, latency_ms=1),
        ]
        self.assertEqual(_aggregate_status(results), STATUS_OK)

    def test_critical_fail_wins(self):
        results = [
            CheckResult(name="a", status=STATUS_FAIL, latency_ms=1, critical=True),
            CheckResult(name="b", status=STATUS_OK, latency_ms=1),
        ]
        self.assertEqual(_aggregate_status(results), STATUS_FAIL)

    def test_non_critical_fail_becomes_warn(self):
        results = [
            CheckResult(name="a", status=STATUS_OK, latency_ms=1, critical=True),
            CheckResult(name="b", status=STATUS_FAIL, latency_ms=1, critical=False),
        ]
        self.assertEqual(_aggregate_status(results), STATUS_WARN)

    def test_skipped_does_not_affect(self):
        results = [
            CheckResult(name="a", status=STATUS_SKIPPED, latency_ms=0, critical=True),
            CheckResult(name="b", status=STATUS_OK, latency_ms=1),
        ]
        self.assertEqual(_aggregate_status(results), STATUS_OK)


class HttpStatusTests(TestCase):
    def test_ok_returns_200(self):
        report = mock.MagicMock()
        report.status = STATUS_OK
        self.assertEqual(http_status_for(report), 200)

    def test_warn_returns_200(self):
        report = mock.MagicMock()
        report.status = STATUS_WARN
        self.assertEqual(http_status_for(report), 200)

    def test_fail_returns_503(self):
        report = mock.MagicMock()
        report.status = STATUS_FAIL
        self.assertEqual(http_status_for(report), 503)


class SplitLdapUrlTests(TestCase):
    def test_ldap_default_port(self):
        host, port = _split_ldap_url("ldap://dc01.example.local")
        self.assertEqual(host, "dc01.example.local")
        self.assertEqual(port, 389)

    def test_ldaps_default_port(self):
        host, port = _split_ldap_url("ldaps://dc01.example.local")
        self.assertEqual(host, "dc01.example.local")
        self.assertEqual(port, 636)

    def test_explicit_port(self):
        host, port = _split_ldap_url("ldap://dc01.example.local:3268")
        self.assertEqual(host, "dc01.example.local")
        self.assertEqual(port, 3268)

    def test_no_scheme(self):
        host, port = _split_ldap_url("dc01.example.local")
        self.assertEqual(host, "dc01.example.local")
        self.assertEqual(port, 389)


class HealthzEndpointTests(TestCase):
    @override_settings(HEALTHZ_ALLOWED_IPS=["127.0.0.1"])
    def test_healthz_returns_ok_for_allowed_ip(self):
        response = self.client.get("/healthz", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "ok")

    @override_settings(HEALTHZ_ALLOWED_IPS=["10.0.0.5"])
    def test_healthz_blocks_unauthorized_ip(self):
        response = self.client.get("/healthz", REMOTE_ADDR="192.168.1.10")
        self.assertEqual(response.status_code, 403)


class ReadyzEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(
        HEALTHZ_ALLOWED_IPS=["127.0.0.1"],
        READYZ_TTL_SECONDS=0,
        READYZ_CHECKS_ENABLED=["db_default", "cache"],
    )
    def test_readyz_runs_only_enabled_checks(self):
        response = self.client.get("/readyz", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "ok")
        names = {check["name"] for check in payload["checks"]}
        self.assertEqual(names, {"db_default", "cache"})

    @override_settings(
        HEALTHZ_ALLOWED_IPS=["127.0.0.1"],
        READYZ_TTL_SECONDS=0,
        READYZ_CHECKS_ENABLED=["db_default", "cache"],
    )
    def test_readyz_returns_503_when_critical_fails(self):
        broken = CheckResult(
            name="db_default",
            status=STATUS_FAIL,
            latency_ms=5,
            critical=True,
            message="boom",
        )
        with mock.patch.object(health, "check_db_default", return_value=broken):
            response = self.client.get("/readyz", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "fail")

    @override_settings(
        HEALTHZ_ALLOWED_IPS=["127.0.0.1"],
        READYZ_TTL_SECONDS=60,
        READYZ_CHECKS_ENABLED=["db_default", "cache"],
    )
    def test_readyz_uses_cache(self):
        with mock.patch.object(health, "check_db_default", wraps=health.check_db_default) as spy:
            self.client.get("/readyz", REMOTE_ADDR="127.0.0.1")
            self.client.get("/readyz", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(spy.call_count, 1, "Il secondo readyz deve essere servito da cache")

    @override_settings(HEALTHZ_ALLOWED_IPS=["10.0.0.5"])
    def test_readyz_requires_allowed_ip(self):
        response = self.client.get("/readyz", REMOTE_ADDR="192.168.1.10")
        self.assertEqual(response.status_code, 403)


class CheckGraphTokenTests(TestCase):
    @override_settings(GRAPH_TENANT_ID="", GRAPH_CLIENT_ID="", GRAPH_CLIENT_SECRET="")
    def test_skipped_when_not_configured(self):
        result = health.check_graph_token()
        self.assertEqual(result.status, STATUS_SKIPPED)

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s"
    )
    def test_fail_when_acquire_raises(self):
        with mock.patch(
            "core.graph_utils.acquire_graph_token",
            side_effect=RuntimeError("invalid_client"),
        ):
            result = health.check_graph_token()
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertIn("invalid_client", result.message)

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s"
    )
    def test_ok_when_token_returned(self):
        with mock.patch(
            "core.graph_utils.acquire_graph_token", return_value="ya29.fake-token"
        ):
            result = health.check_graph_token()
        self.assertEqual(result.status, STATUS_OK)


class CheckLdapTests(TestCase):
    @override_settings(LDAP_ENABLED=False)
    def test_skipped_when_disabled(self):
        result = health.check_ldap()
        self.assertEqual(result.status, STATUS_SKIPPED)

    @override_settings(LDAP_ENABLED=True, LDAP_SERVER="")
    def test_fail_when_server_missing(self):
        result = health.check_ldap()
        self.assertEqual(result.status, STATUS_FAIL)


class CheckSmtpTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_skipped_for_non_smtp_backend(self):
        result = health.check_smtp()
        self.assertEqual(result.status, STATUS_SKIPPED)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="",
    )
    def test_fail_when_host_missing(self):
        result = health.check_smtp()
        self.assertEqual(result.status, STATUS_FAIL)


class RunReadyzChecksDirectTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(READYZ_TTL_SECONDS=0, READYZ_CHECKS_ENABLED=[])
    def test_empty_list_means_all_enabled(self):
        report = run_readyz_checks()
        names = {check.name for check in report.checks}
        # Almeno i check sempre presenti devono esserci.
        self.assertIn("db_default", names)
        self.assertIn("cache", names)


class _FakeHTTP:
    """Risposta HTTP fittizia usabile come context manager (per urlopen)."""

    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@override_settings(MONITORING_AI_CHECKS_ENABLED=True, OLLAMA_CHAT_ENABLED=True,
                   OLLAMA_BASE_URL="http://gpu:11434", OLLAMA_CHAT_MODEL="qwen2.5:14b-instruct")
class AiHealthCheckTests(TestCase):
    def test_ollama_chat_ok_when_model_present(self):
        payload = {"models": [{"name": "qwen2.5:14b-instruct"}, {"name": "altro"}]}
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(payload)):
            result = health.check_ollama_chat()
        self.assertEqual(result.status, STATUS_OK)
        self.assertFalse(result.critical)

    def test_ollama_chat_warn_when_model_missing(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP({"models": [{"name": "altro"}]})):
            result = health.check_ollama_chat()
        self.assertEqual(result.status, STATUS_WARN)

    def test_ollama_chat_fail_when_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = health.check_ollama_chat()
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertFalse(result.critical)  # AI giù non deve far 503 il readyz

    @override_settings(MONITORING_AI_CHECKS_ENABLED=False)
    def test_ollama_chat_skipped_when_disabled(self):
        result = health.check_ollama_chat()
        self.assertEqual(result.status, STATUS_SKIPPED)

    @override_settings(OLLAMA_EMBED_ENABLED=False)
    def test_embeddings_skipped_when_off(self):
        self.assertEqual(health.check_embeddings().status, STATUS_SKIPPED)

    @override_settings(OLLAMA_EMBED_ENABLED=True, RAG_EMBED_BACKEND="openai",
                       RAG_EMBED_OPENAI_BASE_URL="http://gpu:8081", RAG_EMBED_OPENAI_MODEL="bge-m3")
    def test_embeddings_tei_ok(self):
        payload = {"data": [{"embedding": [0.1] * 1024}]}
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(payload)):
            result = health.check_embeddings()
        self.assertEqual(result.status, STATUS_OK)
        self.assertEqual(result.details.get("dim"), 1024)

    @override_settings(OLLAMA_EMBED_ENABLED=True, RAG_EMBED_BACKEND="openai",
                       RAG_EMBED_OPENAI_BASE_URL="http://gpu:8081", RAG_EMBED_OPENAI_MODEL="bge-m3")
    def test_embeddings_tei_fail_when_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertEqual(health.check_embeddings().status, STATUS_FAIL)


class AiReadinessAlertTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(MONITORING_NOTIFY_CRITICAL_BY_EMAIL=True)
    def test_no_email_when_all_ok(self):
        ok = [CheckResult(name="ollama_chat", status=STATUS_OK, latency_ms=1)]
        with mock.patch.object(health, "run_ai_checks", return_value=ok), \
             mock.patch("core.email_utils.send_hub_mail") as send:
            result = health.run_ai_readiness_alert()
        self.assertEqual(result["status"], STATUS_OK)
        self.assertFalse(result["emailed"])
        send.assert_not_called()

    @override_settings(MONITORING_NOTIFY_CRITICAL_BY_EMAIL=True,
                       MONITORING_ALERT_QUIET_HOURS_ENABLED=False)
    def test_email_on_degrade_then_suppressed_until_change(self):
        bad = [CheckResult(name="ollama_chat", status=STATUS_FAIL, latency_ms=1,
                           message="irraggiungibile")]
        with mock.patch.object(health, "run_ai_checks", return_value=bad), \
             mock.patch("monitoring.services._admin_recipients", return_value=["a@b.c"]), \
             mock.patch("core.email_utils.send_hub_mail") as send:
            first = health.run_ai_readiness_alert()
            second = health.run_ai_readiness_alert()   # stesso degrado -> niente spam
        self.assertTrue(first["emailed"])
        self.assertFalse(second["emailed"])
        self.assertEqual(send.call_count, 1)

    @override_settings(MONITORING_NOTIFY_CRITICAL_BY_EMAIL=True,
                       MONITORING_ALERT_QUIET_HOURS_ENABLED=False)
    def test_recovery_resets_state(self):
        bad = [CheckResult(name="ollama_chat", status=STATUS_FAIL, latency_ms=1)]
        ok = [CheckResult(name="ollama_chat", status=STATUS_OK, latency_ms=1)]
        with mock.patch("monitoring.services._admin_recipients", return_value=["a@b.c"]), \
             mock.patch("core.email_utils.send_hub_mail") as send:
            with mock.patch.object(health, "run_ai_checks", return_value=bad):
                health.run_ai_readiness_alert()
            with mock.patch.object(health, "run_ai_checks", return_value=ok):
                health.run_ai_readiness_alert()        # ritorno OK -> azzera stato
            with mock.patch.object(health, "run_ai_checks", return_value=bad):
                again = health.run_ai_readiness_alert() # nuovo degrado -> riallarma
        self.assertTrue(again["emailed"])
        self.assertEqual(send.call_count, 2)

    @override_settings(MONITORING_NOTIFY_CRITICAL_BY_EMAIL=True,
                       MONITORING_ALERT_QUIET_HOURS_ENABLED=True,
                       MONITORING_ALERT_QUIET_START_HOUR=18,
                       MONITORING_ALERT_QUIET_END_HOUR=8)
    def test_quiet_hours_suppress_then_resume(self):
        import datetime as _dt

        bad = [CheckResult(name="ollama_chat", status=STATUS_FAIL, latency_ms=1)]
        with mock.patch.object(health, "run_ai_checks", return_value=bad), \
             mock.patch("monitoring.services._admin_recipients", return_value=["a@b.c"]), \
             mock.patch("core.email_utils.send_hub_mail") as send:
            # 20:00 -> quiet-hours: nessuna mail, stato anti-spam NON consumato
            with mock.patch("django.utils.timezone.localtime",
                            return_value=_dt.datetime(2026, 7, 2, 20, 0)):
                night = health.run_ai_readiness_alert()
            self.assertFalse(night["emailed"])
            send.assert_not_called()
            # 10:00 -> orario attivo: lo stesso degrado ancora presente riallarma
            with mock.patch("django.utils.timezone.localtime",
                            return_value=_dt.datetime(2026, 7, 3, 10, 0)):
                day = health.run_ai_readiness_alert()
            self.assertTrue(day["emailed"])
            self.assertEqual(send.call_count, 1)

    @override_settings(MONITORING_NOTIFY_CRITICAL_BY_EMAIL=True,
                       MONITORING_ALERT_QUIET_HOURS_ENABLED=True,
                       MONITORING_ALERT_QUIET_START_HOUR=18,
                       MONITORING_ALERT_QUIET_END_HOUR=8)
    def test_quiet_hours_force_email_overrides(self):
        import datetime as _dt

        bad = [CheckResult(name="ollama_chat", status=STATUS_FAIL, latency_ms=1)]
        with mock.patch.object(health, "run_ai_checks", return_value=bad), \
             mock.patch("monitoring.services._admin_recipients", return_value=["a@b.c"]), \
             mock.patch("core.email_utils.send_hub_mail") as send, \
             mock.patch("django.utils.timezone.localtime",
                        return_value=_dt.datetime(2026, 7, 2, 23, 0)):
            res = health.run_ai_readiness_alert(force_email=True)
        self.assertTrue(res["emailed"])
        send.assert_called_once()


class AiAlertIssueTests(TestCase):
    """Gli alert AI confluiscono come Issue nella centrale monitoring."""

    def setUp(self):
        cache.clear()

    @staticmethod
    def _checks(status):
        return [CheckResult(name="ollama_chat", status=status, latency_ms=1, message="x")]

    def test_creates_issue_on_fail_and_resolves_on_ok(self):
        from monitoring.models import Issue

        with mock.patch.object(health, "run_ai_checks", return_value=self._checks(STATUS_FAIL)), \
             mock.patch("core.email_utils.send_hub_mail"):
            health.run_ai_readiness_alert()
        open_issues = Issue.objects.exclude(status=Issue.Status.RESOLVED)
        self.assertEqual(open_issues.count(), 1)
        issue = open_issues.first()
        self.assertEqual(issue.category, Issue.Category.INTEGRATION)
        self.assertEqual(issue.severity, Issue.Severity.HIGH)
        self.assertEqual(issue.source, Issue.Source.SYSTEM_WATCHDOG)

        # Secondo run ancora FAIL: stessa Issue (dedup), non una nuova.
        with mock.patch.object(health, "run_ai_checks", return_value=self._checks(STATUS_FAIL)), \
             mock.patch("core.email_utils.send_hub_mail"):
            health.run_ai_readiness_alert()
        self.assertEqual(Issue.objects.exclude(status=Issue.Status.RESOLVED).count(), 1)

        # Ritorno OK: la Issue viene risolta.
        with mock.patch.object(health, "run_ai_checks", return_value=self._checks(STATUS_OK)), \
             mock.patch("core.email_utils.send_hub_mail"):
            health.run_ai_readiness_alert()
        self.assertEqual(Issue.objects.exclude(status=Issue.Status.RESOLVED).count(), 0)
        self.assertEqual(Issue.objects.filter(status=Issue.Status.RESOLVED).count(), 1)

    def test_warn_maps_to_medium_severity(self):
        from monitoring.models import Issue

        with mock.patch.object(health, "run_ai_checks", return_value=self._checks(STATUS_WARN)), \
             mock.patch("core.email_utils.send_hub_mail"):
            health.run_ai_readiness_alert()
        issue = Issue.objects.exclude(status=Issue.Status.RESOLVED).first()
        self.assertIsNotNone(issue)
        self.assertEqual(issue.severity, Issue.Severity.MEDIUM)
