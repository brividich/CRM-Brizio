"""Monitoring: alert e digest instradati nel frame email HUB (send_hub_mail).

- ``render_system_digest_html`` rende lo stato sistema come card con badge;
- ``emit_monitoring_alert`` esce nel frame HUB (logo + badge), col ``text/plain``
  pulito (niente tag HTML grezzi).
"""
from __future__ import annotations

import unittest.mock as mock

from django.core import mail
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from monitoring import health
from monitoring.digest import render_system_digest_html


def _html_alt(email) -> str:
    for content, mimetype in getattr(email, "alternatives", []):
        if mimetype == "text/html":
            return content
    return ""


def _digest(all_green=True, **over):
    d = {
        "generated_at": None,
        "readyz_status": "ok" if all_green else "fail",
        "services_bad": [] if all_green else ["ollama_chat"],
        "ai_ok": all_green,
        "ai_issues": [] if all_green else ["AI · ollama_chat: FAIL"],
        "severity": {} if all_green else {"high": 2},
        "open_total": 0 if all_green else 2,
        "job_failed_today": 0,
        "job_missing": 0,
        "all_green": all_green,
    }
    d.update(over)
    return d


class RenderDigestHtmlTests(SimpleTestCase):
    def test_all_green_badge_operativo(self):
        html = render_system_digest_html(_digest(all_green=True))
        self.assertIn("OPERATIVO", html)
        self.assertIn("<table", html)

    def test_degraded_badge_e_servizio(self):
        html = render_system_digest_html(_digest(all_green=False))
        self.assertIn("DEGRADATO", html)
        self.assertIn("ollama_chat", html)


class AlertEmailFrameTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(MONITORING_NOTIFY_CRITICAL_BY_EMAIL=True,
                       MONITORING_ALERT_QUIET_HOURS_ENABLED=False)
    def test_alert_instradato_nel_frame_hub(self):
        with mock.patch("monitoring.services._admin_recipients", return_value=["a@b.c"]):
            sent = health.emit_monitoring_alert(
                subject="Test alert",
                body="Servizio X irraggiungibile.\nControllare la centrale.",
                fingerprint="f" * 8, state_key="test:alert:key",
            )
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        html = _html_alt(email)
        self.assertIn("novicrmhub.png", html)            # frame HUB
        self.assertIn("Servizio X irraggiungibile", html)
        self.assertNotIn("<", email.body)                # plain senza tag HTML
