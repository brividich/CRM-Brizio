"""Avvisi dei ticket a richiedente e gestori: campanella e mail. Solo dati sintetici."""
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from core.models import Notifica
from tickets.models import StatoTicket, Ticket, TicketAllegato, TicketImpostazioni, TipoTicket
from tickets.services import avvisi
from tickets.services.lavorazione import prendi_in_carico
from tickets.services.stato import cambia_stato_ticket

IDS = {"rich@example.test": [101], "tec@example.test": [202], "team1@example.test": [301],
       "team2@example.test": [302]}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AvvisiTicketTests(TestCase):
    def setUp(self):
        TicketImpostazioni.objects.create(tipo=TipoTicket.IT, team_gestori=[
            {"nome": "Team Uno", "email": "team1@example.test"}, {"nome": "Team Due", "email": "Team2@example.test"},
        ])
        p = patch("core.notifiche.legacy_user_ids_for_email", side_effect=lambda e: IDS.get(e.lower(), []))
        p.start()
        self.addCleanup(p.stop)
        p = patch("tickets.views._update_ticket_sharepoint", return_value=None)
        p.start()
        self.addCleanup(p.stop)
        self.t = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Stampante sintetica", descrizione="Non stampa", categoria="HW",
            richiedente_nome="Rita Sintetica", richiedente_email="rich@example.test", richiedente_legacy_user_id=101,
        )

    def _notifiche(self, uid):
        return list(Notifica.objects.filter(legacy_user_id=uid).values_list("tipo", "url_azione"))

    def test_nuovo_al_team_e_conferma_al_richiedente(self):
        with self.captureOnCommitCallbacks(execute=True):
            avvisi.nuovo(self.t, autore_email="rich@example.test")
        self.assertEqual(self._notifiche(301), [("ticket_nuovo", f"/tickets/gestione/{self.t.pk}/")])
        self.assertEqual(self._notifiche(302), [("ticket_nuovo", f"/tickets/gestione/{self.t.pk}/")])
        self.assertEqual(self._notifiche(101), [("ticket_aperto", f"/tickets/{self.t.pk}/")])
        destinatari = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(destinatari, ["rich@example.test", "team1@example.test", "team2@example.test"])

    def test_nuovo_con_regola_attiva_una_sola_mail(self):
        """Se una regola Automazioni manda già la mail del ticket nuovo, al team solo la campanella."""
        from automazioni.models import AutomationAction, AutomationCondition, AutomationRule

        r = AutomationRule.objects.create(code="syn-nuovo-it", name="Nuovo IT", source_code="tickets",
                                          operation_type="insert", is_active=True, is_draft=False)
        AutomationCondition.objects.create(rule=r, field_name="tipo", operator="equals", expected_value="IT",
                                           value_type="string")
        AutomationAction.objects.create(rule=r, order=1, action_type="send_email", is_enabled=True,
                                        config_json={"to": "it@example.test"})
        with self.captureOnCommitCallbacks(execute=True):
            avvisi.nuovo(self.t, autore_email="rich@example.test")
        self.assertEqual(self._notifiche(301), [("ticket_nuovo", f"/tickets/gestione/{self.t.pk}/")])
        self.assertEqual([m.to[0] for m in mail.outbox], ["rich@example.test"])
        self.t.tipo = TipoTicket.MAN
        self.assertFalse(avvisi.regola_mail_nuovo_attiva(self.t))

    def test_presa_in_carico_avvisa_il_richiedente_non_chi_la_prende(self):
        with self.captureOnCommitCallbacks(execute=True):
            prendi_in_carico(self.t, nome="Tec Nico", email="tec@example.test")
        self.assertEqual(self._notifiche(101), [("ticket_preso", f"/tickets/{self.t.pk}/")])
        self.assertEqual(self._notifiche(202), [])

    def test_assegnato_da_altri_avvisa_il_tecnico(self):
        self.t.assegnato_a, self.t.assegnato_email = "Tec Nico", "tec@example.test"
        self.t.save()
        with self.captureOnCommitCallbacks(execute=True):
            avvisi.assegnato(self.t, autore_email="team1@example.test", autore_nome="Team Uno")
        self.assertEqual(self._notifiche(202), [("ticket_assegnato", f"/tickets/gestione/{self.t.pk}/")])
        self.assertIn("tec@example.test", [m.to[0] for m in mail.outbox])

    def test_risolto_chiede_conferma_chiuso_solo_campanella(self):
        with self.captureOnCommitCallbacks(execute=True):
            cambia_stato_ticket(self.t, StatoTicket.RISOLTO, utente_nome="Tec", utente_email="tec@example.test")
        self.assertEqual(self._notifiche(101), [("ticket_risolto", f"/tickets/{self.t.pk}/")])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("conferm", mail.outbox[0].subject.lower())
        with self.captureOnCommitCallbacks(execute=True):
            cambia_stato_ticket(self.t, StatoTicket.CHIUSO, utente_nome="Tec", utente_email="tec@example.test")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(("ticket_stato", f"/tickets/{self.t.pk}/"), self._notifiche(101))

    def test_il_richiedente_non_si_avvisa_da_solo(self):
        with self.captureOnCommitCallbacks(execute=True):
            cambia_stato_ticket(self.t, StatoTicket.ANNULLATO, utente_nome="Rita", utente_email="rich@example.test")
        self.assertEqual(self._notifiche(101), [])

    def test_commenti_vanno_all_altra_parte(self):
        with self.captureOnCommitCallbacks(execute=True):
            avvisi.commento(self.t, autore_email="rich@example.test", testo="Ancora rotta", da_richiedente=True,
                            interno=False)
        self.assertEqual([n[0] for n in self._notifiche(301)], ["ticket_commento"])
        self.t.assegnato_email = "tec@example.test"
        self.t.save()
        with self.captureOnCommitCallbacks(execute=True):
            avvisi.commento(self.t, autore_email="rich@example.test", testo="Ancora", da_richiedente=True,
                            interno=False)
            avvisi.commento(self.t, autore_email="tec@example.test", testo="Arrivo", da_richiedente=False,
                            interno=False)
            avvisi.commento(self.t, autore_email="tec@example.test", testo="Nota", da_richiedente=False,
                            interno=True)
        self.assertEqual([n[0] for n in self._notifiche(202)], ["ticket_commento"])
        self.assertEqual([n[0] for n in self._notifiche(101)], ["ticket_commento"])

    def test_riaperto_dal_richiedente_avvisa_il_tecnico(self):
        self.t.assegnato_email = "tec@example.test"
        self.t.save()
        with self.captureOnCommitCallbacks(execute=True):
            avvisi.azione_richiedente(self.t, azione="riapri", autore_email="rich@example.test", nota="Non va")
        self.assertEqual([n[0] for n in self._notifiche(202)], ["ticket_riaperto"])
        self.assertEqual(self._notifiche(301), [])

    def test_allegato_rifiutato_a_chi_l_ha_caricato(self):
        a = TicketAllegato.objects.create(ticket=self.t, nome_originale="foto.jpg", uploaded_by_nome="Tec",
                                          uploaded_by_email="tec@example.test", file="x.jpg")
        with self.captureOnCommitCallbacks(execute=True):
            avvisi.allegato_rifiutato(a, nota="Sfocata", autore_email="team1@example.test")
        self.assertEqual([n[0] for n in self._notifiche(202)], ["ticket_allegato_rifiutato"])

    def test_silenzio(self):
        with self.captureOnCommitCallbacks(execute=True), avvisi.silenzio():
            avvisi.nuovo(self.t)
        self.assertEqual(Notifica.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
