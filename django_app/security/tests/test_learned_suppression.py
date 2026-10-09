"""Soppressione appresa: 3 disattivazioni della stessa impronta → dalla 4ª niente alert.

Dati sintetici: job, dispositivi e CVE inventati.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityAlertDismissal,
    SecurityAlertSuppressionRule,
    SecurityConfigurationAuditLog,
    SecurityEventRecord,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services.alert_lifecycle import close_alert, mark_false_positive, mute_alert, reopen_alert
from security.services.configuration import set_setting
from security.services.learned_suppression import alert_fingerprint, dismissal_progress, event_fingerprint
from security.services.rule_engine import evaluate_security_rules


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_learn_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="NAS sintetico", vendor="Synology", source_type=SourceType.EMAIL)
        self._n = 0

    def _event(self, payload=None, event_type="backup_job", severity=Severity.WARNING, when=None):
        self._n += 1
        payload = payload or {"job_name": "JOB-DEMO", "device_name": "PC-DEMO-01", "status": "failed",
                              "start_time": f"2026-01-0{self._n % 9 + 1}T02:00"}
        return SecurityEventRecord.objects.create(
            source=self.source, event_type=event_type, severity=severity, occurred_at=when or timezone.now(),
            fingerprint=f"fp-{self._n}", dedup_hash=f"dh-{self._n}", payload=payload,
        )

    def _alert_from_engine(self, **kwargs):
        event = self._event(**kwargs)
        evaluate_security_rules()
        event.refresh_from_db()
        return event, SecurityAlert.objects.filter(event=event).first()

    def _dismiss(self, n, kind="fp", **kwargs):
        alerts = []
        for _ in range(n):
            _event, alert = self._alert_from_engine(**kwargs)
            if kind == "fp":
                mark_false_positive(alert, actor="analista", reason="Job di test, non è un problema")
            elif kind == "mute":
                mute_alert(alert, actor="analista", reason="Rumore noto")
            else:
                close_alert(alert, actor="analista", reason="Accettato dal responsabile", outcome=kind)
            alerts.append(alert)
        return alerts


class FingerprintTests(_Base):
    def test_fingerprint_ignores_timestamps_and_ids(self):
        a = self._event({"job_name": "JOB-DEMO", "device_name": "PC-DEMO-01", "start_time": "2026-01-01T02:00", "status": "failed"})
        b = self._event({"job_name": "job-demo ", "device_name": "PC-DEMO-01", "start_time": "2026-02-09T03:00", "status": "failed"})
        self.assertEqual(event_fingerprint(a).hash, event_fingerprint(b).hash)
        self.assertEqual(set(event_fingerprint(a).fields), {"job_name", "device_name"})

    def test_different_device_different_fingerprint(self):
        a = self._event({"job_name": "JOB-DEMO", "device_name": "PC-DEMO-01"})
        b = self._event({"job_name": "JOB-DEMO", "device_name": "PC-DEMO-02"})
        self.assertNotEqual(event_fingerprint(a).hash, event_fingerprint(b).hash)

    def test_cve_fingerprint_uses_cve_and_product(self):
        a = self._event({"cve": "CVE-2099-0001", "affected_product": "DemoZip", "exposed_devices": 3}, event_type="vulnerability_finding")
        b = self._event({"cve": "CVE-2099-0001", "affected_product": "DemoZip", "exposed_devices": 7}, event_type="vulnerability_finding")
        self.assertEqual(event_fingerprint(a).hash, event_fingerprint(b).hash)

    def test_event_without_identifying_fields_is_not_learnable(self):
        self.assertIsNone(event_fingerprint(self._event({"count": 4}, event_type="generic_metric")))


class LearningTests(_Base):
    def test_two_dismissals_do_not_create_rule_and_badge_warns(self):
        alerts = self._dismiss(2)
        self.assertFalse(SecurityAlertSuppressionRule.objects.filter(owner="system:learned").exists())
        _event, third = self._alert_from_engine()
        progress = dismissal_progress(third)
        self.assertEqual(progress["count"], 2)
        self.assertTrue(progress["next_creates_rule"])
        response = self.client.get(reverse("security:alert_detail", args=[third.pk]))
        self.assertContains(response, "2/3 disattivazioni: la prossima creerà una soppressione automatica")
        self.assertEqual(len(alerts), 2)

    def test_third_dismissal_creates_exact_learned_rule_with_audit(self):
        alerts = self._dismiss(3)
        rule = SecurityAlertSuppressionRule.objects.get(owner="system:learned")
        self.assertEqual(rule.fingerprint, alert_fingerprint(alerts[0]).hash)
        self.assertEqual(rule.scope_type, "learned_fingerprint")
        self.assertEqual(rule.event_type, "backup_job")
        self.assertEqual(rule.match_payload, {"job_name": "JOB-DEMO", "device_name": "PC-DEMO-01"})
        self.assertEqual(rule.max_severity, Severity.WARNING)
        self.assertIn("analista", rule.reason)
        self.assertEqual(rule.reason.count("alert #"), 3)
        self.assertAlmostEqual((rule.expires_at - timezone.now()).days, 179, delta=1)
        self.assertTrue(SecurityConfigurationAuditLog.objects.filter(model_name="SecurityAlertSuppressionRule", object_id=str(rule.pk), action="create").exists())
        self.assertEqual(rule.dismissals.count(), 3)

    def test_fourth_occurrence_is_suppressed_with_trace(self):
        self._dismiss(3)
        rule = SecurityAlertSuppressionRule.objects.get(owner="system:learned")
        event, alert = self._alert_from_engine()
        self.assertIsNone(alert)
        self.assertTrue(event.suppressed)
        self.assertEqual(event.decision_trace["decision"], "suppressed_kpi_only")
        self.assertEqual(event.decision_trace["rule_id"], rule.pk)
        self.assertTrue(event.decision_trace["learned"])
        rule.refresh_from_db()
        self.assertEqual(rule.hit_count, 1)
        self.assertIsNotNone(rule.last_hit_at)

    def test_other_device_still_alerts(self):
        self._dismiss(3)
        _event, alert = self._alert_from_engine(payload={"job_name": "JOB-DEMO", "device_name": "PC-DEMO-99", "status": "failed"})
        self.assertIsNotNone(alert)

    def test_mixed_dismissal_kinds_count(self):
        self._dismiss(1, kind="fp")
        self._dismiss(1, kind="mute")
        self._dismiss(1, kind="accepted_risk")
        self.assertTrue(SecurityAlertSuppressionRule.objects.filter(owner="system:learned").exists())

    def test_resolved_and_automatic_closures_do_not_count(self):
        for _ in range(3):
            _event, alert = self._alert_from_engine()
            close_alert(alert, actor="analista", reason="Backup rifatto", outcome="resolved")
        for _ in range(3):
            _event, alert = self._alert_from_engine()
            mark_false_positive(alert, actor="system", reason="automatico")
        self.assertEqual(SecurityAlertDismissal.objects.count(), 0)
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_dismissal_without_reason_does_not_count(self):
        for _ in range(3):
            _event, alert = self._alert_from_engine()
            mark_false_positive(alert, actor="analista", reason="")
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_bulk_action_counts_once(self):
        alerts = [self._alert_from_engine()[1] for _ in range(3)]
        # Tre alert attivi con la stessa impronta non possono coesistere solo se dedup diversi: qui lo sono.
        for alert in alerts:
            mark_false_positive(alert, actor="analista", reason="Massivo", batch="bulk-1")
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_dismissals_outside_window_do_not_count(self):
        self._dismiss(2)
        SecurityAlertDismissal.objects.update(created_at=timezone.now() - timedelta(days=200))
        self._dismiss(1)
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_threshold_and_duration_are_configurable(self):
        set_setting("soppressione.appresa.soglia", 2)
        set_setting("soppressione.appresa.durata_giorni", 30)
        self._dismiss(2)
        rule = SecurityAlertSuppressionRule.objects.get(owner="system:learned")
        self.assertLessEqual((rule.expires_at - timezone.now()).days, 30)

    def test_disabled_learning_records_but_does_not_learn(self):
        set_setting("soppressione.appresa.attivo", False)
        self._dismiss(3)
        self.assertEqual(SecurityAlertDismissal.objects.count(), 3)
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())


class GuardrailTests(_Base):
    def test_never_learns_on_critical(self):
        self._dismiss(3, severity=Severity.CRITICAL)
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_never_learns_on_kev_cve(self):
        payload = {"cve": "CVE-2099-0002", "affected_product": "DemoApp", "kev": True, "status": "failed",
                   "job_name": "x"}
        self._dismiss(3, payload=payload)
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_never_learns_on_threats(self):
        payload = {"type": "watchguard_botnet_detected", "computer": "PC-DEMO-01", "title": "Botnet", "status": "failed", "job_name": "x"}
        self._dismiss(3, payload=payload)
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_escalated_severity_still_alerts(self):
        self._dismiss(3)
        _event, alert = self._alert_from_engine(severity=Severity.HIGH)
        self.assertIsNotNone(alert)

    def test_critical_event_never_suppressed_by_learned_rule(self):
        self._dismiss(3)
        rule = SecurityAlertSuppressionRule.objects.get(owner="system:learned")
        rule.max_severity = Severity.CRITICAL  # anche con una regola «larga» sulla severità
        rule.save()
        _event, alert = self._alert_from_engine(severity=Severity.CRITICAL)
        self.assertIsNotNone(alert)

    def test_expired_rule_no_longer_suppresses(self):
        self._dismiss(3)
        SecurityAlertSuppressionRule.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        _event, alert = self._alert_from_engine()
        self.assertIsNotNone(alert)

    def test_manual_reopen_disables_rule_and_resets_count(self):
        alerts = self._dismiss(3)
        reopen_alert(alerts[0], actor="analista", reason="Era un problema vero")
        rule = SecurityAlertSuppressionRule.objects.get(owner="system:learned")
        self.assertFalse(rule.is_active)
        self.assertIn("riaperto", rule.revoked_reason)
        self.assertFalse(SecurityAlertDismissal.objects.filter(counted=True).exists())
        mark_false_positive(alerts[0], actor="analista", reason="di nuovo")
        self.assertEqual(SecurityAlertSuppressionRule.objects.filter(is_active=True).count(), 0)

    def test_promoting_suppressed_event_resets_learning(self):
        from security.services.event_triage import promote_event

        self._dismiss(3)
        event, _alert = self._alert_from_engine()
        self.assertTrue(event.suppressed)
        promote_event(event, user=self.user, severity=Severity.WARNING, reason="Va guardato", learn=False)
        self.assertFalse(SecurityAlertSuppressionRule.objects.get(owner="system:learned").is_active)


class ViewTests(_Base):
    def test_close_as_not_relevant_requires_reason(self):
        _event, alert = self._alert_from_engine()
        url = reverse("security:alert_action", args=[alert.pk, "close"])
        self.client.post(url, {"outcome": "not_relevant", "reason": ""})
        alert.refresh_from_db()
        self.assertNotEqual(alert.status, Status.CLOSED)
        self.client.post(url, {"outcome": "not_relevant", "reason": "Server di laboratorio"})
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.CLOSED)
        self.assertEqual(SecurityAlertDismissal.objects.get().kind, "not_relevant")

    def test_mute_action(self):
        _event, alert = self._alert_from_engine()
        self.client.post(reverse("security:alert_action", args=[alert.pk, "mute"]), {"reason": "Rumore"})
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.MUTED)

    def test_bulk_false_positive_requires_reason(self):
        _event, alert = self._alert_from_engine()
        self.client.post(reverse("security:alerts_bulk"), {"alert_ids": [alert.pk], "action": "false_positive", "reason": ""})
        alert.refresh_from_db()
        self.assertNotEqual(alert.status, Status.FALSE_POSITIVE)

    def test_suppressions_page_filters_and_revoke(self):
        self._dismiss(3)
        rule = SecurityAlertSuppressionRule.objects.get(owner="system:learned")
        SecurityAlertSuppressionRule.objects.create(name="Manuale demo", reason="Test", owner="analista")
        response = self.client.get(reverse("security:suppressions") + "?tipo=apprese")
        self.assertContains(response, rule.name)
        self.assertNotContains(response, "Manuale demo")
        self.client.post(reverse("security:suppression_revoke", args=[rule.pk]), {"reason": ""})
        rule.refresh_from_db()
        self.assertTrue(rule.is_active)
        self.client.post(reverse("security:suppression_revoke", args=[rule.pk]), {"reason": "Non più valida"})
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertIn("Non più valida", rule.revoked_reason)

    def test_revoke_requires_config_permission(self):
        self._dismiss(3)
        rule = SecurityAlertSuppressionRule.objects.get(owner="system:learned")
        viewer = get_user_model().objects.create(username="soc_learn_viewer")
        self.client.force_login(viewer)
        from unittest.mock import patch

        with patch("security.views_suppressions.can_view_security_center", return_value=True), \
                patch("core.middleware.ACLMiddleware.__call__", lambda self, r: self.get_response(r), create=True):
            self.client.post(reverse("security:suppression_revoke", args=[rule.pk]), {"reason": "provo"})
        rule.refresh_from_db()
        self.assertTrue(rule.is_active)

    def test_settings_page_renders_learning_section(self):
        response = self.client.get(reverse("security:soc_settings"))
        self.assertContains(response, "Soppressione appresa")
        self.assertContains(response, "disattivazioni")
