"""Robustezza SOC: parser che spiegano cosa hanno letto e dati illeggibili che non diventano «tutto ok».

Casi coperti (tutti dati sintetici):

1. Defender senza «Exposed devices» leggibile: prima valeva 0 e chiudeva da solo l'alert della CVE.
2. Synology «completata senza errori» / «Errori: 0»: prima diventava «failed» per la parola «errore».
3. Backup senza orari: job+stato uguali ogni giorno, il secondo esito veniva scartato come duplicato.
4. Un evento malformato interrompeva la valutazione di tutti gli eventi, a ogni ciclo.
5. Ogni parser produce una «lettura» (campi letti/mancanti, qualità) e spiega perché riconosce un contenuto.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    ParseStatus,
    SecurityAlert,
    SecurityEventRecord,
    SecurityMailboxMessage,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.parsers.base import QUALITA_COMPLETA, QUALITA_DA_VERIFICARE, QUALITA_PARZIALE, Lettura
from security.parsers.microsoft_defender_vulnerability_notification_email_parser import (
    MicrosoftDefenderVulnerabilityNotificationEmailParser,
    microsoft_defender_vulnerability_notification_email_parser as parse_defender,
)
from security.parsers.synology_active_backup_email_parser import parse_synology_active_backup_email
from security.parsers.veeam_backup_email_parser import parse_veeam_email
from security.services import rule_engine
from security.services.parser_catalog import parser_overview, test_parsers
from security.services.parser_engine import run_pending_parsers, spiega_errore
from security.services.rule_engine import EVALUATION_ERROR, evaluate_security_rules
from security.tests.test_parsers_real_formats import EXEC_SUMMARY, SYNOLOGY_OK, SYNOLOGY_SUBJECT_OK, VEEAM, _wg

SENDER = "defender-noreply@microsoft.com"
SUBJECT = "New vulnerabilities notification from Microsoft Defender for Endpoint"


class LetturaTests(SimpleTestCase):
    def test_quality_levels(self):
        lettura = Lettura("Prova")
        lettura.campo("A", "x", obbligatorio=True)
        self.assertEqual(lettura.qualita, QUALITA_COMPLETA)
        lettura.campo("B", None)
        self.assertEqual(lettura.qualita, QUALITA_PARZIALE)
        lettura.campo("C", "", obbligatorio=True)
        self.assertEqual(lettura.qualita, QUALITA_DA_VERIFICARE)
        data = lettura.as_dict()
        self.assertEqual(data["qualita_label"], "Da verificare")
        self.assertEqual([row["campo"] for row in data["campi_mancanti"]], ["B", "C"])

    def test_long_values_are_shortened(self):
        lettura = Lettura("Prova")
        lettura.campo("Lista", [f"PC-{i}" for i in range(8)])
        self.assertIn("(+3)", lettura.as_dict()["campi_letti"][0]["valore"])


class DefenderExposedDevicesTests(SimpleTestCase):
    def test_missing_exposed_count_is_flagged_not_zero(self):
        parsed = parse_defender(SUBJECT, "CVE-2099-0001\nSeverity: High\nCVSS score: 7.5\nAffected product: Edge", sender=SENDER)
        finding = parsed["findings"][0]
        self.assertEqual(finding["exposed_devices"], 0)
        self.assertTrue(finding["exposed_devices_unparsed"])
        self.assertEqual(parsed["lettura"]["qualita"], QUALITA_DA_VERIFICARE)
        self.assertTrue(any("dispositivi esposti" in warning for warning in parsed["parse_warnings"]))

    def test_readable_zero_is_a_real_zero(self):
        parsed = parse_defender(SUBJECT, "CVE-2099-0002\nSeverity: High\nExposed devices: 0\nAffected product: Edge", sender=SENDER)
        self.assertFalse(parsed["findings"][0]["exposed_devices_unparsed"])

    def test_critical_with_unknown_count_is_a_review_candidate(self):
        parsed = parse_defender(SUBJECT, "CVE-2099-0003\nSeverity: Critical\nCVSS score: 9.8\nAffected product: Edge", sender=SENDER)
        self.assertEqual([c["type"] for c in parsed["alert_candidates"]], ["defender_unreadable_vulnerability"])

    def test_complete_notification_reads_complete(self):
        parsed = parse_defender(SUBJECT, "Organization: Demo Srl\nCVE-2099-0004\nSeverity: Critical\nCVSS score: 9.8\nExposed devices: 3\nAffected product: Edge", sender=SENDER)
        self.assertEqual(parsed["lettura"]["qualita"], QUALITA_COMPLETA)

    def test_why_explains_sender_and_cves(self):
        item = SimpleNamespace(sender=SENDER, subject=SUBJECT, body="CVE-2099-0005 e CVE-2099-0006")
        reasons = MicrosoftDefenderVulnerabilityNotificationEmailParser().perche_riconosce(item)
        self.assertTrue(any("Mittente attendibile" in reason for reason in reasons))
        self.assertTrue(any("2 CVE" in reason for reason in reasons))


class DefenderExposedDevicesFlowTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Defender", vendor="Microsoft", source_type=SourceType.EMAIL)

    def _ingest(self, body):
        SecurityMailboxMessage.objects.create(source=self.source, sender=SENDER, subject=SUBJECT, body=body)
        run_pending_parsers()
        evaluate_security_rules()

    def test_unreadable_count_does_not_close_the_open_alert(self):
        self._ingest("CVE-2099-0100\nSeverity: Critical\nCVSS score: 9.8\nExposed devices: 4\nAffected product: Edge")
        alert = SecurityAlert.objects.get()
        self._ingest("CVE-2099-0100\nSeverity: Critical\nCVSS score: 9.8\nAffected product: Edge")
        alert.refresh_from_db()
        self.assertNotEqual(alert.status, Status.RESOLVED)

    def test_readable_zero_still_closes_the_alert(self):
        self._ingest("CVE-2099-0101\nSeverity: Critical\nCVSS score: 9.8\nExposed devices: 4\nAffected product: Edge")
        self._ingest("CVE-2099-0101\nSeverity: Critical\nCVSS score: 9.8\nExposed devices: 0\nAffected product: Edge")
        self.assertEqual(SecurityAlert.objects.get().status, Status.RESOLVED)

    def test_critical_with_unknown_count_raises_manual_review(self):
        self._ingest("CVE-2099-0102\nSeverity: Critical\nCVSS score: 9.8\nAffected product: Edge")
        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.severity, Severity.HIGH)
        self.assertTrue(alert.decision_trace["exposed_devices_unparsed"])

    def test_item_records_reading_quality(self):
        self._ingest("CVE-2099-0103\nSeverity: High\nCVSS score: 7.0\nAffected product: Edge")
        message = SecurityMailboxMessage.objects.get()
        self.assertEqual(message.raw_payload["lettura_qualita"], QUALITA_DA_VERIFICARE)


class SynologyStatusTests(SimpleTestCase):
    def test_no_errors_phrase_is_success(self):
        body = SYNOLOGY_OK.replace("è stata completata.", "è stata completata senza errori.") + "Errori: 0\n"
        payload = parse_synology_active_backup_email("Backup JOB-DEMO su NAS-DEMO", body)
        self.assertEqual(payload["status"], "completed")

    def test_subject_outcome_wins_over_body_noise(self):
        payload = parse_synology_active_backup_email(SYNOLOGY_SUBJECT_OK, SYNOLOGY_OK + "Log: nessun errore critico, 1 error page cached\n")
        self.assertEqual(payload["status"], "completed")

    def test_real_failure_is_still_failed(self):
        payload = parse_synology_active_backup_email(
            "NAS Active Backup for Business - attività di backup JOB-DEMO su NAS-DEMO non riuscita",
            SYNOLOGY_OK.replace("è stata completata", "non è riuscita"),
        )
        self.assertEqual(payload["status"], "failed")

    def test_unknown_outcome_is_declared(self):
        payload = parse_synology_active_backup_email("Backup JOB-DEMO su NAS-DEMO", "Ora d'inizio: 17/06/2026 10:00\n")
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["lettura"]["qualita"], QUALITA_DA_VERIFICARE)

    def test_full_mail_reads_complete_fields(self):
        lettura = parse_synology_active_backup_email(SYNOLOGY_SUBJECT_OK, SYNOLOGY_OK)["lettura"]
        letti = {row["campo"] for row in lettura["campi_letti"]}
        self.assertTrue({"Esito", "Nome del job", "NAS", "Inizio", "Fine", "Dispositivi"} <= letti)
        self.assertEqual(lettura["qualita"], QUALITA_COMPLETA)


class BackupWithoutTimesTests(TestCase):
    """Due esiti dello stesso job in giorni diversi, senza orari nel testo: devono restare due."""

    def setUp(self):
        self.source = SecuritySource.objects.create(name="Backup", vendor="Synology", source_type=SourceType.EMAIL)

    def _mail(self, subject, body, days_ago):
        message = SecurityMailboxMessage.objects.create(source=self.source, sender="nas@example.test", subject=subject, body=body)
        SecurityMailboxMessage.objects.filter(pk=message.pk).update(received_at=timezone.now() - timedelta(days=days_ago))

    def test_synology_daily_mails_are_not_duplicates(self):
        body = "L'attività di backup JOB-DEMO su NAS-DEMO è stata completata.\nElenco dispositivi: PC-DEMO\n"
        self._mail(SYNOLOGY_SUBJECT_OK, body, days_ago=1)
        self._mail(SYNOLOGY_SUBJECT_OK, body, days_ago=0)
        run_pending_parsers()
        self.assertEqual(BackupJobRecord.objects.count(), 2)

    def test_veeam_without_date_uses_received_day(self):
        body = VEEAM.replace("martedì 29 settembre 2026 23:30:12\n", "")
        received = timezone.make_aware(datetime(2026, 10, 1, 7, 0))
        payload = parse_veeam_email("[Success] Backup DEMO (2 objects)", body, received_at=received)
        self.assertTrue(payload["start_time"].startswith("2026-10-01T23:30"))
        self.assertTrue(any("data di ricezione" in warning for warning in payload["parse_warnings"]))

    def test_veeam_daily_mails_without_times_are_not_duplicates(self):
        body = "Backup job: NIGHTLY\nSuccess\n"
        self._mail("[Success] NIGHTLY", body, days_ago=1)
        self._mail("[Success] NIGHTLY", body, days_ago=0)
        run_pending_parsers()
        self.assertEqual(BackupJobRecord.objects.count(), 2)


class WatchGuardLetturaTests(SimpleTestCase):
    def test_executive_summary_reading(self):
        report = _wg("TestFW_Executive_Summary_2026-09-28T22_00_to_2026-09-29T21_59.pdf", EXEC_SUMMARY)
        lettura = report.payload["lettura"]
        self.assertEqual(lettura["formato"], "Firebox · Executive Summary")
        self.assertNotEqual(lettura["qualita"], QUALITA_DA_VERIFICARE)

    def test_all_zero_figures_raise_a_warning(self):
        report = _wg("TestFW_Executive_Summary.pdf", "Executive Summary Report\nFrom\n2026-09-29 00:00 (Europe/Berlin)\nTo\n2026-09-29 23:59 (Europe/Berlin)\n")
        lettura = report.payload["lettura"]
        self.assertTrue(any("zero" in warning for warning in lettura["avvisi"]))


class RuleEngineIsolationTests(TestCase):
    """Un evento che fa esplodere la sua regola non deve bloccare gli altri, né essere ripreso all'infinito."""

    def setUp(self):
        self.source = SecuritySource.objects.create(name="Fonte", vendor="Demo", source_type=SourceType.EMAIL)

    def _event(self, event_type, payload, minutes_ago):
        return SecurityEventRecord.objects.create(
            source=self.source, event_type=event_type, severity=Severity.INFO,
            occurred_at=timezone.now() - timedelta(minutes=minutes_ago),
            fingerprint=f"fp-{event_type}-{minutes_ago}", dedup_hash=f"dd-{event_type}-{minutes_ago}", payload=payload,
        )

    def test_poison_event_is_isolated(self):
        poison = self._event("backup_job", {"status": "failed", "job_name": "X"}, minutes_ago=10)
        good = self._event("unknown_type", {"detail": "ok"}, minutes_ago=5)

        def boom(event):
            raise ValueError("payload inatteso")

        with mock.patch.dict(rule_engine._HANDLERS, {"backup_job": boom}):
            with self.assertLogs("security.services.rule_engine", level="ERROR"):
                evaluate_security_rules()

        poison.refresh_from_db()
        good.refresh_from_db()
        self.assertEqual(poison.decision_trace["decision"], EVALUATION_ERROR)
        self.assertIn("payload inatteso", poison.decision_trace["error"])
        self.assertEqual(good.decision_trace["decision"], "kpi_only", good.decision_trace)
        self.assertEqual(evaluate_security_rules(), 0)  # nessuno resta in coda per sempre

    def test_partial_writes_of_the_failing_event_are_rolled_back(self):
        self._event("backup_job", {"status": "failed", "job_name": "X"}, minutes_ago=10)
        with mock.patch("security.services.rule_engine.create_backup_ticket", side_effect=RuntimeError("ticket rotto")):
            with self.assertLogs("security.services.rule_engine", level="ERROR"):
                evaluate_security_rules()
        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_non_numeric_exposed_devices_does_not_crash(self):
        event = self._event("vulnerability_finding", {"cve": "CVE-2099-0200", "exposed_devices": "n/d", "cvss": "x"}, minutes_ago=1)
        evaluate_security_rules()
        event.refresh_from_db()
        self.assertNotEqual(event.decision_trace.get("decision"), EVALUATION_ERROR)


class ParserErrorExplanationTests(TestCase):
    def test_hints(self):
        self.assertIn("«cve»", spiega_errore(KeyError("cve")))
        self.assertIn("formato atteso", spiega_errore(ValueError("x")))
        self.assertIn("inatteso", spiega_errore(RuntimeError("x")))

    def test_failed_item_gets_a_hint(self):
        source = SecuritySource.objects.create(name="Defender", vendor="Microsoft", source_type=SourceType.EMAIL)
        SecurityMailboxMessage.objects.create(source=source, sender=SENDER, subject=SUBJECT, body="CVE-2099-0300\nExposed devices: 1")
        target = "security.parsers.microsoft_defender_vulnerability_notification_email_parser.MicrosoftDefenderVulnerabilityNotificationEmailParser.parse"
        with mock.patch(target, side_effect=KeyError("affected_product")):
            with self.assertLogs("security.services.parser_engine", level="ERROR"):
                run_pending_parsers()
        message = SecurityMailboxMessage.objects.get()
        self.assertEqual(message.parse_status, ParseStatus.FAILED)
        self.assertIn("affected_product", message.raw_payload["parser_error_hint"])
        row = next(row for row in parser_overview()["parser_rows"] if row["name"] == "microsoft_defender_vulnerability_notification_email_parser")
        self.assertIn("formato", row["last_hint"])


class ParserTestPageTests(TestCase):
    def test_dry_run_explains_why_and_what(self):
        result = test_parsers(sender=SENDER, subject=SUBJECT, body="CVE-2099-0400\nSeverity: Critical\nCVSS score: 9.8\nAffected product: Edge")
        defender = next(c for c in result["candidates"] if c["name"].startswith("microsoft_defender"))
        self.assertTrue(defender["why"])
        lettura = result["parsed"]["lettura"]
        self.assertEqual(lettura["qualita"], QUALITA_DA_VERIFICARE)
        self.assertIn("Dispositivi esposti", [row["campo"] for row in lettura["campi_mancanti"]])

    def test_overview_flags_parsers_reading_badly(self):
        source = SecuritySource.objects.create(name="Defender", vendor="Microsoft", source_type=SourceType.EMAIL)
        SecurityMailboxMessage.objects.create(source=source, sender=SENDER, subject=SUBJECT, body="CVE-2099-0401\nSeverity: High\nAffected product: Edge")
        run_pending_parsers()
        row = next(row for row in parser_overview()["parser_rows"] if row["name"].startswith("microsoft_defender"))
        self.assertEqual(row["status"], "to_check")
        self.assertEqual(row["to_check"], 1)


class ParserPageRenderTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        self.client.force_login(get_user_model().objects.create(username="soc_lettura_admin", is_staff=True, is_superuser=True))
        self.url = reverse("security:admin_config_parsers")

    def test_dry_run_page_shows_reading_and_reasons(self):
        response = self.client.post(self.url, {
            "action": "test", "sender": SENDER, "subject": SUBJECT,
            "body": "CVE-2099-0500\nSeverity: Critical\nCVSS score: 9.8\nAffected product: Edge",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cosa ha letto")
        self.assertContains(response, "Da verificare")
        self.assertContains(response, "Dispositivi esposti")
        self.assertContains(response, "Mittente attendibile")