"""Eventi ingeriti (promozione ad alert + regole apprese + apprendimento AI) e KPI senza doppi conteggi."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlert, SecurityAlertActionLog, SecurityEscalationRule, SecurityEventRecord, SecurityKpiSnapshot, SecurityReport,
    SecurityReportMetric, SecuritySource, SecurityVpnAccess,
)
from security.services.kpi_dashboard import kpi_detail, kpi_overview
from security.services.kpi_service import build_daily_kpi_snapshots
from security.services.rule_engine import evaluate_security_rules


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_ev", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Casella SOC", source_type="email", vendor="mailbox")
        self.today = timezone.localdate()


class KpiNoDoubleCountTests(_Base):
    def _report(self, day, period=None, report_type="watchguard_epdr_executive_report", **metrics):
        payload = {"period_start": str(period[0]), "period_end": str(period[1])} if period else {}
        report = SecurityReport.objects.create(source=self.source, report_type=report_type, title="Report", report_date=day,
                                               parser_name="p", parsed_payload=payload)
        for name, value in metrics.items():
            SecurityReportMetric.objects.create(report=report, name=name, value=value)
        return report

    def _tiles(self, days=7):
        return {t["name"]: t for domain in kpi_overview(self.today, days) for t in domain["tiles"]}

    def test_unprotected_endpoints_same_value_on_several_days_is_not_summed(self):
        for offset in range(3):
            self._report(self.today - timedelta(days=offset), watchguard_epdr_unprotected_endpoints=12)
        self.assertEqual(self._tiles()["watchguard_epdr_unprotected_endpoints"]["value"], 12)

    def test_same_report_read_twice_in_a_day_counts_once(self):
        self._report(self.today, report_type="synology_active_backup", backup_failed_count=2, watchguard_epdr_unprotected_endpoints=5)
        self._report(self.today, report_type="synology_active_backup", backup_failed_count=2, watchguard_epdr_unprotected_endpoints=5)
        tiles = self._tiles()
        self.assertEqual(tiles["backup_failed_count"]["value"], 2)
        self.assertEqual(tiles["watchguard_epdr_unprotected_endpoints"]["value"], 5)

    def test_overlapping_weekly_reports_count_the_period_once(self):
        # Report settimanale che arriva ogni giorno con la settimana che scorre: si conta il piu' recente.
        for offset in range(3):
            day = self.today - timedelta(days=offset)
            self._report(day, period=(day - timedelta(days=6), day), watchguard_malware_detected_count=4)
        self.assertEqual(self._tiles()["watchguard_malware_detected_count"]["value"], 4)

    def test_daily_reports_are_still_summed(self):
        for offset in range(3):
            day = self.today - timedelta(days=offset)
            self._report(day, period=(day, day), report_type="watchguard_dimension_executive_summary", watchguard_botnet_blocked_count=3)
        self.assertEqual(self._tiles()["watchguard_botnet_blocked_count"]["value"], 9)

    def test_detail_marks_duplicate_reports_and_snapshot_is_deduplicated(self):
        self._report(self.today, watchguard_epdr_unprotected_endpoints=7)
        self._report(self.today, watchguard_epdr_unprotected_endpoints=7)
        detail = kpi_detail("watchguard_epdr_unprotected_endpoints", self.today, 7)
        self.assertEqual(detail["value"], 7)
        self.assertEqual(sorted(m.counted for m in detail["reports"]), [False, True])
        build_daily_kpi_snapshots(self.today)
        snap = SecurityKpiSnapshot.objects.get(name="watchguard_epdr_unprotected_endpoints", snapshot_date=self.today)
        self.assertEqual(snap.value, 7)
        page = self.client.get(reverse("security:kpi_detail", args=["watchguard_epdr_unprotected_endpoints"]))
        self.assertContains(page, "no, doppione")
        self.assertContains(page, 'data-href="#giorno-')

    def test_stale_wrong_snapshot_does_not_override_report_value(self):
        self._report(self.today, watchguard_epdr_unprotected_endpoints=6)
        SecurityKpiSnapshot.objects.create(source=self.source, snapshot_date=self.today, name="watchguard_epdr_unprotected_endpoints", value=18)
        self.assertEqual(self._tiles()["watchguard_epdr_unprotected_endpoints"]["value"], 6)


class EventsTests(_Base):
    def _event(self, computer="PC-PROD-01", **extra):
        payload = {"type": "endpoint_outdated", "computer": computer, "title": f"Protezione non aggiornata su {computer}", **extra}
        return SecurityEventRecord.objects.create(
            source=self.source, event_type="watchguard_epdr_detection", severity="low", fingerprint=f"fp-{computer}",
            dedup_hash=f"dh-{computer}-{SecurityEventRecord.objects.count()}", payload=payload,
        )

    def test_list_and_detail_show_events_judged_ok(self):
        event = self._event()
        evaluate_security_rules()
        event.refresh_from_db()
        self.assertEqual(event.decision_trace["decision"], "kpi_only")
        page = self.client.get(reverse("security:events"))
        self.assertContains(page, "PC-PROD-01")
        self.assertContains(page, "Giudicato a posto")
        self.assertEqual(page.context["decision_rows"][1]["count"], 1)
        only_ok = self.client.get(reverse("security:events"), {"decision": "alert"})
        self.assertEqual(only_ok.context["page"].paginator.count, 0)
        day = self.client.get(reverse("security:events"), {"giorno": self.today.isoformat()})
        self.assertEqual(day.context["selected_day"], self.today)
        detail = self.client.get(reverse("security:event_detail", args=[event.pk]))
        self.assertContains(detail, "Crea l'alert")

    def test_promote_creates_alert_learned_rule_and_learning_record(self):
        from ai_assistant.models import AiProposta

        event = self._event()
        evaluate_security_rules()
        response = self.client.post(reverse("security:event_promote", args=[event.pk]), {
            "severity": "high", "reason": "PC di produzione: non deve restare scoperto", "learn": "1", "match": ["type", "computer"],
        })
        alert = SecurityAlert.objects.get(event=event)
        self.assertRedirects(response, reverse("security:alert_detail", args=[alert.pk]), fetch_redirect_response=False)
        self.assertEqual(alert.severity, "high")
        self.assertTrue(alert.decision_trace["manual_escalation"])
        event.refresh_from_db()
        self.assertEqual(event.decision_trace["decision"], "alert")
        self.assertEqual(event.decision_trace["previous_decision"], "kpi_only")
        self.assertTrue(SecurityAlertActionLog.objects.filter(alert=alert, action="manual_escalation").exists())
        rule = SecurityEscalationRule.objects.get()
        self.assertEqual(rule.match_payload, {"type": "endpoint_outdated", "computer": "PC-PROD-01"})
        learned = AiProposta.objects.get(modulo="soc", azione="motore_evento")
        self.assertEqual(learned.esito, AiProposta.SCARTATA)

        # Il motore ora riconosce da solo lo stesso fatto sullo stesso computer, non sugli altri.
        same = self._event()
        other = self._event(computer="PC-UFFICIO-02")
        evaluate_security_rules()
        same.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(same.decision_trace["decision"], "alert")
        self.assertEqual(same.decision_trace["learned_rule_id"], rule.pk)
        self.assertEqual(other.decision_trace["decision"], "kpi_only")
        rule.refresh_from_db()
        self.assertEqual(rule.hit_count, 1)

    def test_promote_requires_reason(self):
        event = self._event()
        self.client.post(reverse("security:event_promote", args=[event.pk]), {"severity": "high", "reason": ""})
        self.assertFalse(SecurityAlert.objects.exists())

    def test_ai_proposal_is_compared_with_the_human_decision(self):
        from ai_assistant.models import AiProposta

        event = self._event()
        evaluate_security_rules()
        answer = {"ok": True, "text": "VERDETTO: OK\nGRAVITÀ: bassa\nNon c'è nulla di anomalo.", "error": "", "model": "m", "disclaimer": "d"}
        with mock.patch("security.services.ai_explain._ask", return_value=answer):
            page = self.client.post(reverse("security:event_ai_triage", args=[event.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(page, "è a posto")
        proposal = AiProposta.objects.get(modulo="soc", azione="triage_evento")
        self.assertEqual(proposal.proposta, {"crea_alert": False})
        self.client.post(reverse("security:event_promote", args=[event.pk]), {"severity": "warning", "reason": "era un allarme"})
        proposal.refresh_from_db()
        self.assertEqual(proposal.esito, AiProposta.SCARTATA)
        self.assertIn("crea_alert", proposal.campi_corretti)

    def test_learned_rule_appears_in_ai_context_as_explicit_section(self):
        from security.services.event_triage import triage_context

        event = self._event()
        SecurityEscalationRule.objects.create(name="r", event_type=event.event_type, match_payload={"computer": "PC-PROD-01"}, severity="high")
        self.assertIn("DA TRATTARE COME ALLARME", triage_context(event))

    def test_toggle_rule_needs_config_permission(self):
        rule = SecurityEscalationRule.objects.create(name="r", event_type="x", severity="high")
        self.client.post(reverse("security:escalation_rule_toggle", args=[rule.pk]), {"next": "https://evil.example/"})
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        plain = get_user_model().objects.create(username="soc_viewer", is_staff=True)
        self.client.force_login(plain)
        with mock.patch("security.services.configuration.can_manage_security_config", return_value=False):
            self.client.post(reverse("security:escalation_rule_toggle", args=[rule.pk]))
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)


class InteractiveChartsTests(_Base):
    def test_vpn_day_selection_keeps_period_chart_and_filters_the_rest(self):
        now = timezone.now()
        for offset, user in ((0, "a.rossi"), (0, "a.rossi"), (1, "b.verdi")):
            SecurityVpnAccess.objects.create(source=self.source, action="allowed", username=user, source_ip="203.0.113.5", kind="vpn",
                                             login_at=now - timedelta(days=offset), dedup_hash=f"h{offset}{user}{SecurityVpnAccess.objects.count()}")
        page = self.client.get(reverse("security:vpn_history"), {"giorni": 7})
        self.assertContains(page, "data-tip=")
        self.assertContains(page, "a.rossi: 2")
        day = (now - timedelta(days=1)).astimezone(timezone.get_current_timezone()).date()
        selected = self.client.get(reverse("security:vpn_history"), {"giorni": 7, "giorno": day.isoformat()})
        self.assertEqual(selected.context["summary"]["total"], 1)
        self.assertEqual(len(selected.context["daily"]["days"]), 7)
        self.assertContains(selected, "is-selected")

    def test_dashboard_trend_columns_link_to_events_of_the_day(self):
        SecurityEventRecord.objects.create(source=self.source, event_type="x", fingerprint="f", dedup_hash="d", payload={})
        page = self.client.get(reverse("security:dashboard"))
        self.assertContains(page, "giorno=" + self.today.isoformat())
        self.assertContains(page, "eventi oggi")
