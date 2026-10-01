"""Mail non pertinenti = scartate (non fallite), riparazione dei dati esistenti, filtri consigliati
e data proposta da «Importa storico»."""
import importlib
from datetime import timedelta

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import ParseStatus, SecurityMailboxMessage, SecurityMailboxSource, SecuritySource, SecuritySourceFile
from security.services.security_inbox_pipeline import process_mailbox_message, process_source_file
from security.views import RECOMMENDED_SUBJECT_FILTERS


def _message(source, subject="[RENTRI] 265 registrazioni in scadenza", body="Elenco registrazioni", **extra):
    return SecurityMailboxMessage.objects.create(source=source, subject=subject, body=body, sender="avviso@example.test", **extra)


class SkippedIsNotFailedTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Casella", source_type="email", vendor="mailbox")

    def test_mail_no_parser_recognizes_is_skipped(self):
        message = _message(self.source)
        process_mailbox_message(message)
        message.refresh_from_db()
        self.assertEqual(message.parse_status, ParseStatus.SKIPPED)
        self.assertEqual(message.raw_payload["skip_reason"], "no_parser")

    def test_file_no_parser_recognizes_is_skipped(self):
        source_file = SecuritySourceFile.objects.create(source=self.source, original_name="note.txt", file_type="manual", content="niente da vedere")
        process_source_file(source_file)
        source_file.refresh_from_db()
        self.assertEqual(source_file.parse_status, ParseStatus.SKIPPED)

    def test_recognized_report_is_still_parsed(self):
        message = _message(
            self.source,
            subject="NAS Active Backup for Business - attività di backup JOB su NAS completata",
            body="L'attività di backup JOB su NAS è stata completata.\nOra d’inizio: 17/06/2026 10:00\nOra di fine: 17/06/2026 10:01\nDimensioni trasferite: 522.6 MB\nElenco dispositivi: PC1\n",
        )
        process_mailbox_message(message)
        message.refresh_from_db()
        self.assertEqual(message.parse_status, ParseStatus.PARSED)


class RepairMigrationTests(TestCase):
    def test_failed_but_skipped_rows_are_repaired_real_failures_are_kept(self):
        source = SecuritySource.objects.create(name="Casella", source_type="email", vendor="mailbox")
        skipped_old = _message(source, parse_status=ParseStatus.FAILED, raw_payload={"skip_reason": "no_parser"})
        skipped_older = _message(source, parse_status=ParseStatus.FAILED, pipeline_result={"status": "skipped", "parser_matched": False})
        real_failure = _message(source, parse_status=ParseStatus.FAILED, raw_payload={"parser_error": "boom", "parser_name": "x"})
        untouched = _message(source, parse_status=ParseStatus.PARSED)
        migration = importlib.import_module("security.migrations.0014_repair_skipped_status")
        migration.repair_skipped_status(django_apps, None)
        for row in (skipped_old, skipped_older, real_failure, untouched):
            row.refresh_from_db()
        self.assertEqual(skipped_old.parse_status, ParseStatus.SKIPPED)
        self.assertEqual(skipped_older.parse_status, ParseStatus.SKIPPED)
        self.assertEqual(real_failure.parse_status, ParseStatus.FAILED)
        self.assertEqual(untouched.parse_status, ParseStatus.PARSED)


class MailboxDetailTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create(username="soc_filtri", is_staff=True, is_superuser=True))
        self.mailbox = SecurityMailboxSource.objects.create(name="Personale", code="personale", source_type="graph", mailbox_address="x@example.test")
        self.url = reverse("security:admin_mailbox_source_detail", args=["personale"])

    def test_unfiltered_mailbox_is_flagged_and_filters_can_be_applied(self):
        self.assertContains(self.client.get(self.url), "legge TUTTE le mail")
        self.client.post(self.url, {"action": "recommended_filters"})
        self.mailbox.refresh_from_db()
        self.assertEqual(self.mailbox.subject_include_text.splitlines(), RECOMMENDED_SUBJECT_FILTERS)
        self.assertNotContains(self.client.get(self.url), "legge TUTTE le mail")

    def test_recommended_filters_match_the_supported_report_subjects(self):
        from security.services.mailbox_ingestion import should_accept_message
        from security.services.mailbox_providers import MailboxMessage

        self.mailbox.subject_include_text = "\n".join(RECOMMENDED_SUBJECT_FILTERS)

        def accepted(subject):
            message = MailboxMessage(
                provider_message_id="1", internet_message_id="", sender="a@b.test", recipients=[], subject=subject,
                received_at=timezone.now(), body_text="", body_html="", attachments=[],
            )
            return should_accept_message(self.mailbox, message)

        for subject in ("Scheduled Firebox Report", "[WatchGuard Endpoint Security 360] [X] Threats detected between 9/30/2026", "NAS-BCK Active Backup for Business - attività di backup J su N completata", "[Success] Backup QLIK (4 objects)", "I: Watchguard EPDR Stato rete"):
            self.assertTrue(accepted(subject), subject)
        for subject in ("[RENTRI] 265 registrazioni in scadenza — soglia 30 giorni", "R: Conflitto assenza per X - 29/09/2026"):
            self.assertFalse(accepted(subject), subject)

    def test_history_date_continues_from_where_reading_reached(self):
        reached = timezone.now() - timedelta(days=40)
        self.mailbox.last_success_at = reached
        self.mailbox.save(update_fields=["last_success_at"])
        response = self.client.get(self.url)
        self.assertEqual(response.context["history_default"], timezone.localtime(reached).date().isoformat())

    def test_history_date_without_reading_defaults_to_a_year_ago(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["history_default"], (timezone.localdate() - timedelta(days=365)).isoformat())
