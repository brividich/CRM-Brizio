"""Regressioni audit 09/10 (Fase 3): privacy del monitoring (M11) e notifiche di sicurezza."""
from __future__ import annotations

from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase


class MonitoringPrivacyTests(SimpleTestCase):
    """Audit M11: niente session ID riutilizzabili ne' token nelle URL del monitoring."""

    def test_session_key_is_hashed(self):
        from monitoring.services import hash_session_key

        hashed = hash_session_key("abc123sessionkey")
        self.assertNotIn("abc123sessionkey", hashed)
        self.assertEqual(hashed, hash_session_key("abc123sessionkey"))
        self.assertLessEqual(len(hashed), 64)
        self.assertEqual(hash_session_key(""), "")

    def test_query_string_is_stripped(self):
        from monitoring.services import strip_url_query

        self.assertEqual(strip_url_query("/approval-actions/x/?token=segreto#f"), "/approval-actions/x/")
        self.assertEqual(
            strip_url_query("https://hub.example.local/a/?q=mario"), "https://hub.example.local/a/"
        )

    def test_request_context_has_no_query_nor_raw_session(self):
        from monitoring.services import build_request_event_context

        request = RequestFactory().get("/anagrafica/ricerca/", {"q": "Rossi Mario"})
        request.session = SimpleNamespace(session_key="raw-session-key")
        request.user = SimpleNamespace(is_authenticated=False)
        context = build_request_event_context(request)
        self.assertEqual(context["current_url"], "/anagrafica/ricerca/")
        self.assertNotEqual(context["session_key"], "raw-session-key")


class SecurityNotificationTests(SimpleTestCase):
    """Mail all'utente per gli eventi di sicurezza sul suo account."""

    def test_notification_sent_to_user(self):
        from django.core import mail

        from core.security_notify import notify_security_event

        user = SimpleNamespace(email="utente@example.local")
        self.assertTrue(notify_security_event(user, "Password cambiata", "Test sintetico."))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("utente@example.local", mail.outbox[0].to)
        self.assertIn("Password cambiata", mail.outbox[0].subject)

    def test_user_without_email_is_skipped(self):
        from core.security_notify import notify_security_event

        self.assertFalse(notify_security_event(SimpleNamespace(email=""), "x", "y"))
