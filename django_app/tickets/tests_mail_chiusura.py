"""Mail di chiusura al richiedente: regola solo su CHIUSO e «Rimanda la mail». Solo dati sintetici."""
from importlib import import_module

from django.apps import apps as django_apps
from django.urls import reverse

from automazioni.models import AutomationAction, AutomationCondition, AutomationRule, AutomationRunLog
from tickets.models import StatoTicket, TicketCommento, TicketStatoLog
from tickets.services.mail_chiusura import REGOLA, rimanda_mail_chiusura
from tickets.tests_lavorazione import LavorazioneBase


class MailChiusuraTests(LavorazioneBase):
    def setUp(self):
        super().setUp()
        self.rule = AutomationRule.objects.create(
            code=REGOLA, name="Cambio stato ticket - email richiedente", source_code="tickets",
            operation_type="update", trigger_scope="specific_field", watched_field="stato",
            is_active=True, is_draft=False,
        )
        AutomationCondition.objects.create(rule=self.rule, order=1, field_name="stato", operator="changed",
                                           value_type="string")
        AutomationCondition.objects.create(rule=self.rule, order=2, field_name="richiedente_email",
                                           operator="is_not_empty", value_type="string")
        AutomationAction.objects.create(
            rule=self.rule, order=1, action_type="write_log",
            config_json={"message_template": "Ticket {numero_ticket} chiuso"},
        )
        import_module("automazioni.migrations.0043_ticket_mail_solo_chiusura").applica(django_apps, None)

    def test_migrazione_aggiunge_condizione_chiuso_una_volta(self):
        modulo = import_module("automazioni.migrations.0043_ticket_mail_solo_chiusura")
        modulo.applica(django_apps, None)
        condizioni = AutomationCondition.objects.filter(rule=self.rule, field_name="stato", operator="equals")
        self.assertEqual(list(condizioni.values_list("expected_value", flat=True)), ["CHIUSO"])

    def test_rimanda_su_ticket_chiuso(self):
        ticket = self._ticket(stato=StatoTicket.CHIUSO, richiedente_email="rich@example.com")
        TicketStatoLog.objects.create(ticket=ticket, da_stato=StatoTicket.IN_CARICO, a_stato=StatoTicket.CHIUSO,
                                      utente_nome="Tec")
        riuscito, messaggio = rimanda_mail_chiusura(ticket, self.tecnico)
        self.assertTrue(riuscito, messaggio)
        run = AutomationRunLog.objects.get(rule=self.rule)
        self.assertEqual(run.status, "success")
        self.assertEqual(run.old_payload_json["stato"], StatoTicket.IN_CARICO)

    def test_non_rimanda_se_non_chiuso_o_senza_mail(self):
        aperto = self._ticket(stato=StatoTicket.IN_CARICO, richiedente_email="rich@example.com")
        self.assertFalse(rimanda_mail_chiusura(aperto)[0])
        senza = self._ticket(stato=StatoTicket.CHIUSO, richiedente_email="")
        self.assertFalse(rimanda_mail_chiusura(senza)[0])
        self.assertFalse(AutomationRunLog.objects.filter(rule=self.rule).exists())

    def test_regola_spenta(self):
        AutomationRule.objects.filter(pk=self.rule.pk).update(is_active=False)
        ticket = self._ticket(stato=StatoTicket.CHIUSO, richiedente_email="rich@example.com")
        riuscito, messaggio = rimanda_mail_chiusura(ticket)
        self.assertFalse(riuscito)
        self.assertIn("spenta", messaggio)

    def test_pulsante_e_vista(self):
        ticket = self._ticket(stato=StatoTicket.CHIUSO, richiedente_email="rich@example.com")
        ticket.closed_at = ticket.created_at
        ticket.save(update_fields=["closed_at"])
        dettaglio = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk]))
        self.assertContains(dettaglio, "Rimanda la mail")
        response = self.client.post(reverse("tickets:gestione_rimanda_mail_chiusura", args=[ticket.pk]))
        self.assertRedirects(response, reverse("tickets:gestione_detail", args=[ticket.pk]),
                             fetch_redirect_response=False)
        self.assertTrue(TicketCommento.objects.filter(ticket=ticket, testo__startswith="Mail di chiusura").exists())
        self.assertEqual(self.client.get(reverse("tickets:gestione_rimanda_mail_chiusura", args=[ticket.pk])).status_code, 405)
