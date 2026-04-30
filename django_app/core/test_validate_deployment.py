from __future__ import annotations

import json
import tempfile
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


SAFE_SECRET = "django-insecure-valid-test-secret-key-with-enough-entropy"
LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "validate-deployment-tests",
    }
}


@override_settings(
    SECRET_KEY=SAFE_SECRET,
    DEBUG=False,
    ALLOWED_HOSTS=["testserver", "localhost"],
    TIME_ZONE="Europe/Rome",
    APP_VERSION="9.9.9-test",
    CACHES=LOCMEM_CACHE,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STATIC_ROOT=tempfile.gettempdir(),
    MEDIA_ROOT=tempfile.gettempdir(),
    GRAPH_TENANT_ID="tenant-test",
    GRAPH_CLIENT_ID="client-test",
    GRAPH_CLIENT_SECRET="graph-secret-test-value",
    GRAPH_SITE_ID="site-test",
    APPROVAL_MAILBOX_ADDRESS="approvals@example.test",
    LDAP_ENABLED=False,
)
class ValidateDeploymentCommandTests(TestCase):
    def test_json_output_is_valid(self):
        out = StringIO()

        call_command("validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out)

        payload = json.loads(out.getvalue())
        self.assertIn("summary", payload)
        self.assertIn("checks", payload)
        self.assertIsInstance(payload["checks"], list)

    def test_secret_key_placeholder_generates_fail(self):
        out = StringIO()

        with override_settings(SECRET_KEY="change-me"), self.assertRaises(CommandError):
            call_command("validate_deployment", "--format", "json", stdout=out)

        payload = json.loads(out.getvalue())
        matching = [
            item
            for item in payload["checks"]
            if item["name"] == "SECRET_KEY" and item["severity"] == "FAIL"
        ]
        self.assertTrue(matching)

    def test_cache_check_ok_with_locmem(self):
        out = StringIO()

        call_command("validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out)

        payload = json.loads(out.getvalue())
        roundtrip = [
            item
            for item in payload["checks"]
            if item["section"] == "cache" and item["name"] == "roundtrip"
        ][0]
        self.assertEqual(roundtrip["severity"], "OK")

    def test_graph_placeholder_generates_warning(self):
        out = StringIO()

        with override_settings(
            GRAPH_TENANT_ID="<GRAPH_TENANT_ID>",
            GRAPH_CLIENT_ID="<GRAPH_CLIENT_ID>",
            GRAPH_CLIENT_SECRET="<GRAPH_CLIENT_SECRET>",
            GRAPH_SITE_ID="site-test",
        ):
            call_command("validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out)

        payload = json.loads(out.getvalue())
        credentials = [
            item
            for item in payload["checks"]
            if item["section"] == "graph" and item["name"] == "credentials"
        ][0]
        self.assertEqual(credentials["severity"], "WARN")
        self.assertIn("placeholder", credentials["message"].lower())

    def test_fail_on_warn_raises_when_warnings_are_present(self):
        out = StringIO()

        with override_settings(APPROVAL_MAILBOX_ADDRESS=""):
            with self.assertRaises(CommandError):
                call_command("validate_deployment", "--format", "json", "--fail-on-warn", stdout=out)

        payload = json.loads(out.getvalue())
        self.assertGreater(payload["summary"]["WARN"], 0)
        self.assertEqual(payload["summary"]["FAIL"], 0)

    def test_secrets_are_not_printed(self):
        out = StringIO()
        secret = "super-sensitive-client-secret-value"
        email_password = "super-sensitive-email-password"

        with override_settings(
            SECRET_KEY=secret,
            GRAPH_CLIENT_SECRET=secret,
            EMAIL_HOST_PASSWORD=email_password,
        ):
            call_command("validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out)

        rendered = out.getvalue()
        self.assertNotIn(secret, rendered)
        self.assertNotIn(email_password, rendered)
        self.assertIn("<set>", rendered)
