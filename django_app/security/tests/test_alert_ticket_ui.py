"""Coda alert, dettaglio alert e ticket: conteggi reali, decisione leggibile, filtri."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from security.models import (
    SecurityAlert,
    SecurityEventRecord,
    SecurityRemediationTicket,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.templatetags.security_i18n import action_label, kv_items


class _Base(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(username="soc_ui_admin", is_staff=True, is_superuser=True)
        self.client.force_login(user)
        self.source = SecuritySource.objects.create(name="Demo", vendor="Demo", source_type=SourceType.EMAIL)

    def _alert(self, severity, status=Status.NEW, **extra):
        return SecurityAlert.objects.create(
            source=self.source, title=f"Alert {severity} {status}", severity=severity, status=status,
            dedup_hash=f"{severity}-{status}-{SecurityAlert.objects.count()}", **extra,
        )


class AlertsListTest(_Base):
    def test_severity_chips_show_real_counts(self):
        self._alert(Severity.CRITICAL)
        self._alert(Severity.CRITICAL)
        self._alert(Severity.WARNING)
        response = self.client.get(reverse("security:alerts_list"))
        chips = {c["value"]: c["count"] for c in response.context["severity_chips"]}
        self.assertEqual(chips[Severity.CRITICAL], 2)
        self.assertEqual(chips[Severity.WARNING], 1)
        self.assertEqual(response.context["all_count"], 3)
        self.assertNotContains(response, "<span>severita</span>", html=False)

    def test_counts_ignore_severity_filter_but_list_applies_it(self):
        self._alert(Severity.CRITICAL)
        self._alert(Severity.WARNING)
        response = self.client.get(reverse("security:alerts_list"), {"severity": Severity.CRITICAL})
        self.assertEqual(response.context["total"], 1)
        self.assertEqual(response.context["all_count"], 2)

    def test_active_status_filter(self):
        self._alert(Severity.HIGH)
        self._alert(Severity.HIGH, status=Status.CLOSED)
        response = self.client.get(reverse("security:alerts_list"), {"status": "active"})
        self.assertEqual(response.context["total"], 1)


class AlertDetailTest(_Base):
    def test_decision_trace_rendered_as_key_values(self):
        event = SecurityEventRecord.objects.create(
            source=self.source, event_type="backup_job", fingerprint="f", dedup_hash="d",
            payload={"job_name": "ERP VM Backup", "status": "failed", "raw_body_hash": "abc"},
        )
        alert = self._alert(
            Severity.WARNING, event=event,
            decision_trace={"decision": "alert", "rule": "Backup missing/failed => alert", "backup_status": "failed", "alert_created": True},
        )
        html = self.client.get(reverse("security:alert_detail", args=[alert.pk])).content.decode()
        self.assertIn("Backup missing/failed =&gt; alert", html)
        self.assertIn("Esito backup", html)
        self.assertNotIn("{&#x27;", html)  # niente dict Python grezzo
        self.assertNotIn("raw_body_hash", html)


class TicketsListTest(_Base):
    def test_filters(self):
        SecurityRemediationTicket.objects.create(source=self.source, title="Aperto", severity=Severity.HIGH, status=Status.OPEN, dedup_hash="t1")
        SecurityRemediationTicket.objects.create(source=self.source, title="Chiuso", severity=Severity.HIGH, status=Status.CLOSED, dedup_hash="t2")
        response = self.client.get(reverse("security:tickets_list"), {"status": "active"})
        self.assertEqual(response.context["total"], 1)
        self.assertContains(response, "Aperto")


class FiltersTest(TestCase):
    def test_kv_items_hides_empty_and_hashes(self):
        rows = dict(kv_items({"cve": "CVE-1", "dedup_hash": "x", "empty": "", "exposed_devices": 3, "flag": True}))
        self.assertEqual(rows["CVE"], "CVE-1")
        self.assertEqual(rows["Dispositivi esposti"], "3")
        self.assertEqual(rows["Flag"], "sì")
        self.assertNotIn("Dedup hash", rows)

    def test_action_label(self):
        self.assertEqual(action_label("alert_created"), "Alert creato")
        self.assertEqual(action_label("something_new"), "Something new")
