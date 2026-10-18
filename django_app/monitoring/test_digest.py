"""Test del digest giornaliero 'stato portale' (build + invio task)."""
from __future__ import annotations

import unittest.mock as mock

from django.test import TestCase, override_settings

from monitoring import health, tasks
from monitoring.digest import build_system_digest, render_system_digest
from monitoring.models import Issue

# Il DB di test non ha backup configurati: i check di backup (che nel digest di
# produzione devono comparire) qui segnalerebbero «nessun backup». Si escludono,
# come i check dell'infrastruttura (qcluster, disco, certificato), che dipendono
# dalla macchina su cui girano i test.
_SENZA_BACKUP = [
    n for n in health.available_checks()
    if n not in health.BACKUP_CHECK_NAMES and n not in health.INFRA_CHECK_NAMES
]


@override_settings(READYZ_CHECKS_ENABLED=_SENZA_BACKUP, READYZ_TTL_SECONDS=0)
class SystemDigestTests(TestCase):
    def test_build_all_green_on_empty_db(self):
        digest = build_system_digest()
        self.assertTrue(digest["all_green"])
        self.assertEqual(digest["open_total"], 0)
        subject, body = render_system_digest(digest)
        self.assertIn("tutto ok", subject)
        self.assertIn("Servizi", body)
        self.assertIn("Assistente AI: OPERATIVO", body)

    def test_build_flags_open_ai_issue(self):
        Issue.objects.create(
            code="INC-DG-1", title="AI · ollama_chat: FAIL", category=Issue.Category.INTEGRATION,
            severity=Issue.Severity.HIGH, source=Issue.Source.SYSTEM_WATCHDOG,
            status=Issue.Status.NEW, fingerprint="f" * 8, current_url="check:ai_ollama_chat",
        )
        digest = build_system_digest()
        self.assertFalse(digest["all_green"])
        self.assertFalse(digest["ai_ok"])
        _subject, body = render_system_digest(digest)
        self.assertIn("DEGRADATO", body)

    @override_settings(MONITORING_DIGEST_ALWAYS=True)
    def test_task_sends_heartbeat_when_always(self):
        with mock.patch("monitoring.services._admin_recipients", return_value=["a@b.c"]), \
             mock.patch("core.email_utils.send_hub_mail") as send:
            result = tasks.run_system_digest()
        self.assertTrue(result["sent"])
        send.assert_called_once()

    @override_settings(MONITORING_DIGEST_ALWAYS=False)
    def test_task_skips_when_green_and_not_always(self):
        with mock.patch("monitoring.services._admin_recipients", return_value=["a@b.c"]), \
             mock.patch("core.email_utils.send_hub_mail") as send:
            result = tasks.run_system_digest()
        self.assertFalse(result["sent"])
        send.assert_not_called()

    @override_settings(MONITORING_DIGEST_ALWAYS=True)
    def test_task_no_recipients_no_send(self):
        with mock.patch("monitoring.services._admin_recipients", return_value=[]), \
             mock.patch("core.email_utils.send_hub_mail") as send:
            result = tasks.run_system_digest()
        self.assertFalse(result["sent"])
        send.assert_not_called()
