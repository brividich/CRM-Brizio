"""Pagina «Configurazione › Parser»: stato reale, prova a secco, rielaborazione, PDF.

Prima la pagina elencava solo le righe di configurazione (tutte «Attivo»), il form
«sostituisci» non poteva modificare un parser esistente e gli allegati PDF arrivavano ai
parser come binario decodificato in UTF-8: nessun report WatchGuard in PDF veniva letto.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from security.models import (
    ParseStatus,
    SecurityConfigurationAuditLog,
    SecurityMailboxMessage,
    SecurityParserConfig,
    SecurityReport,
    SecuritySource,
    SecuritySourceFile,
    SourceType,
)
from security.services.parser_catalog import parser_overview, reprocess_items, test_parsers
from security.services.parser_engine import SKIP_UNTRUSTED_SENDER, run_pending_parsers
from security.services.text_extraction import extract_text

DEFENDER = "microsoft_defender_vulnerability_notification_email_parser"
SYNOLOGY = "synology_active_backup_email_parser"
WATCHGUARD = "watchguard_report_parser"
DEFENDER_BODY = "CVE-2025-12345\nAffected product: Contoso VPN Gateway\nCVSS: 9.8\nExposed devices: 3\nSeverity: Critical"


def _pdf_bytes(text):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


class TextExtractionTest(TestCase):
    def test_pdf_text_is_extracted_not_decoded_as_utf8(self):
        text, warnings = extract_text("report.pdf", _pdf_bytes("WatchGuard ThreatSync Summary"))
        self.assertIn("WatchGuard ThreatSync Summary", text)
        self.assertEqual(warnings, [])

    def test_broken_pdf_gives_warning_not_exception(self):
        text, warnings = extract_text("report.pdf", b"%PDF-1.4 rotto")
        self.assertEqual(text, "")
        self.assertTrue(warnings)

    def test_csv_decoded(self):
        text, warnings = extract_text("auth.csv", "user,ip\nmario,192.0.2.1\n".encode("utf-8-sig"))
        self.assertTrue(text.startswith("user,ip"))
        self.assertEqual(warnings, [])


class ParserOverviewTest(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Casella SOC", vendor="Demo", source_type=SourceType.EMAIL)

    def _rows(self):
        return {row["name"]: row for row in parser_overview()["parser_rows"]}

    def test_status_comes_from_real_outcomes(self):
        SecurityReport.objects.create(source=self.source, report_type="x", title="x", parser_name=DEFENDER)
        SecurityParserConfig.objects.create(parser_name=SYNOLOGY, enabled=False)
        SecurityMailboxMessage.objects.create(
            source=self.source, sender="a@example.test", subject="WatchGuard", parse_status=ParseStatus.FAILED,
            raw_payload={"parser_name": WATCHGUARD, "parser_error": "KeyError: 'report'"},
        )
        SecurityParserConfig.objects.create(parser_name="parser_che_non_esiste")
        rows = self._rows()
        self.assertEqual(rows[DEFENDER]["status"], "ok")
        self.assertEqual(rows[SYNOLOGY]["status"], "disabled")
        self.assertEqual(rows[WATCHGUARD]["status"], "error")
        self.assertIn("KeyError", rows[WATCHGUARD]["last_error"])
        self.assertEqual(rows["parser_che_non_esiste"]["status"], "orphan")
        self.assertFalse(rows["parser_che_non_esiste"]["registered"])

    def test_never_used_parser_is_idle(self):
        self.assertEqual(self._rows()[SYNOLOGY]["status"], "idle")


class DryRunTest(TestCase):
    def test_mail_dry_run_saves_nothing(self):
        result = test_parsers(sender="defender-noreply@microsoft.com", subject="Microsoft Defender vulnerability notification", body=DEFENDER_BODY)
        self.assertEqual(result["chosen_name"], DEFENDER)
        self.assertGreaterEqual(result["parsed"]["records_total"], 1)
        self.assertFalse(SecurityReport.objects.exists())
        self.assertFalse(SecurityMailboxMessage.objects.exists())

    def test_spoofed_sender_explained(self):
        result = test_parsers(sender="x@attacker.example", subject="Microsoft Defender vulnerability notification", body=DEFENDER_BODY)
        self.assertIsNone(result["chosen"])
        self.assertEqual(result["skip_code"], SKIP_UNTRUSTED_SENDER)

    def test_pdf_file_reaches_watchguard(self):
        result = test_parsers(filename="WatchGuard ThreatSync Summary.pdf", data=_pdf_bytes("WatchGuard ThreatSync Summary\nIncidents: 4"))
        self.assertEqual(result["chosen_name"], WATCHGUARD)
        self.assertIn("ThreatSync", result["extracted_preview"])
        self.assertNotIn("error", result)
        self.assertFalse(SecuritySourceFile.objects.exists())


class ReprocessTest(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Casella SOC", vendor="Demo", source_type=SourceType.EMAIL)

    def test_reenabled_parser_picks_up_skipped_items(self):
        config = SecurityParserConfig.objects.create(parser_name=DEFENDER, enabled=False)
        msg = SecurityMailboxMessage.objects.create(source=self.source, sender="defender-noreply@microsoft.com", subject="Microsoft Defender vulnerability notification", body=DEFENDER_BODY)
        spoof = SecurityMailboxMessage.objects.create(source=self.source, sender="x@attacker.example", subject="Microsoft Defender vulnerability notification", body=DEFENDER_BODY)
        run_pending_parsers()
        config.enabled = True
        config.save()
        result = reprocess_items()
        msg.refresh_from_db()
        spoof.refresh_from_db()
        self.assertEqual(msg.parse_status, ParseStatus.PARSED)
        self.assertNotIn("skip_reason", msg.raw_payload)
        # Lo spoofing resta scartato: non viene riproposto.
        self.assertEqual(spoof.parse_status, ParseStatus.SKIPPED)
        self.assertEqual(result["requeued"], 1)


class ParserPageTest(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(username="soc_parser_admin", is_staff=True, is_superuser=True)
        self.client.force_login(user)
        self.url = reverse("security:admin_config_parsers")

    def test_page_lists_registered_parsers_without_config(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "WatchGuard · tutti i report")
        self.assertContains(response, "Crea configurazione")

    def test_toggle_creates_and_flips_config_with_audit(self):
        self.client.post(self.url, {"action": "toggle", "parser_name": SYNOLOGY})
        self.assertFalse(SecurityParserConfig.objects.get(parser_name=SYNOLOGY).enabled)
        self.client.post(self.url, {"action": "toggle", "parser_name": SYNOLOGY})
        self.assertTrue(SecurityParserConfig.objects.get(parser_name=SYNOLOGY).enabled)
        self.assertTrue(SecurityConfigurationAuditLog.objects.filter(model_name="SecurityParserConfig", field_name="enabled").exists())

    def test_priority_edit_on_existing_parser(self):
        config = SecurityParserConfig.objects.create(parser_name=WATCHGUARD, priority=50)
        self.client.post(self.url, {"action": "priority", "object_id": config.pk, "priority": "5"})
        config.refresh_from_db()
        self.assertEqual(config.priority, 5)

    def test_registered_parser_cannot_be_deleted(self):
        config = SecurityParserConfig.objects.create(parser_name=WATCHGUARD)
        self.client.post(self.url, {"action": "delete-orphan", "object_id": config.pk})
        self.assertTrue(SecurityParserConfig.objects.filter(pk=config.pk).exists())
        orphan = SecurityParserConfig.objects.create(parser_name="vecchio_parser")
        self.client.post(self.url, {"action": "delete-orphan", "object_id": orphan.pk})
        self.assertFalse(SecurityParserConfig.objects.filter(pk=orphan.pk).exists())

    def test_dry_run_with_uploaded_pdf(self):
        upload = SimpleUploadedFile("WatchGuard ThreatSync.pdf", _pdf_bytes("WatchGuard ThreatSync Summary"), content_type="application/pdf")
        response = self.client.post(self.url, {"action": "test", "file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["test_result"]["chosen_name"], WATCHGUARD)
        self.assertContains(response, "Lo elaborerebbe")

    def test_non_admin_denied(self):
        self.client.force_login(get_user_model().objects.create(username="soc_parser_nobody"))
        # Il middleware ACL può fermarlo prima (redirect) o la view (403): mai la pagina.
        self.assertIn(self.client.get(self.url).status_code, {302, 403})
        self.client.post(self.url, {"action": "toggle", "parser_name": SYNOLOGY})
        self.assertFalse(SecurityParserConfig.objects.exists())
