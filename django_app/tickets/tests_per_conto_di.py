"""Ticket aperto per conto di un collega e chiuso al volo (solo manutentori e IT).
Solo dati sintetici."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.services import squadra_manutenzione
from core.models import AccessGroup, AccessGroupMembership, Profile, UserOnboarding
from tickets.models import EsitoIntervento, StatoTicket, Ticket

User = get_user_model()


def _onboarding(user):
    UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PerContoDiTests(TestCase):
    def setUp(self):
        self.manut = User.objects.create_user(username="syn.pcd.manut", first_name="Manu", last_name="Tentore")
        self.collega = User.objects.create_user(username="syn.pcd.collega", first_name="Col", last_name="Lega",
                                                email="collega@example.com")
        self.estraneo = User.objects.create_user(username="syn.pcd.altro")
        for user, legacy in ((self.manut, 991001), (self.collega, 991002), (self.estraneo, 991003)):
            Profile.objects.create(user=user, legacy_user_id=legacy)
            _onboarding(user)
        gruppo = AccessGroup.objects.create(code="syn-pcd-squadra", label="Squadra sintetica", priority=300)
        AccessGroupMembership.objects.create(group=gruppo, legacy_user_id=991001)
        squadra_manutenzione.salva_impostazioni(gruppo="syn-pcd-squadra", assegnatario="")

    def _payload(self, **extra):
        data = {
            "tipo": "MAN", "incide_sicurezza": "0", "categoria": "CNC", "priorita": "MEDIA",
            "titolo": "Perdita sintetica", "descrizione": "Descrizione sintetica",
            "asset_descrizione_libera": "Macchina sintetica",
        }
        data.update(extra)
        return data

    def _patches(self):
        return (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._can_manage_tickets", return_value=False),
            patch("tickets.views._get_assets_for_select", return_value=[]),
            patch("tickets.views._push_ticket_to_sharepoint", return_value=None),
        )

    def test_manutentore_vede_il_campo_e_apre_per_il_collega(self):
        self.client.force_login(self.manut)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=MAN")
            self.assertContains(page, "Per conto di")
            response = self.client.post(reverse("tickets:nuovo") + "?tipo=MAN",
                                        self._payload(per_conto_di=str(self.collega.pk)))
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.richiedente_user_id, self.collega.pk)
        self.assertEqual(ticket.aperto_da_user_id, self.manut.pk)
        self.assertTrue(ticket.aperto_da_nome)
        # Chi l'ha compilato continua a vederlo
        with p1, p2, p3, p4:
            detail = self.client.get(reverse("tickets:detail", args=[ticket.pk]))
        self.assertEqual(detail.status_code, 200)

    def test_chi_non_e_della_squadra_non_puo(self):
        self.client.force_login(self.estraneo)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=MAN")
            self.assertNotContains(page, "Per conto di")
            self.client.post(reverse("tickets:nuovo") + "?tipo=MAN",
                             self._payload(per_conto_di=str(self.collega.pk)))
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.richiedente_user_id, self.estraneo.pk)
        self.assertIsNone(ticket.aperto_da_user_id)

    def test_errore_conserva_la_scelta(self):
        self.client.force_login(self.manut)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            response = self.client.post(reverse("tickets:nuovo") + "?tipo=MAN",
                                        self._payload(per_conto_di=str(self.collega.pk), titolo=""))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-hub-form-error")
        self.assertContains(response, f'value="{self.collega.pk}" selected')
        self.assertContains(response, "Descrizione sintetica")
        self.assertEqual(Ticket.objects.count(), 0)

    def _al_volo(self, **extra):
        return self._payload(per_conto_di=str(self.collega.pk), chiudi_subito="1",
                             intervento_svolto="Sostituito fusibile sintetico", **extra)

    def _post_al_volo(self, payload):
        self.client.force_login(self.manut)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4, patch("tickets.views._silenzia_automazioni_import") as silenzia:
            response = self.client.post(reverse("tickets:nuovo") + "?tipo=MAN", payload)
        return response, silenzia

    def test_al_volo_nasce_chiuso_con_intervento(self):
        response, silenzia = self._post_al_volo(self._al_volo(intervento_ore="1,5"))
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.stato, StatoTicket.CHIUSO)
        self.assertIsNotNone(ticket.closed_at)
        self.assertEqual(ticket.richiedente_user_id, self.collega.pk)
        self.assertEqual(ticket.risolto_da_nome, ticket.aperto_da_nome)
        intervento = ticket.interventi.get()
        self.assertEqual(intervento.esito, EsitoIntervento.COMPLETATO)
        self.assertEqual(intervento.descrizione_lavoro, "Sostituito fusibile sintetico")
        self.assertEqual(intervento.durata_ore, 1.5)
        self.assertEqual(intervento.data_fine - intervento.data_inizio, timedelta(hours=1.5))
        self.assertEqual(ticket.data_primo_intervento, intervento.data_inizio)
        self.assertEqual(ticket.created_at, intervento.data_inizio)
        self.assertEqual(ticket.closed_at, intervento.data_fine)
        self.assertTrue(ticket.commenti.filter(is_interno=False, testo__contains="fusibile").exists())
        self.assertEqual(ticket.stato_log.get().a_stato, StatoTicket.CHIUSO)
        silenzia.assert_called_once()
        self.assertEqual(silenzia.call_args.args[0], [ticket.pk])

    def test_al_volo_con_sicurezza_lascia_gli_avvisi(self):
        payload = self._al_volo()
        payload["incide_sicurezza"] = "1"
        _response, silenzia = self._post_al_volo(payload)
        self.assertEqual(Ticket.objects.get().stato, StatoTicket.CHIUSO)
        silenzia.assert_not_called()

    def test_al_volo_senza_lavoro_non_crea_e_conserva_i_campi(self):
        payload = self._al_volo(intervento_ore="2")
        payload["intervento_svolto"] = ""
        response, _silenzia = self._post_al_volo(payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scrivi cosa è stato fatto")
        self.assertContains(response, 'value="1" checked')
        self.assertEqual(Ticket.objects.count(), 0)

    def test_al_volo_date_e_ore_non_valide(self):
        futuro = (timezone.localtime() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        for extra, messaggio in (
            ({"intervento_quando": futuro}, "non può essere futura"),
            ({"intervento_quando": "2026-13-45T10:00"}, "non è valida"),
            ({"intervento_ore": "abc"}, "non sono valide"),
            ({"intervento_ore": "-1"}, "non sono valide"),
        ):
            with self.subTest(extra=extra):
                response, _silenzia = self._post_al_volo(self._al_volo(**extra))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, messaggio)
                self.assertEqual(Ticket.objects.count(), 0)

    def test_al_volo_data_passata_vale_per_ticket_e_intervento(self):
        passato = (timezone.localtime() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
        self._post_al_volo(self._al_volo(intervento_quando=passato, intervento_ore="2"))
        ticket = Ticket.objects.get()
        intervento = ticket.interventi.get()
        self.assertEqual(timezone.localtime(ticket.closed_at).strftime("%Y-%m-%dT%H:%M"), passato)
        self.assertEqual(ticket.closed_at, intervento.data_fine)
        self.assertEqual(ticket.created_at, intervento.data_inizio)
        self.assertEqual(ticket.closed_at - ticket.created_at, timedelta(hours=2))
        # Il momento vero della registrazione resta nel log di stato
        self.assertGreater(ticket.stato_log.get().created_at, ticket.closed_at)

    def test_chi_non_e_ammesso_non_chiude_al_volo(self):
        self.client.force_login(self.estraneo)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=MAN")
            self.assertNotContains(page, "Già risolto")
            self.client.post(reverse("tickets:nuovo") + "?tipo=MAN", self._al_volo())
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.stato, StatoTicket.APERTA)
        self.assertEqual(ticket.interventi.count(), 0)

    def _payload_it(self, **extra):
        data = self._payload(categoria="PC", **extra)
        data["tipo"] = "IT"
        return data

    def test_it_solo_per_i_gestori_it(self):
        def gestisce_it(_request, tipo=None):
            return tipo == "IT"

        self.client.force_login(self.manut)
        p1, _p2, p3, p4 = self._patches()
        with p1, p3, p4, patch("tickets.views._can_manage_tickets", side_effect=gestisce_it):
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=IT")
            self.assertContains(page, "Per conto di")
            self.assertContains(page, "Già risolto")
            self.client.post(reverse("tickets:nuovo") + "?tipo=IT", self._payload_it(
                per_conto_di=str(self.collega.pk), chiudi_subito="1", intervento_svolto="Riavviato servizio sintetico",
            ))
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.richiedente_user_id, self.collega.pk)
        self.assertEqual(ticket.stato, StatoTicket.CHIUSO)

    def test_squadra_manutenzione_non_vale_per_l_it(self):
        self.client.force_login(self.manut)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=IT")
            self.assertNotContains(page, "Per conto di")
            self.assertNotContains(page, "Già risolto")
            self.client.post(reverse("tickets:nuovo") + "?tipo=IT", self._payload_it(
                per_conto_di=str(self.collega.pk), chiudi_subito="1", intervento_svolto="Sintetico",
            ))
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.richiedente_user_id, self.manut.pk)
        self.assertEqual(ticket.stato, StatoTicket.APERTA)

    def test_il_richiedente_vede_intervento_e_compilatore(self):
        self._post_al_volo(self._al_volo())
        ticket = Ticket.objects.get()
        self.client.force_login(self.collega)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            detail = self.client.get(reverse("tickets:detail", args=[ticket.pk]))
        self.assertContains(detail, "per suo conto")
        self.assertContains(detail, "Sostituito fusibile sintetico")
