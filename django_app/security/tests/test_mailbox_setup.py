"""Caselle mail configurabili dall'HUB: senza di loro il Security Center non riceve dati.

Prima: autoconfig e «Sorgenti» configuravano solo il riconoscimento dei report, la
casella da leggere non si poteva creare da interfaccia e nessun task la leggeva.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityMailboxIngestionRun, SecurityMailboxSource
from security.services.diagnostics import _mailbox_sources_check
from security.services.mailbox_providers import MailboxMessage
from security.services.mailbox_setup import graph_credentials_status

GRAPH_ENV = {"GRAPH_TENANT_ID": "tenant-x", "GRAPH_CLIENT_ID": "client-x", "GRAPH_CLIENT_SECRET": "super-secret-value-123"}


def _mail(sender, subject, body=""):
    return MailboxMessage(
        provider_message_id=subject, internet_message_id=None, sender=sender, recipients=["soc@example.test"],
        subject=subject, received_at=timezone.now() - timedelta(hours=1), body_text=body, body_html="", attachments=[],
    )


class _Admin(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(username="soc_mail_admin", is_staff=True, is_superuser=True)
        self.client.force_login(user)

    def _source(self, **extra):
        data = {"name": "Casella SOC", "code": "casella-soc", "source_type": "graph", "mailbox_address": "soc@example.test"}
        data.update(extra)
        return SecurityMailboxSource.objects.create(**data)


class MailboxListCreateTest(_Admin):
    def test_create_from_ui(self):
        response = self.client.post(reverse("security:admin_mailbox_sources_list"), {
            "name": "Report sicurezza", "enabled": "on", "source_type": "graph",
            "mailbox_address": "soc@example.test", "expected_every_hours": 24, "max_messages_per_run": 50,
            "process_attachments": "on", "process_email_body": "on",
        })
        source = SecurityMailboxSource.objects.get(name="Report sicurezza")
        self.assertEqual(source.code, "report-sicurezza")
        self.assertRedirects(response, reverse("security:admin_mailbox_source_detail", args=[source.code]))

    def test_graph_requires_address(self):
        response = self.client.post(reverse("security:admin_mailbox_sources_list"), {
            "name": "Senza indirizzo", "source_type": "graph", "expected_every_hours": 0, "max_messages_per_run": 50,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SecurityMailboxSource.objects.filter(name="Senza indirizzo").exists())
        self.assertContains(response, "Obbligatorio per leggere la casella")

    @mock.patch.dict("os.environ", GRAPH_ENV)
    def test_credentials_status_never_shows_values(self):
        status = graph_credentials_status()
        self.assertTrue(status["complete"])
        html = self.client.get(reverse("security:admin_mailbox_sources_list")).content.decode()
        self.assertNotIn("super-secret-value-123", html)
        self.assertNotIn("tenant-x", html)
        self.assertIn("Ambiente del server", html)

    def test_nav_link_present(self):
        html = self.client.get(reverse("security:dashboard")).content.decode()
        self.assertIn(reverse("security:admin_mailbox_sources_list"), html)


class MailboxPreviewRunTest(_Admin):
    def test_preview_shows_recognition_without_importing(self):
        source = self._source()
        provider = mock.Mock()
        provider.list_messages.return_value = [
            _mail("defender-noreply@microsoft.com", "Microsoft Defender vulnerability notification",
                  "CVE-2025-1\nAffected product: Contoso\nCVSS: 9.8\nExposed devices: 2"),
            _mail("news@example.test", "Newsletter"),
        ]
        with mock.patch("security.services.mailbox_providers.get_provider", return_value=provider):
            response = self.client.post(reverse("security:admin_mailbox_source_detail", args=[source.code]), {"action": "preview"})
        self.assertContains(response, "Riconosciuta")
        self.assertContains(response, "Non riconosciuta")
        self.assertContains(response, "Nulla è stato importato")
        from security.models import SecurityMailboxMessage

        self.assertEqual(SecurityMailboxMessage.objects.count(), 0)
        source.refresh_from_db()
        self.assertIsNone(source.last_success_at)  # l'anteprima non sposta il punto di ripresa

    def test_preview_error_is_explained(self):
        source = self._source()
        provider = mock.Mock()
        provider.list_messages.side_effect = RuntimeError("Missing required Microsoft Graph setting: GRAPH_TENANT_ID")
        with mock.patch("security.services.mailbox_providers.get_provider", return_value=provider):
            response = self.client.post(reverse("security:admin_mailbox_source_detail", args=[source.code]), {"action": "preview"})
        self.assertContains(response, "Lettura non riuscita")
        self.assertContains(response, "Mail.Read")

    def test_run_reports_failure_instead_of_ok(self):
        source = self._source()
        failed = SecurityMailboxIngestionRun(source=source, status="failed", error_message="401 Unauthorized")
        with mock.patch("security.services.mailbox_ingestion.run_mailbox_ingestion", return_value=failed):
            response = self.client.post(reverse("security:admin_mailbox_source_detail", args=[source.code]), {"action": "run"}, follow=True)
        self.assertContains(response, "Lettura fallita: 401 Unauthorized")

    def test_bulk_run_reports_failure(self):
        self._source()
        failed = SecurityMailboxIngestionRun(status="failed", error_message="403 Forbidden")
        with mock.patch("security.services.mailbox_ingestion.run_mailbox_ingestion", return_value=failed):
            response = self.client.post(reverse("security:run_mailbox_ingestion"), follow=True)
        self.assertContains(response, "0 ok, 1 in errore")


class CycleScheduleDiagnosticsTest(TestCase):
    def test_cycle_isolates_failing_step(self):
        from security.tasks import run_security_cycle_task

        with mock.patch("security.tasks.ingest_security_mailboxes_task", side_effect=RuntimeError("graph giù")):
            result = run_security_cycle_task()
        self.assertTrue(str(result["mailboxes"]).startswith("errore"))
        self.assertIn("kpis", result)
        self.assertNotIn("errore", str(result["rules"]))

    def test_cycle_is_scheduled(self):
        from automazioni.schedules import SCHEDULES

        spec = next(s for s in SCHEDULES if s["name"] == "security_cycle")
        self.assertEqual(spec["func"], "security.tasks.run_security_cycle_task")
        self.assertEqual(spec["schedule_type"], "I")

    def test_diagnostics_flags_missing_mailbox(self):
        self.assertEqual(_mailbox_sources_check()["status"], "error")

    @mock.patch.dict("os.environ", GRAPH_ENV)
    def test_diagnostics_ok_with_mailbox_and_credentials(self):
        SecurityMailboxSource.objects.create(name="C", code="c", source_type="graph", mailbox_address="soc@example.test")
        self.assertEqual(_mailbox_sources_check()["status"], "ok")
