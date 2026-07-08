from __future__ import annotations

import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

SAFE_SECRET = "django-insecure-valid-test-secret-key-with-enough-entropy"
LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "validate-deployment-email-tests",
    }
}


@override_settings(
    SECRET_KEY=SAFE_SECRET,
    DEBUG=False,
    ALLOWED_HOSTS=["testserver", "localhost"],
    CACHES=LOCMEM_CACHE,
)
class ValidateDeploymentFromEmailTests(TestCase):
    """Fix 1 — con backend SMTP il mittente non può restare vuoto (finirebbe su
    webmaster@localhost). Il check `email/from_email` lo segnala."""

    def _checks(self):
        out = StringIO()
        call_command("validate_deployment", "--format", "json", "--no-fail-on-fail", stdout=out)
        return json.loads(out.getvalue())["checks"]

    def _from_email_check(self):
        return [c for c in self._checks() if c["section"] == "email" and c["name"] == "from_email"]

    def test_smtp_senza_from_email_e_senza_host_user_segnala(self):
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="smtp.example.test",
            EMAIL_HOST_USER="",
            DEFAULT_FROM_EMAIL="",
        ):
            found = self._from_email_check()
        self.assertTrue(found, "atteso un check email/from_email")
        self.assertIn(found[0]["severity"], ("WARN", "FAIL"))

    def test_smtp_con_host_user_from_email_ok(self):
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="smtp.example.test",
            EMAIL_HOST_USER="postmaster@example.test",
            DEFAULT_FROM_EMAIL="",
        ):
            found = self._from_email_check()
        self.assertTrue(found)
        self.assertEqual(found[0]["severity"], "OK")
