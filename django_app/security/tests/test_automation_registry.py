"""Registro delle regole di rientro: regole storiche invariate, nuove regole spente, simulazione."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityEventRecord,
    SecuritySource,
    SecurityVpnAccess,
    Severity,
    SourceType,
    Status,
)
from security.services import auto_resolution
from security.services.configuration import set_setting


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_auto_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Firebox sintetico", vendor="WatchGuard", source_type=SourceType.EMAIL)
        self._n = 0

    def _event(self, event_type, payload, occurred_at=None, dedup=None):
        self._n += 1
        return SecurityEventRecord.objects.create(
            source=self.source, event_type=event_type, occurred_at=occurred_at or timezone.now(),
            fingerprint=f"fp-{self._n}", dedup_hash=dedup or f"dh-{self._n}", payload=payload, decision_trace={"decision": "alert"},
        )

    def _alert(self, event, created_at=None):
        alert = SecurityAlert.objects.create(source=self.source, event=event, title=f"Alert {event.pk}", severity=Severity.WARNING,
                                             status=Status.NEW, dedup_hash=event.dedup_hash)
        if created_at:
            SecurityAlert.objects.filter(pk=alert.pk).update(created_at=created_at)
            alert.refresh_from_db()
        return alert


class RegistryTests(_Base):
    def test_registry_lists_existing_and_new_rules(self):
        self.assertEqual(set(auto_resolution.REGISTRY), {"backup_job", "vulnerability_finding", "source_silent", "vpn_within_limits", "cve_patched_inventory"})
        self.assertTrue(auto_resolution.rule_enabled("backup_job"))
        self.assertFalse(auto_resolution.rule_enabled("vpn_within_limits"))
        self.assertFalse(auto_resolution.rule_enabled("cve_patched_inventory"))

    def test_existing_rule_writes_rule_code_and_evidence(self):
        failure = self._event("backup_job", {"job_name": "JOB-DEMO", "device_name": "PC-DEMO", "status": "failed"},
                              occurred_at=timezone.now() - timedelta(hours=3))
        alert = self._alert(failure)
        success = self._event("backup_job", {"job_name": "JOB-DEMO", "device_name": "PC-DEMO", "status": "completed"})
        self.assertEqual(auto_resolution.resolve_backup_recovered(success), 1)
        log = SecurityAlertActionLog.objects.get(alert=alert, action="auto_resolved")
        self.assertEqual(log.details["rule"], "backup_job")
        self.assertEqual(log.details["evidence_event_id"], success.pk)

    def test_per_rule_switch_off_keeps_alert_open(self):
        failure = self._event("backup_job", {"job_name": "J", "device_name": "D", "status": "failed"}, occurred_at=timezone.now() - timedelta(hours=1))
        alert = self._alert(failure)
        set_setting("autoresolve.backup_job.attivo", False)
        success = self._event("backup_job", {"job_name": "J", "device_name": "D", "status": "completed"})
        self.assertEqual(auto_resolution.resolve_backup_recovered(success), 0)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.NEW)

    def test_new_rule_cannot_be_enabled_without_simulation(self):
        with self.assertRaises(ValueError):
            auto_resolution.set_rule_enabled("vpn_within_limits", True)
        auto_resolution.simulate("vpn_within_limits")
        auto_resolution.set_rule_enabled("vpn_within_limits", True)
        self.assertTrue(auto_resolution.rule_enabled("vpn_within_limits"))


class SimulationTests(_Base):
    def test_backup_simulation_is_read_only_and_counts(self):
        failure = self._event("backup_job", {"job_name": "J", "device_name": "D", "status": "failed"}, occurred_at=timezone.now() - timedelta(days=3))
        alert = self._alert(failure, created_at=timezone.now() - timedelta(days=3))
        self._event("backup_job", {"job_name": "J", "device_name": "D", "status": "completed"}, occurred_at=timezone.now() - timedelta(days=2))
        result = auto_resolution.simulate("backup_job")
        self.assertEqual(result["would_close"], 1)
        self.assertEqual(result["examples"][0]["alert_id"], alert.pk)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.NEW)  # la simulazione non chiude nulla
        self.assertIsNotNone(auto_resolution.last_simulation("backup_job"))

    def test_simulation_ignores_success_after_alert_was_closed(self):
        failure = self._event("backup_job", {"job_name": "J", "device_name": "D", "status": "failed"}, occurred_at=timezone.now() - timedelta(days=5))
        alert = self._alert(failure, created_at=timezone.now() - timedelta(days=5))
        SecurityAlert.objects.filter(pk=alert.pk).update(status=Status.CLOSED, closed_at=timezone.now() - timedelta(days=4))
        self._event("backup_job", {"job_name": "J", "device_name": "D", "status": "completed"}, occurred_at=timezone.now() - timedelta(days=2))
        self.assertEqual(auto_resolution.simulate("backup_job")["would_close"], 0)


class VpnRuleTests(_Base):
    def _vpn_alert(self, days_ago=10, user="utente.demo"):
        event = self._event("watchguard_alert_candidate", {"type": "watchguard_vpn_repeated_denied", "user": user, "count": 30},
                            occurred_at=timezone.now() - timedelta(days=days_ago))
        return self._alert(event, created_at=timezone.now() - timedelta(days=days_ago))

    def _access(self, day, user, action=SecurityVpnAccess.ACTION_ALLOWED, n=1):
        for i in range(n):
            login = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time())) + timedelta(hours=9, minutes=i)
            SecurityVpnAccess.objects.create(source=self.source, action=action, username=user, login_at=login,
                                             duration_seconds=3600, dedup_hash=f"{user}-{day}-{action}-{i}")

    def _enable(self):
        auto_resolution.simulate("vpn_within_limits")
        auto_resolution.set_rule_enabled("vpn_within_limits", True)

    def test_closes_after_n_days_within_limits_with_data(self):
        alert = self._vpn_alert()
        today = timezone.localdate()
        for offset in range(1, 8):
            self._access(today - timedelta(days=offset), "utente.demo", SecurityVpnAccess.ACTION_DENIED, n=2)
        self._enable()
        self.assertEqual(auto_resolution.run_vpn_within_limits(today), 1)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)
        self.assertIn("7 giorni consecutivi", alert.status_reason)

    def test_silence_is_not_recovery(self):
        alert = self._vpn_alert()
        today = timezone.localdate()
        for offset in range(1, 8):
            if offset != 4:  # un giorno senza dati VPN
                self._access(today - timedelta(days=offset), "altro.utente")
        self._enable()
        self.assertEqual(auto_resolution.run_vpn_within_limits(today), 0)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.NEW)

    def test_still_above_threshold_stays_open(self):
        self._vpn_alert()
        today = timezone.localdate()
        for offset in range(1, 8):
            self._access(today - timedelta(days=offset), "utente.demo", SecurityVpnAccess.ACTION_DENIED, n=12 if offset == 2 else 1)
        self._enable()
        self.assertEqual(auto_resolution.run_vpn_within_limits(today), 0)

    def test_disabled_by_default_does_nothing(self):
        self._vpn_alert()
        today = timezone.localdate()
        for offset in range(1, 8):
            self._access(today - timedelta(days=offset), "utente.demo")
        self.assertEqual(auto_resolution.run_vpn_within_limits(today), 0)


class AutomationViewTests(_Base):
    def test_page_simulate_and_toggle(self):
        response = self.client.get(reverse("security:automation"))
        self.assertContains(response, "VPN tornata nei limiti")
        response = self.client.post(reverse("security:automation_toggle", args=["vpn_within_limits"]), {"enabled": "1"}, follow=True)
        self.assertContains(response, "esegui la simulazione")
        self.client.post(reverse("security:automation_simulate", args=["vpn_within_limits"]))
        response = self.client.get(reverse("security:automation"))
        self.assertContains(response, "Simulazione: vpn_within_limits")
        self.client.post(reverse("security:automation_toggle", args=["vpn_within_limits"]), {"enabled": "1", "giorni": "5"})
        self.assertTrue(auto_resolution.rule_enabled("vpn_within_limits"))
        self.assertEqual(auto_resolution.vpn_days(), 5)

    def test_unknown_rule_404(self):
        self.assertEqual(self.client.post(reverse("security:automation_simulate", args=["nope"])).status_code, 404)
