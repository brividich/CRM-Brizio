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
