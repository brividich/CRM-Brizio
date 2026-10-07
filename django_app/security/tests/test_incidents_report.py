"""Registro incidenti NIS2/GDPR, report periodico PDF, motore parser transazionale e cancello di lettura."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    ParseStatus,
    SecurityAlert,
    SecurityIncident,
    SecurityIncidentLog,
    SecurityRemediationTicket,
    SecurityReport,
    SecurityReportMetric,
    SecuritySource,
    SecuritySourceFile,
    Severity,
    SourceType,
    Status,
)
from security.parsers.base import BaseParser, ParsedRecord, ParsedReport
from security.services import incidents as svc
from security.services.periodic_report import build_report, resolve_period


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_inc_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Firewall sintetico", vendor="Demo", source_type=SourceType.EMAIL)

    def _incident(self, hours_ago=0, **fields):
        fields.setdefault("title", "Ransomware sintetico su file server")
        return svc.create_incident(self.user, detected_at=timezone.now() - timedelta(hours=hours_ago), **fields)


class IncidentDeadlineTests(_Base):
    def test_not_significant_has_no_deadlines(self):
        incident = self._incident()
        self.assertEqual(svc.deadlines(incident), [])
        self.assertIsNone(svc.next_open_deadline(incident))

    def test_significant_incident_gets_nis2_deadlines(self):
        incident = self._incident(hours_ago=30, is_significant=True)
        states = {d["key"]: d["state"] for d in svc.deadlines(incident)}
        self.assertEqual(states, {"early_warning": "overdue", "notification": "pending", "final_report": "pending"})
        self.assertEqual(svc.next_open_deadline(incident)["key"], "early_warning")
        self.assertIsNotNone(incident.significance_assessed_at)

    def test_personal_data_adds_gdpr_deadline_due_soon(self):
        incident = self._incident(hours_ago=65, personal_data_breach=True)
        (gdpr,) = svc.deadlines(incident)
        self.assertEqual((gdpr["key"], gdpr["state"]), ("gdpr", "due_soon"))

    def test_milestone_in_time_and_late(self):
        incident = self._incident(hours_ago=50, is_significant=True)
        svc.record_milestone(incident, "early_warning", self.user, when=incident.detected_at + timedelta(hours=30), reference="CSIRT-TEST-1")
        svc.record_milestone(incident, "notification", self.user, when=incident.detected_at + timedelta(hours=40))
        states = {d["key"]: d["state"] for d in svc.deadlines(incident)}
        self.assertEqual(states["early_warning"], "late")
        self.assertEqual(states["notification"], "done")
        incident.refresh_from_db()
        self.assertEqual(incident.csirt_reference, "CSIRT-TEST-1")
        # La relazione finale si conta dalla notifica effettiva.
        final = next(d for d in svc.deadlines(incident) if d["key"] == "final_report")
        self.assertEqual(final["due_at"], incident.notification_at + timedelta(days=30))

    def test_urgent_incidents_lists_overdue_only_when_due(self):
        overdue = self._incident(hours_ago=30, is_significant=True)
        self._incident(hours_ago=1, is_significant=True)
        self.assertEqual([row["incident"].pk for row in svc.urgent_incidents()], [overdue.pk])

    def test_code_and_log(self):
        incident = self._incident()
        self.assertRegex(incident.code, r"^INC-\d{4}-\d{4}$")
        self.assertTrue(SecurityIncidentLog.objects.filter(incident=incident, action="created").exists())

    def test_create_from_case_inherits_alerts(self):
        alert = SecurityAlert.objects.create(source=self.source, title="Cifratura massiva", severity=Severity.CRITICAL, status=Status.OPEN, dedup_hash="x1")
        case = SecurityRemediationTicket.objects.create(source=self.source, alert=alert, title="Caso sintetico", severity=Severity.CRITICAL, dedup_hash="c1")
        incident = svc.create_from_case(case, self.user)
        self.assertEqual(incident.severity, Severity.CRITICAL)
        self.assertEqual(list(incident.alerts.all()), [alert])
        self.assertEqual(list(incident.tickets.all()), [case])


class IncidentViewTests(_Base):
    def test_create_edit_milestone_and_pdf(self):
        now = timezone.localtime()
        response = self.client.post(reverse("security:incident_create"), {
            "title": "Phishing con credenziali sottratte",
            "category": "phishing",
            "severity": Severity.HIGH,
            "status": SecurityIncident.STATUS_OPEN,
            "detected_at": now.strftime("%Y-%m-%dT%H:%M"),
            "significance_criteria": ["service_disruption"],
            "is_significant": "on",
        })
        incident = SecurityIncident.objects.get()
        self.assertRedirects(response, reverse("security:incident_detail", args=[incident.pk]))
        self.assertEqual(incident.significance_criteria, ["service_disruption"])

        page = self.client.get(reverse("security:incident_detail", args=[incident.pk]))
        self.assertContains(page, "Pre-notifica CSIRT (24 h)")
        self.assertNotContains(page, "{#")

        form = self.client.get(reverse("security:incident_edit", args=[incident.pk]))
        self.assertContains(form, now.strftime("%Y-%m-%dT%H:%M"))  # la data resta valorizzata in modifica

        self.client.post(reverse("security:incident_edit", args=[incident.pk]), {
            "title": incident.title, "category": "phishing", "severity": Severity.CRITICAL,
            "status": SecurityIncident.STATUS_CONTAINED, "detected_at": now.strftime("%Y-%m-%dT%H:%M"),
            "significance_criteria": ["service_disruption"], "is_significant": "on",
        })
        log = SecurityIncidentLog.objects.filter(incident=incident, action="updated").get()
        self.assertIn("Gravità", log.body)
        self.assertIn("Stato", log.body)

        self.client.post(reverse("security:incident_milestone", args=[incident.pk, "early_warning"]),
                         {"sent_at": now.strftime("%Y-%m-%dT%H:%M"), "reference": "PROT-1"})
        incident.refresh_from_db()
        self.assertIsNotNone(incident.early_warning_at)

        future = (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("security:incident_milestone", args=[incident.pk, "notification"]), {"sent_at": future})
        incident.refresh_from_db()
        self.assertIsNone(incident.notification_at)

        pdf = self.client.get(reverse("security:incident_pdf", args=[incident.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        register = self.client.get(reverse("security:incidents_register_pdf"))
        self.assertTrue(register.content.startswith(b"%PDF"))

    def test_list_and_case_button(self):
        self._incident(hours_ago=30, is_significant=True)
        page = self.client.get(reverse("security:incidents"))
        self.assertContains(page, "Notifiche da inviare")
        case = SecurityRemediationTicket.objects.create(source=self.source, title="Caso", dedup_hash="c2")
        detail = self.client.get(reverse("security:case_detail", args=[case.pk]))
        self.assertContains(detail, reverse("security:incident_from_case", args=[case.pk]))
        response = self.client.post(reverse("security:incident_from_case", args=[case.pk]))
        incident = case.incidents.get()
        self.assertRedirects(response, reverse("security:incident_edit", args=[incident.pk]))
        # Secondo clic: nessun duplicato.
        self.client.post(reverse("security:incident_from_case", args=[case.pk]))
        self.assertEqual(case.incidents.count(), 1)

    def test_dashboard_shows_overdue_notification(self):
        incident = self._incident(hours_ago=30, is_significant=True)
        page = self.client.get(reverse("security:dashboard"))
        self.assertContains(page, f"{incident.code}: Pre-notifica CSIRT (24 h) scaduta")


class PeriodicReportTests(_Base):
    def test_resolve_period(self):
        start, end, _ = resolve_period("last_week", today=date(2026, 10, 7))  # mercoledì
        self.assertEqual((start, end), (date(2026, 9, 28), date(2026, 10, 4)))
        start, end, label = resolve_period("last_month", today=date(2026, 3, 15))
        self.assertEqual((start, end, label), (date(2026, 2, 1), date(2026, 2, 28), "febbraio 2026"))
        start, end, _ = resolve_period("custom", date(2026, 5, 10), date(2026, 5, 1))
        self.assertEqual((start, end), (date(2026, 5, 1), date(2026, 5, 10)))

    def test_report_counts_and_pdf(self):
        today = timezone.localdate()
        SecurityAlert.objects.create(source=self.source, title="Login anomalo", severity=Severity.HIGH, status=Status.OPEN, dedup_hash="r1")
        BackupJobRecord.objects.create(source=self.source, job_name="NAS notturno", status="failed", completed_at=timezone.now(), dedup_hash="b1")
        BackupJobRecord.objects.create(source=self.source, job_name="NAS notturno", status="completed", completed_at=timezone.now(), dedup_hash="b2")
        self._incident(is_significant=True)
        report = build_report(today - timedelta(days=6), today)
        self.assertEqual(report["alerts"]["created"], 1)
        self.assertEqual(report["backup"]["success_rate"], 50.0)
        self.assertEqual(report["incidents"]["significant"], 1)

        page = self.client.get(reverse("security:report") + "?period=last_30")
        self.assertContains(page, "Backup riusciti")
        pdf = self.client.get(reverse("security:report_pdf") + "?period=last_30")
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))


class _FakeParser(BaseParser):
    name = "fake_atomic_parser"

    def can_parse(self, item):
        return True

    def parse(self, item):
        return ParsedReport(
            report_type="fake", title="Fake", parser_name=self.name,
            records=[ParsedRecord(record_type="fake_event", payload={"n": 1})],
            metrics={"fake_metric": 3},
            payload={"dedup_key": "fake-dedup-1"},
        )


class ParserEngineAtomicTests(_Base):
    def _item(self):
        return SecuritySourceFile.objects.create(source=self.source, original_name="r.txt", file_type="manual", content="x")

    def test_failure_mid_report_leaves_nothing_behind(self):
        from security.services import parser_engine

        item = self._item()
        with patch.object(parser_engine, "_match_enabled_parser", return_value=_FakeParser()), \
                patch.object(parser_engine, "_persist_record", side_effect=RuntimeError("boom")):
            parser_engine.run_pending_parsers()
        item.refresh_from_db()
        self.assertEqual(item.parse_status, ParseStatus.FAILED)
        self.assertFalse(SecurityReport.objects.exists())
        self.assertFalse(SecurityReportMetric.objects.exists())

        # Rielaborato dopo la correzione: il report si salva per intero (nessun falso «già letto»).
        item.parse_status = ParseStatus.PENDING
        item.save(update_fields=["parse_status"])
        with patch.object(parser_engine, "_match_enabled_parser", return_value=_FakeParser()):
            parser_engine.run_pending_parsers()
        item.refresh_from_db()
        self.assertEqual(item.parse_status, ParseStatus.PARSED)
        self.assertEqual(SecurityReport.objects.count(), 1)
        self.assertEqual(item.raw_payload["parse_outcome"], "stored")
        self.assertNotIn("parser_error", item.raw_payload)
        self.assertIn("parse_ms", item.raw_payload)


class ViewGuardTests(TestCase):
    def test_ticket_and_alert_pages_need_soc_read_permission(self):
        user = get_user_model().objects.create(username="no_soc_user", is_active=True)
        self.client.force_login(user)
        with patch("security.permissions.can_view_security_center", return_value=False), \
                patch("security.views_incidents.can_view_security_center", return_value=False), \
                patch("security.views_report.can_view_security_center", return_value=False), \
                patch("core.middleware.ACLMiddleware.__call__", lambda self, request: self.get_response(request), create=True):
            for name in ("security:tickets_list", "security:alerts_list", "security:incidents", "security:report"):
                response = self.client.get(reverse(name))
                self.assertIn(response.status_code, (302, 403), name)
                self.assertNotEqual(response.status_code, 200, name)
