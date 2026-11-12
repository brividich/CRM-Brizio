"""Sala riunioni per le visite (sale del KICK-OFF). Dati sintetici."""
from __future__ import annotations

from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from tasks.models import MeetingRoom
from tasks.services.sale import disponibilita_giorno

from . import sale, servizi
from .models import CategoriaVisita, Preregistrazione, Referente, RichiestaAppuntamento, SalaInviti

MAIL = "core.email_utils.send_hub_mail"
GRAPH_PRONTO = "core.outlook_calendar.graph_ready"
CREA_EVENTO = "core.outlook_calendar.create_event"


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.sala = MeetingRoom.objects.create(nome="Sala Prova", email="sala.prova@example.local", capienza=8)
        SalaInviti.objects.create(sala=self.sala)
        self.ref = Referente.objects.create(nome="Prova", cognome="Referente", email="referente@example.local")
        CategoriaVisita.objects.create(nome="Riunione")
        self.domani = timezone.localdate() + timedelta(days=1)
        self.user = get_user_model().objects.create_superuser("dip_sala", "referente@example.local", "x", first_name="Prova", last_name="Referente")
        UserOnboarding.objects.get_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)

    def visita(self, inizio=time(10, 0), fine=time(11, 0), **kw):
        return servizi.crea_preregistrazione(ospite_nome="Ospite Uno", ospite_email="uno@example.local", referente=self.ref,
                                             creata_da="test", data_visita=self.domani, ora_inizio=inizio, ora_fine=fine,
                                             sala=self.sala, **kw)


class VerificaTests(Base):
    def test_sovrapposizione_con_altra_visita(self):
        self.visita()
        self.assertIn("già prenotata", sale.verifica(self.sala, self.domani, time(10, 30), time(11, 30)))
        self.assertEqual(sale.verifica(self.sala, self.domani, time(11, 0), time(12, 0)), "")

    def test_senza_ora_non_si_prenota(self):
        self.assertIn("ora", sale.verifica(self.sala, self.domani, None, None))

    def test_il_kickoff_non_vede_le_visite(self):
        self.visita()
        dati = disponibilita_giorno(self.domani)
        self.assertEqual(next(s for s in dati["sale"] if s["id"] == self.sala.pk)["blocchi"], [])

    def test_negli_inviti_solo_le_sale_scelte(self):
        altra = MeetingRoom.objects.create(nome="Sala Non Scelta")
        self.assertEqual(list(sale.sale_attive()), [self.sala])
        SalaInviti.objects.create(sala=altra)
        self.assertEqual(set(sale.sale_attive()), {self.sala, altra})


@override_settings(RECEPTION_NATIVA=True)
class AnnunciaConSalaTests(Base):
    def dati(self, **kw):
        d = {"nome": "Ospite Prova", "email": "ospite@example.local", "data_visita": self.domani.isoformat(),
             "ora_inizio": "09:00", "ora_fine": "10:00", "motivo": "Riunione", "sala": str(self.sala.pk)}
        d.update(kw)
        return d

    def test_prenota_in_outlook_dal_calendario_del_referente(self):
        with patch(MAIL) as invia, patch(GRAPH_PRONTO, return_value=True), patch(CREA_EVENTO, return_value={"id": "ev-1"}) as crea:
            self.client.post(reverse("reception:annuncia"), self.dati())
        pre = Preregistrazione.objects.get()
        self.assertEqual((pre.sala, pre.outlook_event_id, pre.outlook_organizer_email), (self.sala, "ev-1", "referente@example.local"))
        payload = crea.call_args.kwargs["payload"]
        self.assertEqual(crea.call_args.kwargs["target_email"], "referente@example.local")
        self.assertEqual(payload["attendees"], [{"emailAddress": {"address": "sala.prova@example.local", "name": "Sala Prova"}, "type": "resource"}])
        # L'evento è già nel calendario del referente: la sua mail non porta un secondo invito .ics
        mail_referente = next(c for c in invia.call_args_list if c.args[2] == ["referente@example.local"])
        self.assertEqual(mail_referente.kwargs["attachments"], [])

    def test_senza_outlook_la_sala_resta_nel_portale(self):
        with patch(MAIL), patch(GRAPH_PRONTO, return_value=False):
            r = self.client.post(reverse("reception:annuncia"), self.dati(), follow=True)
        pre = Preregistrazione.objects.get()
        self.assertEqual((pre.sala, pre.outlook_event_id), (self.sala, ""))
        self.assertContains(r, "prenotala anche in Outlook")

    def test_sala_occupata_niente_visita(self):
        self.visita()
        with patch(MAIL), patch(GRAPH_PRONTO, return_value=False):
            r = self.client.post(reverse("reception:annuncia"), self.dati(ora_inizio="10:30", ora_fine="11:30"), follow=True)
        self.assertEqual(Preregistrazione.objects.count(), 1)
        self.assertContains(r, "già prenotata")

    def test_senza_sala_come_prima(self):
        with patch(MAIL), patch(CREA_EVENTO) as crea:
            self.client.post(reverse("reception:annuncia"), self.dati(sala=""))
        self.assertIsNone(Preregistrazione.objects.get().sala)
        crea.assert_not_called()

    def test_la_pagina_mostra_la_scelta_della_sala(self):
        self.assertContains(self.client.get(reverse("reception:annuncia")), "Prenota una sala")


@override_settings(RECEPTION_NATIVA=True)
class ApprovaConSalaTests(Base):
    def test_approvando_si_prenota_la_sala(self):
        r = servizi.nuova_richiesta(nome="Anna", cognome="Esempio", email="anna@example.local", data_visita=self.domani,
                                    referente_indicato="Prova Referente")
        RichiestaAppuntamento.objects.filter(pk=r.pk).update(stato=RichiestaAppuntamento.IN_ATTESA, referente=self.ref)
        with patch(MAIL), patch(GRAPH_PRONTO, return_value=True), patch(CREA_EVENTO, return_value={"id": "ev-2"}):
            self.client.post(reverse("reception:annuncia_decidi", args=[r.pk]),
                             {"azione": "approva", "ora_inizio": "14:00", "ora_fine": "15:30", "sala": str(self.sala.pk)})
        pre = RichiestaAppuntamento.objects.get(pk=r.pk).preregistrazione
        self.assertEqual((pre.sala, pre.ora_fine, pre.outlook_event_id), (self.sala, time(15, 30), "ev-2"))


class ApiEliminaTests(Base):
    def test_api_disponibilita(self):
        self.visita()
        r = self.client.get(reverse("reception:api_sale"), {"data": self.domani.isoformat()})
        self.assertEqual(r.status_code, 200)
        blocchi = r.json()["sale"][0]["blocchi"]
        self.assertEqual(blocchi[0]["inizio"], "10:00")
        self.assertNotIn("Ospite Uno", blocchi[0]["titolo"])
        self.assertEqual(self.client.get(reverse("reception:api_sale"), {"data": "x"}).status_code, 400)

    def test_api_anonimo_json_401(self):
        self.client.logout()
        r = self.client.get(reverse("reception:api_sale"), {"data": self.domani.isoformat()})
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")

    def test_eliminando_l_invito_si_libera_la_sala(self):
        pre = self.visita()
        Preregistrazione.objects.filter(pk=pre.pk).update(outlook_event_id="ev-3", outlook_organizer_email="referente@example.local")
        with patch(GRAPH_PRONTO, return_value=True), patch("core.outlook_calendar.delete_event") as cancella:
            self.client.post(reverse("reception:preregistrazione_azione", args=[pre.pk]), {"azione": "elimina"})
        cancella.assert_called_once_with(target_email="referente@example.local", event_id="ev-3")
        self.assertFalse(Preregistrazione.objects.exists())


@override_settings(CHIOSCO_ALLOWED_IPS=["127.0.0.1"], RECEPTION_NATIVA=True)
class FotoReferenteChioscoTests(TestCase):
    def setUp(self):
        from anagrafica.models import DipendenteAnagraficaCivile

        self.ref = Referente.objects.create(nome="Prova", cognome="Foto", email="foto@example.local", dipendente_id=990001)
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=990001)
        DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=990001).update(foto="dipendenti/990001/foto_prova.jpg")
        self.url = reverse("chiosco:foto_referente", args=[self.ref.pk])

    def test_miniatura_solo_alle_postazioni_ammesse(self):
        with patch("anagrafica.views.dipendenti._miniatura_foto", return_value=b"jpeg-finto"):
            r = self.client.get(self.url)
            self.assertEqual((r.status_code, r["Content-Type"], r.content), (200, "image/jpeg", b"jpeg-finto"))
            self.assertEqual(self.client.get(self.url, REMOTE_ADDR="10.9.9.9").status_code, 404)
            with override_settings(RECEPTION_NATIVA=False):
                self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_referente_senza_foto_o_disattivo(self):
        altro = Referente.objects.create(nome="Senza", cognome="Foto", email="senza@example.local")
        self.assertEqual(self.client.get(reverse("chiosco:foto_referente", args=[altro.pk])).status_code, 404)
        Referente.objects.filter(pk=self.ref.pk).update(attivo=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_la_pagina_del_chiosco_porta_solo_la_versione_della_foto(self):
        from fornitori import chiosco

        dati = {r["id"]: r for r in chiosco.referenti()}
        self.assertTrue(dati[self.ref.pk]["foto"])
        self.assertNotIn("/", dati[self.ref.pk]["foto"])


class ConfigurazioneSaleTests(Base):
    url = property(lambda self: reverse("reception:sale"))

    def test_pagina_e_voce_di_menu(self):
        r = self.client.get(self.url)
        self.assertContains(r, "Sala Prova")
        self.assertContains(r, "Proponi negli inviti")

    def test_aggiungi_modifica_e_togli_dagli_inviti(self):
        self.client.post(self.url, {"nome": "Sala Nuova", "email": "nuova@example.local", "capienza": "12", "negli_inviti": "1"})
        nuova = MeetingRoom.objects.get(nome="Sala Nuova")
        self.assertTrue(SalaInviti.objects.filter(sala=nuova).exists())
        self.client.post(self.url, {"pk": str(nuova.pk), "nome": "Sala Nuova 2", "email": "", "capienza": ""})
        nuova.refresh_from_db()
        self.assertEqual((nuova.nome, nuova.email, nuova.capienza), ("Sala Nuova 2", "", None))
        self.assertFalse(SalaInviti.objects.filter(sala=nuova).exists())
        self.client.post(self.url, {"pk": str(self.sala.pk), "azione": "inviti", "negli_inviti": "0"})
        self.assertFalse(SalaInviti.objects.filter(sala=self.sala).exists())

    def test_nome_doppio_ed_email_non_valida(self):
        self.client.post(self.url, {"nome": "sala prova"})
        self.client.post(self.url, {"nome": "Altra", "email": "non-valida"})
        self.assertEqual(MeetingRoom.objects.count(), 1)
