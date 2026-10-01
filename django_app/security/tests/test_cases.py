"""Ticket gestibili (casi), azioni massive sugli alert e chiusura automatica degli alert rientrati."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityEventRecord,
    SecurityMailboxSource,
    SecurityRemediationTicket,
    SecurityReport,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services.auto_resolution import resolve_backup_recovered, resolve_vulnerability_cleared
from security.services.cases import (
    CaseConflict,
    add_task,
    case_timeline,
    open_case_from_alerts,
    set_case_status,
)
from security.services.configuration import set_setting
from security.services.rule_engine import evaluate_security_rules
from security.services.source_heartbeat import evaluate_source_heartbeat


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_case_user", is_staff=True, is_superuser=True)
        self.other = get_user_model().objects.create(username="soc_case_other", is_active=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Backup NAS", vendor="Synology", source_type=SourceType.EMAIL)
        self._n = 0

    def _event(self, event_type, payload, occurred_at=None, dedup=None):
        self._n += 1
        return SecurityEventRecord.objects.create(
            source=self.source, event_type=event_type, occurred_at=occurred_at or timezone.now(),
            fingerprint=f"fp-{self._n}", dedup_hash=dedup or f"dh-{self._n}", payload=payload,
        )

    def _alert(self, event=None, status=Status.NEW, severity=Severity.WARNING, title=None):
        self._n += 1
        return SecurityAlert.objects.create(
            source=self.source, event=event, title=title or f"Alert {self._n}", severity=severity,
            status=status, dedup_hash=event.dedup_hash if event else f"a-{self._n}",
        )


class CaseServiceTests(_Base):
    def test_open_case_links_alerts_and_takes_them_in_charge(self):
        a1, a2 = self._alert(severity=Severity.WARNING), self._alert(severity=Severity.CRITICAL)
        case = open_case_from_alerts([a1, a2], user=self.user, title="Indagine", assignee=self.user)

        self.assertEqual(case.origin, SecurityRemediationTicket.ORIGIN_MANUAL)
        self.assertEqual(case.status, Status.IN_PROGRESS)
        self.assertEqual(case.severity, Severity.CRITICAL)  # la peggiore tra gli alert
        self.assertEqual(set(case.linked_alerts.values_list("pk", flat=True)), {a1.pk, a2.pk})
        a1.refresh_from_db()
        self.assertEqual(a1.status, Status.ACKNOWLEDGED)

    def test_two_manual_cases_on_same_source_do_not_collide(self):
        """L'indice "un solo ticket attivo per (sorgente, dedup)" non deve bloccare i casi a mano."""
        open_case_from_alerts([self._alert()], user=self.user)
        open_case_from_alerts([self._alert()], user=self.user)
        self.assertEqual(SecurityRemediationTicket.objects.count(), 2)

    def test_closing_case_can_close_its_alerts(self):
        alert = self._alert()
        case = open_case_from_alerts([alert], user=self.user)
        set_case_status(case, Status.RESOLVED, user=self.user, reason="Patch installata", close_alerts=True)

        alert.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(alert.status, Status.CLOSED)
        self.assertIsNotNone(case.closed_at)
        self.assertEqual(case.resolution, "Patch installata")

    def test_reopen_conflicting_auto_ticket_is_refused(self):
        old = SecurityRemediationTicket.objects.create(source=self.source, title="Vecchio", dedup_hash="same", status=Status.RESOLVED)
        SecurityRemediationTicket.objects.create(source=self.source, title="Nuovo", dedup_hash="same", status=Status.OPEN)
        with self.assertRaises(CaseConflict):
            set_case_status(old, Status.IN_PROGRESS, user=self.user)
        old.refresh_from_db()
        self.assertEqual(old.status, Status.RESOLVED)

    def test_timeline_merges_case_alert_logs_and_notes(self):
        alert = self._alert()
        case = open_case_from_alerts([alert], user=self.user)
        add_task(case, "Aggiornare Chrome", user=self.user)
        case.notes.create(author=self.user, body="Contattato il fornitore")
        actions = [entry["action"] for entry in case_timeline(case)]
        self.assertIn("case_opened", actions)
        self.assertIn("acknowledge", actions)  # azione sull'alert collegato
        self.assertIn("case_task_added", actions)
        self.assertIn("note", actions)


class CaseViewTests(_Base):
    def _case(self):
        return open_case_from_alerts([self._alert()], user=self.user)

    def test_detail_renders(self):
        case = self._case()
        response = self.client.get(reverse("security:case_detail", args=[case.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, case.title)

    def test_list_defaults_to_active_and_links_detail(self):
        case = self._case()
        SecurityRemediationTicket.objects.create(source=self.source, title="Chiuso", dedup_hash="x", status=Status.CLOSED)
        response = self.client.get(reverse("security:tickets_list"))
        self.assertEqual(response.context["total"], 1)
        self.assertContains(response, reverse("security:case_detail", args=[case.pk]))

    def test_list_filters_assigned_to_me(self):
        mine = self._case()
        self.client.post(reverse("security:case_assign", args=[mine.pk]), {"assignee": "me"})
        self._case()
        response = self.client.get(reverse("security:tickets_list"), {"assignee": "me"})
        self.assertEqual(response.context["total"], 1)

    def test_assign_take_and_assign_other(self):
        case = self._case()
        self.client.post(reverse("security:case_assign", args=[case.pk]), {"assignee": "me"})
        case.refresh_from_db()
        self.assertEqual(case.assignee, self.user)
        self.client.post(reverse("security:case_assign", args=[case.pk]), {"assignee": str(self.other.pk)})
        case.refresh_from_db()
        self.assertEqual(case.assignee, self.other)

    def test_close_requires_reason(self):
        case = self._case()
        self.client.post(reverse("security:case_status", args=[case.pk]), {"status": Status.CLOSED})
        case.refresh_from_db()
        self.assertNotEqual(case.status, Status.CLOSED)
        self.client.post(reverse("security:case_status", args=[case.pk]), {"status": Status.CLOSED, "reason": "Fatto"})
        case.refresh_from_db()
        self.assertEqual(case.status, Status.CLOSED)

    def test_tasks_and_notes(self):
        case = self._case()
        self.client.post(reverse("security:case_task_add", args=[case.pk]), {"title": "Verifica log"})
        task = case.tasks.get()
        self.client.post(reverse("security:case_task_toggle", args=[case.pk, task.pk]))
        task.refresh_from_db()
        self.assertTrue(task.done)
        self.assertEqual(task.done_by, self.user)
        self.client.post(reverse("security:case_note", args=[case.pk]), {"body": "Nota"})
        self.assertEqual(case.notes.count(), 1)
        self.client.post(reverse("security:case_task_delete", args=[case.pk, task.pk]))
        self.assertFalse(case.tasks.exists())

    def test_task_of_another_case_is_404(self):
        case, other = self._case(), self._case()
        add_task(other, "Altro", user=self.user)
        task = other.tasks.get()
        response = self.client.post(reverse("security:case_task_toggle", args=[case.pk, task.pk]))
        self.assertEqual(response.status_code, 404)

    def test_create_from_alert_detail(self):
        alert = self._alert()
        response = self.client.post(reverse("security:case_create"), {"alert_ids": [alert.pk], "title": "Da alert", "assign_to_me": "1"})
        case = SecurityRemediationTicket.objects.get(title="Da alert")
        self.assertRedirects(response, reverse("security:case_detail", args=[case.pk]))
        self.assertEqual(case.assignee, self.user)
        detail = self.client.get(reverse("security:alert_detail", args=[alert.pk]))
        self.assertContains(detail, reverse("security:case_detail", args=[case.pk]))


class BulkAlertTests(_Base):
    def test_bulk_acknowledge_skips_incompatible(self):
        new, closed = self._alert(), self._alert(status=Status.CLOSED)
        self.client.post(reverse("security:alerts_bulk"), {"alert_ids": [new.pk, closed.pk], "action": "acknowledge"})
        new.refresh_from_db()
        closed.refresh_from_db()
        self.assertEqual(new.status, Status.ACKNOWLEDGED)
        self.assertEqual(closed.status, Status.CLOSED)

    def test_bulk_close(self):
        alerts = [self._alert(), self._alert(status=Status.ACKNOWLEDGED)]
        self.client.post(reverse("security:alerts_bulk"), {"alert_ids": [a.pk for a in alerts], "action": "close", "reason": "Rumore"})
        self.assertEqual(SecurityAlert.objects.filter(status=Status.CLOSED).count(), 2)

    def test_bulk_open_case_and_add_to_case(self):
        a1, a2, a3 = self._alert(), self._alert(), self._alert()
        self.client.post(reverse("security:alerts_bulk"), {"alert_ids": [a1.pk, a2.pk], "action": "open_case", "title": "Gruppo"})
        case = SecurityRemediationTicket.objects.get(title="Gruppo")
        self.assertEqual(case.linked_alerts.count(), 2)
        self.client.post(reverse("security:alerts_bulk"), {"alert_ids": [a3.pk, a1.pk], "action": "add_to_case", "case_id": case.pk})
        self.assertEqual(case.linked_alerts.count(), 3)

    def test_next_never_redirects_off_site(self):
        alert = self._alert()
        response = self.client.post(reverse("security:alerts_bulk"), {"alert_ids": [alert.pk], "action": "acknowledge", "next": "https://evil.example/x"})
        self.assertEqual(response["Location"], reverse("security:alerts_list"))

    def test_list_renders_bulk_controls(self):
        self._alert()
        response = self.client.get(reverse("security:alerts_list"))
        self.assertContains(response, 'name="alert_ids"')
        self.assertContains(response, reverse("security:alerts_bulk"))


class AutoResolutionTests(_Base):
    def _backup_failure(self, job="Server01", device="NAS1", hours_ago=10):
        event = self._event("backup_job", {"job_name": job, "device_name": device, "status": "failed"},
                            occurred_at=timezone.now() - timedelta(hours=hours_ago))
        return self._alert(event=event)

    def test_later_successful_backup_resolves_failure_alert(self):
        alert = self._backup_failure()
        success = self._event("backup_job", {"job_name": "Server01", "device_name": "NAS1", "status": "completed"},
                              occurred_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(resolve_backup_recovered(success), 1)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)
        self.assertIn("completato", alert.status_reason)
        log = SecurityAlertActionLog.objects.get(alert=alert, action="auto_resolved")
        self.assertEqual(log.details["evidence_event_id"], success.pk)

    def test_older_success_does_not_resolve(self):
        """Report fuori ordine: un successo PRECEDENTE al fallimento non prova il rientro."""
        alert = self._backup_failure(hours_ago=2)
        old_success = self._event("backup_job", {"job_name": "Server01", "device_name": "NAS1", "status": "completed"},
                                  occurred_at=timezone.now() - timedelta(hours=20))
        self.assertEqual(resolve_backup_recovered(old_success), 0)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.NEW)

    def test_other_job_or_device_does_not_resolve(self):
        alert = self._backup_failure()
        for payload in ({"job_name": "Altro", "device_name": "NAS1"}, {"job_name": "Server01", "device_name": "NAS2"}):
            self.assertEqual(resolve_backup_recovered(self._event("backup_job", {**payload, "status": "completed"})), 0)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.NEW)

    def test_rule_engine_resolves_through_completed_backup(self):
        alert = self._backup_failure()
        SecurityEventRecord.objects.filter(pk=alert.event_id).update(decision_trace={"decision": "alert"})
        self._event("backup_job", {"job_name": "Server01", "device_name": "NAS1", "status": "completed"})
        evaluate_security_rules()
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)

    def test_disabled_setting_keeps_alert_open(self):
        set_setting("SECURITY_AUTO_RESOLVE_ENABLED", False, category="general")
        alert = self._backup_failure()
        success = self._event("backup_job", {"job_name": "Server01", "device_name": "NAS1", "status": "completed"})
        self.assertEqual(resolve_backup_recovered(success), 0)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.NEW)

    def test_vulnerability_with_zero_exposed_resolves(self):
        exposed = self._event("vulnerability_finding", {"cve": "CVE-2026-0001", "affected_product": "Chrome", "exposed_devices": 4},
                              occurred_at=timezone.now() - timedelta(days=1), dedup="vuln-1")
        alert = self._alert(event=exposed)
        cleared = self._event("vulnerability_finding", {"cve": "CVE-2026-0001", "affected_product": "Chrome", "exposed_devices": 0}, dedup="vuln-1")
        self.assertEqual(resolve_vulnerability_cleared(cleared), 1)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)

    def test_vulnerability_still_exposed_stays_open(self):
        exposed = self._event("vulnerability_finding", {"cve": "CVE-2026-0002", "exposed_devices": 4},
                              occurred_at=timezone.now() - timedelta(days=1), dedup="vuln-2")
        alert = self._alert(event=exposed)
        again = self._event("vulnerability_finding", {"cve": "CVE-2026-0002", "exposed_devices": 2}, dedup="vuln-2")
        self.assertEqual(resolve_vulnerability_cleared(again), 0)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.NEW)

    def test_source_back_online_resolves_silence_alert(self):
        mailbox = SecurityMailboxSource.objects.create(
            name=self.source.name, code="nas", source_type="manual", expected_every_hours=24, last_run_at=timezone.now(),
        )
        silent = self._event("source_silent", {"source_code": "nas"}, occurred_at=timezone.now() - timedelta(days=2))
        alert = self._alert(event=silent)
        SecurityReport.objects.create(source=self.source, title="Report", report_type="backup")
        evaluate_source_heartbeat()
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)
        self.assertTrue(mailbox.enabled)

    def test_case_closes_when_all_alerts_recover(self):
        alert = self._backup_failure()
        case = open_case_from_alerts([alert], user=self.user)
        resolve_backup_recovered(self._event("backup_job", {"job_name": "Server01", "device_name": "NAS1", "status": "completed"}))
        case.refresh_from_db()
        self.assertEqual(case.status, Status.RESOLVED)
        self.assertTrue(SecurityAlertActionLog.objects.filter(ticket=case, action="case_auto_resolved").exists())

    def test_case_with_open_tasks_stays_open(self):
        alert = self._backup_failure()
        case = open_case_from_alerts([alert], user=self.user)
        add_task(case, "Verificare spazio su disco", user=self.user)
        resolve_backup_recovered(self._event("backup_job", {"job_name": "Server01", "device_name": "NAS1", "status": "completed"}))
        case.refresh_from_db()
        self.assertEqual(case.status, Status.IN_PROGRESS)
        self.assertTrue(SecurityAlertActionLog.objects.filter(ticket=case, action="case_alerts_all_resolved").exists())

    def test_case_stays_open_while_another_alert_is_active(self):
        failing = self._backup_failure()
        other = self._alert()
        case = open_case_from_alerts([failing, other], user=self.user)
        resolve_backup_recovered(self._event("backup_job", {"job_name": "Server01", "device_name": "NAS1", "status": "completed"}))
        case.refresh_from_db()
        self.assertIn(case.status, [Status.OPEN, Status.IN_PROGRESS])
