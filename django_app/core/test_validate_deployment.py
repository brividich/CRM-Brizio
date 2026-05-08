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

    def test_short_secret_key_warns_outside_prod(self):
        out = StringIO()

        # 32 caratteri, nessun placeholder ne' prefisso 'django-insecure-':
        # fuori prod il check deve produrre WARN (non rompe test/dev).
        with override_settings(SECRET_KEY="abcd1234" * 4):
            call_command(
                "validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out
            )

        payload = json.loads(out.getvalue())
        secret_checks = [
            item
            for item in payload["checks"]
            if item["section"] == "django" and item["name"] == "SECRET_KEY"
        ]
        self.assertTrue(secret_checks)
        self.assertEqual(secret_checks[0]["severity"], "WARN")
        self.assertIn("corta", secret_checks[0]["message"].lower())

    def test_django_insecure_prefix_warns_outside_prod(self):
        out = StringIO()

        # SAFE_SECRET (default override) usa 'django-insecure-' prefix:
        # in test deve essere WARN ma il comando non deve sollevare CommandError
        # con --no-fail-on-fail.
        call_command(
            "validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out
        )

        payload = json.loads(out.getvalue())
        secret_checks = [
            item
            for item in payload["checks"]
            if item["section"] == "django"
            and item["name"] == "SECRET_KEY"
            and item["severity"] == "WARN"
        ]
        self.assertTrue(secret_checks)
        self.assertIn("django-insecure", secret_checks[0]["message"].lower())

    def test_wildcard_allowed_hosts_warn_outside_prod(self):
        out = StringIO()

        with override_settings(ALLOWED_HOSTS=["*"]):
            call_command(
                "validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out
            )

        payload = json.loads(out.getvalue())
        host_checks = [
            item
            for item in payload["checks"]
            if item["section"] == "django" and item["name"] == "ALLOWED_HOSTS"
        ]
        self.assertTrue(host_checks)
        self.assertEqual(host_checks[0]["severity"], "WARN")
        self.assertIn("wildcard", host_checks[0]["message"].lower())

    def test_assets_private_root_under_media_root_warns(self):
        import os
        from pathlib import Path

        out = StringIO()
        media_dir = Path(tempfile.gettempdir()) / "novicrom-media-test"
        private_dir = media_dir / "private"
        media_dir.mkdir(parents=True, exist_ok=True)
        private_dir.mkdir(parents=True, exist_ok=True)

        try:
            with override_settings(
                MEDIA_ROOT=str(media_dir),
                ASSETS_PRIVATE_ROOT=str(private_dir),
            ):
                call_command(
                    "validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out
                )
        finally:
            # cleanup best-effort
            try:
                private_dir.rmdir()
                media_dir.rmdir()
            except OSError:
                pass

        payload = json.loads(out.getvalue())
        containment = [
            item
            for item in payload["checks"]
            if item["section"] == "static_media"
            and item["name"] == "ASSETS_PRIVATE_ROOT_containment"
        ]
        self.assertTrue(containment)
        # Fuori prod il containment violato resta WARN (vincolo sandbox).
        self.assertEqual(containment[0]["severity"], "WARN")
        self.assertIn("media_root", containment[0]["message"].lower())

    def test_csrf_trusted_origins_wildcard_warns(self):
        out = StringIO()

        with override_settings(CSRF_TRUSTED_ORIGINS=["*"]):
            call_command(
                "validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out
            )

        payload = json.loads(out.getvalue())
        csrf_checks = [
            item
            for item in payload["checks"]
            if item["section"] == "security" and item["name"] == "CSRF_TRUSTED_ORIGINS"
        ]
        self.assertTrue(csrf_checks)
        self.assertEqual(csrf_checks[0]["severity"], "WARN")
        self.assertIn("wildcard", csrf_checks[0]["message"].lower())
