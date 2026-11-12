"""Pannelli laterali, selezione multipla e tabelle standard dove mancavano (scheda CVE, Proposte AI, Alert, pannelli)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAccettazioneRischio,
    SecurityAlert,
    SecurityAlertProposta,
    SecurityAlertSuppressionRule,
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityEventRecord,
    SecurityIncident,
    SecurityPropostaAi,
    SecurityRemediationTicket,
    SecuritySource,
    SecurityVpnAccess,
    Severity,
    SourceType,
    Status,
)
from security.services import cpe_ai


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_pannelli_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte pannelli", vendor="Demo", source_type=SourceType.EMAIL)
        self.event = SecurityEventRecord.objects.create(source=self.source, event_type="demo_evento", fingerprint="f1", dedup_hash="e1")

    def alert(self, title="Alert demo", severity=Severity.HIGH, status=Status.NEW, n=1):
        return SecurityAlert.objects.create(source=self.source, event=self.event, title=title, severity=severity, status=status, dedup_hash=f"a{n}")


class CveHostBulkTests(_Base):
    def setUp(self):
        super().setUp()
        self.record = SecurityCveRecord.objects.create(cve_id="CVE-2099-0101", cvss=9.1, severity="critical", nvd_fetched_at=timezone.now())
        for host, outcome in (("pc-uno", SecurityCveImpact.IMPACTS), ("pc-due", SecurityCveImpact.IMPACTS), ("pc-tre", SecurityCveImpact.TO_VERIFY)):
            SecurityCveImpact.objects.create(cve=self.record, host=host, outcome=outcome, explanation="demo", aperta_dal=timezone.now() - timedelta(days=3))
        self.url = reverse("security:cve_host_bulk", args=[self.record.cve_id])

    def test_detail_table_is_standard_with_selection_and_pc_panel(self):
        page = self.client.get(reverse("security:cve_detail", args=[self.record.cve_id]))
        self.assertContains(page, 'id="cve-host-bulk"')
        self.assertContains(page, 'form="cve-host-bulk" class="sec-bulk-item"')
        self.assertContains(page, reverse("security:preview_pc") + "?nome=pc-uno")
        self.assertContains(page, reverse("security:pc_detail") + "?nome=pc-uno")
        self.assertContains(page, 'value="accetta_rischio"')

    def test_ticket_for_selected_hosts(self):
        response = self.client.post(self.url, {"action": "case", "devices": ["pc-uno", "pc-due", "estraneo"]})
        case = SecurityRemediationTicket.objects.get()
        self.assertRedirects(response, reverse("security:case_detail", args=[case.pk]), fetch_redirect_response=False)
        self.assertEqual(case.tasks.count(), 2)
        self.assertIn("CVE-2099-0101", case.title)

    def test_accept_risk_needs_reason_and_date_then_one_per_host(self):
        self.client.post(self.url, {"action": "accetta_rischio", "devices": ["pc-uno", "pc-due"], "motivo": "corto"})
        self.assertFalse(SecurityAccettazioneRischio.objects.exists())
        scadenza = (timezone.localdate() + timedelta(days=60)).isoformat()
        motivo = "Macchina di collaudo isolata dalla rete, patch non disponibile dal fornitore"
        self.client.post(self.url, {"action": "accetta_rischio", "devices": ["pc-uno", "pc-due"], "motivo": motivo, "scadenza": scadenza})
        self.assertEqual(set(SecurityAccettazioneRischio.objects.values_list("host", flat=True)), {"pc-uno", "pc-due"})

    def test_accept_risk_needs_config_permission(self):
        scadenza = (timezone.localdate() + timedelta(days=60)).isoformat()
        with mock.patch("security.views_vuln.can_manage_security_config", return_value=False):
            self.client.post(self.url, {"action": "accetta_rischio", "devices": ["pc-uno"], "motivo": "x" * 40, "scadenza": scadenza})
        self.assertFalse(SecurityAccettazioneRischio.objects.exists())

    def test_confirm_ai_proposals_of_selected_hosts(self):
        proposta = SecurityPropostaAi.objects.create(
            tipo=SecurityPropostaAi.TIPO_ESITO, chiave=cpe_ai.chiave_esito(self.record.cve_id, "pc-tre"), cve=self.record, host="pc-tre",
            versione="1.0", proposta="non_impatta", motivazione="Versione corretta.", confidenza=90,
        )
        with mock.patch("security.views_vuln.can_manage_security_config", return_value=False):
            self.client.post(self.url, {"action": "proposte", "devices": ["pc-tre"]})
        proposta.refresh_from_db()
        self.assertEqual(proposta.stato, SecurityPropostaAi.APERTA)
        with mock.patch("security.views_vuln._queue_recompute") as recompute:
            self.client.post(self.url, {"action": "proposte", "devices": ["pc-tre", "pc-uno"]})
        recompute.assert_called_once()
        proposta.refresh_from_db()
        self.assertEqual((proposta.stato, proposta.decisa_da), (SecurityPropostaAi.ACCETTATA, self.user))

    def test_unknown_action_does_nothing(self):
        self.client.post(self.url, {"action": "cancella", "devices": ["pc-uno"]})
        self.assertFalse(SecurityRemediationTicket.objects.exists())


class AlertProposteRiapriTests(_Base):
    def test_reopen_selected_needs_note(self):
        alert = self.alert(status=Status.CLOSED)
        p = SecurityAlertProposta.objects.create(alert=alert, schema="x", esito="resolved", stato=SecurityAlertProposta.CHIUSA_AUTO,
                                                 decisa_il=timezone.now())
        url = reverse("security:alert_proposte_riapri")
        self.client.post(url, {"proposta_ids": [p.pk]})
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.CLOSED)
        self.client.post(url, {"proposta_ids": [p.pk], "nota": "Il backup non è rientrato"})
        alert.refresh_from_db()
        p.refresh_from_db()
        self.assertNotEqual(alert.status, Status.CLOSED)
        self.assertEqual(p.stato, SecurityAlertProposta.ANNULLATA)

    def test_page_has_selection_and_alert_panel(self):
        alert = self.alert(status=Status.CLOSED)
        SecurityAlertProposta.objects.create(alert=alert, schema="x", esito="resolved", stato=SecurityAlertProposta.CHIUSA_AUTO, decisa_il=timezone.now())
        page = self.client.get(reverse("security:alert_proposte"))
        self.assertContains(page, 'id="auto-bulk"')
        self.assertContains(page, reverse("security:preview", args=["alert", alert.pk]))


class AlertSnoozeBulkTests(_Base):
    def test_snooze_needs_future_date(self):
        a1, a2 = self.alert(n=1), self.alert(n=2, status=Status.SNOOZED)
        url = reverse("security:alerts_bulk")
        self.client.post(url, {"alert_ids": [a1.pk], "action": "snooze"})
        a1.refresh_from_db()
        self.assertEqual(a1.status, Status.NEW)
        domani = (timezone.localdate() + timedelta(days=2)).isoformat()
        self.client.post(url, {"alert_ids": [a1.pk, a2.pk], "action": "snooze", "snooze_until": domani})
        a1.refresh_from_db()
        self.assertEqual(a1.status, Status.SNOOZED)
        self.assertEqual(timezone.localtime(a1.snoozed_until).date().isoformat(), domani)


class PanelActionsTests(_Base):
    def test_ticket_status_from_panel_needs_outcome_to_close(self):
        case = SecurityRemediationTicket.objects.create(source=self.source, title="Ticket demo", status=Status.OPEN, dedup_hash="t1")
        url = reverse("security:case_status", args=[case.pk])
        xhr = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        response = self.client.post(url, {"status": "resolved", "pannello": "1"}, **xhr)
        self.assertContains(response, "scrivi l&#x27;esito")
        case.refresh_from_db()
        self.assertEqual(case.status, Status.OPEN)
        response = self.client.post(url, {"status": "resolved", "reason": "Patch installata", "pannello": "1"}, **xhr)
        self.assertContains(response, "Stato del caso aggiornato.")
        case.refresh_from_db()
        self.assertEqual(case.status, Status.RESOLVED)
        panel = self.client.get(reverse("security:preview", args=["ticket", case.pk]))
        self.assertContains(panel, reverse("security:case_status", args=[case.pk]))

    def test_incident_assign_to_me_from_panel(self):
        incident = SecurityIncident.objects.create(title="Mail sospetta", detected_at=timezone.now())
        panel = self.client.get(reverse("security:preview", args=["incident", incident.pk]))
        self.assertContains(panel, reverse("security:incident_owner_me", args=[incident.pk]))
        response = self.client.post(reverse("security:incident_owner_me", args=[incident.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "Incidente assegnato a te.")
        incident.refresh_from_db()
        self.assertEqual(incident.owner, self.user)

    def test_pc_bulk_accepts_grouped_rows(self):
        self.client.post(reverse("security:pc_bulk"), {"devices_gruppo": ["PC-A|PC-B", "PC-B|PC-C"], "pagina": "Tempi delle patch"})
        self.assertEqual(SecurityRemediationTicket.objects.get().tasks.count(), 3)


class PagineTests(_Base):
    def test_my_work_by_severity_with_panels(self):
        basso = self.alert("Alert basso", severity=Severity.LOW, n=1)
        alto = self.alert("Alert critico", severity=Severity.CRITICAL, n=2)
        page = self.client.get(reverse("security:my_work"))
        body = page.content.decode()
        self.assertLess(body.index("Alert critico"), body.index("Alert basso"))
        self.assertIn(reverse("security:preview", args=["alert", alto.pk]), body)
        self.assertIn(reverse("security:preview", args=["alert", basso.pk]), body)

    def test_suppression_form_prefilled_from_querystring(self):
        page = self.client.get(reverse("security:admin_config_suppressions"), {"name": "Falso positivo demo", "event_type": "demo_evento"})
        self.assertContains(page, 'value="Falso positivo demo"')
        self.assertContains(page, 'value="demo_evento"')
        self.assertFalse(SecurityAlertSuppressionRule.objects.exists())

    def test_vpn_exact_user_filter(self):
        now = timezone.now()
        for i, user in enumerate(("mario", "mario.rossi")):
            SecurityVpnAccess.objects.create(source=self.source, action="allowed", username=user, source_ip="203.0.113.9", kind="vpn",
                                             login_at=now - timedelta(hours=i + 1), duration_seconds=60, dedup_hash=f"vu{i}")
        page = self.client.get(reverse("security:vpn_history"), {"utente": "mario"})
        self.assertContains(page, 'name="utente" value="mario"')
        self.assertNotContains(page, "mario.rossi")
        panel = self.client.get(reverse("security:preview_vpn_user"), {"utente": "mario"})
        self.assertContains(panel, "?utente=mario&amp;giorni=30")

    def test_restore_tests_paginated(self):
        page = self.client.get(reverse("security:backup_ripristini"))
        self.assertEqual(page.status_code, 200)

    def test_page_help_for_new_ticket(self):
        from security.templatetags.security_help import soc_page_help_url

        self.assertIn("13-lavoro-quotidiano", soc_page_help_url("case_create"))
        self.assertIn("#soppressioni", soc_page_help_url("admin_config_suppressions"))
