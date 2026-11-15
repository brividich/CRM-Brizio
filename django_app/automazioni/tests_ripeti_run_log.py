"""«Ripeti» di un run log da Mail inviate e dal dettaglio."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserOnboarding

from .managed_flows import assicura_installati
from .models import (
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
    EmailInviata,
    ManagedFlow,
)
from .ripeti import come_ripetere, ripeti

User = get_user_model()


class RipetiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("rip_admin", "rip@x.local", "x")
        UserOnboarding.objects.update_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)
        self.rule = AutomationRule.objects.create(
            code="rip-regola", name="Regola da ripetere", source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES, is_active=True, is_draft=False,
        )
        self.run_log = AutomationRunLog.objects.create(
            rule=self.rule, source_code="assenze", operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.ERROR, payload_json={"id": 7},
        )

    def test_regola_normale_si_ripete_con_lo_stesso_payload(self):
        self.assertEqual(come_ripetere(self.run_log)["modo"], "regola")
        with patch("django_q.tasks.async_task", side_effect=RuntimeError("no cluster")), \
                patch("automazioni.services.run_rule") as run_rule:
            run_rule.return_value = AutomationRunLog.objects.create(
                rule=self.rule, source_code="assenze", operation_type="update", payload_json={})
            ok, _msg = ripeti(self.run_log, self.admin)
        self.assertTrue(ok)
        args, kwargs = run_rule.call_args
        self.assertEqual(args[0], self.rule)
        self.assertEqual(args[1], {"id": 7})
        self.assertTrue(kwargs["payload_enriched"])

    def test_regola_spenta_non_si_ripete(self):
        self.rule.is_active = False
        self.rule.save()
        ok, msg = ripeti(self.run_log, self.admin)
        self.assertFalse(ok)
        self.assertIn("spenta", msg)

    def test_flusso_su_evento_non_si_ripete_e_pianificato_si(self):
        assicura_installati()
        evento = ManagedFlow.objects.filter(kind="event").select_related("rule").first()
        log_evento = AutomationRunLog.objects.create(rule=evento.rule, source_code="managed_flows",
                                                     operation_type="manual", payload_json={})
        self.assertIsNone(come_ripetere(log_evento)["modo"])
        pianificato = ManagedFlow.objects.filter(kind="schedule").select_related("rule").first()
        log_pian = AutomationRunLog.objects.create(rule=pianificato.rule, source_code="managed_flows",
                                                   operation_type="manual", payload_json={})
        piano = come_ripetere(log_pian)
        self.assertEqual((piano["modo"], piano["codice"]), ("pianificato", pianificato.code))
        with patch("django_q.tasks.async_task") as accoda:
            ok, _msg = ripeti(log_pian, self.admin)
        self.assertTrue(ok)
        self.assertEqual(accoda.call_args[0][:2], ("automazioni.managed_flows.run_managed_flow", pianificato.code))

    def test_vista_accoda_e_torna_a_mail_inviate(self):
        prossima = reverse("admin_portale:automazioni_mail_inviate") + "?esito=errore"
        with patch("django_q.tasks.async_task") as accoda:
            r = self.client.post(reverse("admin_portale:automazioni_run_log_ripeti", args=[self.run_log.pk]),
                                 {"next": prossima})
        self.assertRedirects(r, prossima, fetch_redirect_response=False)
        self.assertEqual(accoda.call_args[0][0], "automazioni.ripeti.ripeti_regola")

    def test_vista_ignora_next_esterno(self):
        with patch("django_q.tasks.async_task"):
            r = self.client.post(reverse("admin_portale:automazioni_run_log_ripeti", args=[self.run_log.pk]),
                                 {"next": "https://esterno.example.com/"})
        self.assertRedirects(r, reverse("admin_portale:automazioni_run_log_detail", args=[self.run_log.pk]),
                             fetch_redirect_response=False)

    def test_mail_inviate_mostra_ripeti_sulle_mail_in_errore(self):
        EmailInviata.objects.create(origine="automazione", destinatari="a@example.com", oggetto="Ko",
                                    esito=EmailInviata.ESITO_ERRORE, errore="SMTP down",
                                    regola=self.rule, run_log=self.run_log)
        r = self.client.get(reverse("admin_portale:automazioni_mail_inviate"))
        self.assertContains(r, reverse("admin_portale:automazioni_run_log_ripeti", args=[self.run_log.pk]))
        self.assertContains(r, reverse("admin_portale:automazioni_run_log_detail", args=[self.run_log.pk]))

    def test_dettaglio_run_log_ha_ripeti(self):
        r = self.client.get(reverse("admin_portale:automazioni_run_log_detail", args=[self.run_log.pk]))
        self.assertContains(r, reverse("admin_portale:automazioni_run_log_ripeti", args=[self.run_log.pk]))
        self.assertContains(r, "Prova con questi dati")
