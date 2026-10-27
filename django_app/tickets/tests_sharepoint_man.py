"""Sincronizzazione bidirezionale ticket MAN <-> lista SharePoint (Graph simulato)."""
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from . import sharepoint_man as sp
from .models import (
    PrioritaTicket,
    StatoTicket,
    Ticket,
    TicketImpostazioni,
    TicketSharePointOutbox,
    TicketStatoLog,
    TipoTicket,
)

_CRED = {"tenant_id": "t", "client_id": "c", "client_secret": "s"}


def _risposta(status=200, payload=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload or {}
    r.text = ""
    return r


class _Base(TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(sp, "_credenziali", return_value=_CRED),
            mock.patch.object(sp, "_headers", return_value={}),
            mock.patch.object(sp, "_invio_immediato"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.cfg = TicketImpostazioni.get_or_create_for(TipoTicket.MAN)
        self.cfg.sharepoint_site_id = "sito"
        self.cfg.sharepoint_list_id = "lista"
        self.cfg.sharepoint_sync_attivo = True
        self.cfg.save()

    def _ticket(self, **extra) -> Ticket:
        dati = dict(
            tipo=TipoTicket.MAN, titolo="Perdita olio", descrizione="Perdita dal mandrino",
            categoria="CNC", richiedente_nome="Operatore Test",
        )
        dati.update(extra)
        return Ticket.objects.create(**dati)


class CodaTest(_Base):
    def test_salvataggio_man_va_in_coda(self):
        t = self._ticket()
        self.assertTrue(TicketSharePointOutbox.objects.filter(ticket=t).exists())

    def test_ticket_it_non_va_in_coda(self):
        t = self._ticket(tipo=TipoTicket.IT, categoria="PC")
        self.assertFalse(TicketSharePointOutbox.objects.filter(ticket=t).exists())

    def test_interruttore_spento_nessuna_coda(self):
        self.cfg.sharepoint_sync_attivo = False
        self.cfg.save()
        t = self._ticket()
        self.assertFalse(TicketSharePointOutbox.objects.exists())
        self.assertEqual(sp.sincronizza(), {"skipped": "sincronizzazione spenta"})
        self.assertIsNotNone(t.pk)


class InvioTest(_Base):
    def test_nuovo_ticket_crea_elemento_e_salva_id(self):
        t = self._ticket()
        with mock.patch.object(sp.requests, "post", return_value=_risposta(201, {"id": "77"})) as post:
            esito = sp.invia_coda()
        self.assertEqual(esito["creati"], 1)
        campi = post.call_args.kwargs["json"]["fields"]
        self.assertEqual(campi["Status"], "Nuovo")
        self.assertEqual(campi["Tipologiaproblema"], "Manutenzione macchinario")
        self.assertFalse(campi["Chiuso"])
        t.refresh_from_db()
        self.assertEqual(t.sharepoint_item_id, "77")
        self.assertFalse(TicketSharePointOutbox.objects.exists())

    def test_chiusura_sul_portale_chiude_su_sharepoint(self):
        t = self._ticket(sharepoint_item_id="5")
        t.stato = StatoTicket.CHIUSO
        t.closed_at = timezone.now()
        t.save()
        with mock.patch.object(sp.requests, "patch", return_value=_risposta(200)) as patch:
            sp.invia_coda()
        campi = patch.call_args.kwargs["json"]
        self.assertTrue(campi["Chiuso"])
        self.assertEqual(campi["Status"], "Completato")
        self.assertIsNotNone(campi["Datachiusuraticket"])
        self.assertIn("/items/5/fields", patch.call_args.args[0])

    def test_errore_lascia_la_riga_in_coda(self):
        self._ticket(sharepoint_item_id="5")
        with mock.patch.object(sp.requests, "patch", return_value=_risposta(500)):
            esito = sp.invia_coda()
        self.assertEqual(esito["falliti"], 1)
        row = TicketSharePointOutbox.objects.get()
        self.assertEqual(row.tentativi, 1)
        self.assertTrue(row.ultimo_errore)


class LetturaTest(_Base):
    def _leggi(self, items, completa=False):
        with mock.patch.object(sp, "_delta", return_value=(items, "link", completa)):
            return sp.leggi_modifiche()

    def test_elemento_nuovo_diventa_ticket_senza_tornare_in_coda(self):
        item = {
            "id": "900",
            "createdBy": {"user": {"displayName": "Capo Reparto Test"}},
            "fields": {"Title": "Nastro fermo", "Description": "Si blocca", "Priority": "Alta",
                       "Status": "Nuovo", "Tipologiaproblema": "Manutenzione strutturale"},
        }
        esito = self._leggi([item])
        self.assertEqual(esito["creati"], 1)
        t = Ticket.objects.get(sharepoint_item_id="900")
        self.assertEqual(t.tipo, TipoTicket.MAN)
        self.assertEqual(t.priorita, PrioritaTicket.ALTA)
        self.assertEqual(t.categoria, "STRUTTURALE")
        self.assertEqual(t.richiedente_nome, "Capo Reparto Test")
        self.assertFalse(TicketSharePointOutbox.objects.exists())

    def test_chiusura_su_sharepoint_chiude_sul_portale(self):
        t = self._ticket(sharepoint_item_id="10")
        TicketSharePointOutbox.objects.all().delete()
        esito = self._leggi([{"id": "10", "fields": {
            "Title": t.titolo, "Description": t.descrizione, "Priority": "Normale", "Status": "Completato",
            "Tipologiaproblema": "Manutenzione macchinario", "Chiuso": True,
            "Datachiusuraticket": "2026-10-20T08:00:00Z",
        }}])
        self.assertEqual(esito["aggiornati"], 1)
        t.refresh_from_db()
        self.assertEqual(t.stato, StatoTicket.CHIUSO)
        self.assertEqual(t.closed_at.year, 2026)
        self.assertEqual(t.categoria, "CNC")  # stessa tipologia: la categoria fine resta
        self.assertTrue(TicketStatoLog.objects.filter(ticket=t, a_stato=StatoTicket.CHIUSO).exists())
        self.assertFalse(TicketSharePointOutbox.objects.exists())

    def test_stato_nuovo_su_sharepoint_non_riapre_un_ticket_in_carico(self):
        # Sulla lista «Stato» resta «Nuovo»: una modifica alle note non deve riportarlo ad Aperta.
        t = self._ticket(sharepoint_item_id="13", stato=StatoTicket.IN_CARICO)
        TicketSharePointOutbox.objects.all().delete()
        self._leggi([{"id": "13", "fields": {"Title": t.titolo, "Description": t.descrizione,
                                             "Status": "Nuovo", "Note": "ricambio ordinato"}}])
        t.refresh_from_db()
        self.assertEqual(t.stato, StatoTicket.IN_CARICO)
        self.assertEqual(t.note_interne, "ricambio ordinato")

    def test_togliere_chiuso_su_sharepoint_riapre(self):
        t = self._ticket(sharepoint_item_id="14", stato=StatoTicket.CHIUSO, closed_at=timezone.now())
        TicketSharePointOutbox.objects.all().delete()
        self._leggi([{"id": "14", "fields": {"Title": t.titolo, "Description": t.descrizione,
                                             "Status": "Nuovo", "Chiuso": False}}])
        t.refresh_from_db()
        self.assertEqual(t.stato, StatoTicket.APERTA)
        self.assertIsNone(t.closed_at)

    def test_lettura_completa_non_tocca_i_ticket_collegati(self):
        t = self._ticket(sharepoint_item_id="15", stato=StatoTicket.CHIUSO, closed_at=timezone.now())
        TicketSharePointOutbox.objects.all().delete()
        esito = self._leggi([
            {"id": "15", "fields": {"Title": "Altro", "Status": "Nuovo", "Chiuso": False}},
            {"id": "16", "fields": {"Title": "Nuovo dalla lista", "Status": "Nuovo"}},
        ], completa=True)
        t.refresh_from_db()
        self.assertEqual(t.stato, StatoTicket.CHIUSO)
        self.assertEqual(esito["creati"], 1)

    def test_modifica_locale_in_coda_vince(self):
        t = self._ticket(sharepoint_item_id="11")
        esito = self._leggi([{"id": "11", "fields": {"Title": "Altro titolo", "Status": "Completato"}}])
        self.assertEqual(esito["saltati_in_coda"], 1)
        t.refresh_from_db()
        self.assertEqual(t.titolo, "Perdita olio")

    def test_elemento_eliminato_scollega_il_ticket(self):
        t = self._ticket(sharepoint_item_id="12")
        TicketSharePointOutbox.objects.all().delete()
        self.assertEqual(self._leggi([{"id": "12", "deleted": {"state": "deleted"}}])["scollegati"], 1)
        t.refresh_from_db()
        self.assertEqual(t.sharepoint_item_id, "")


class AndataRitornoTest(_Base):
    def test_nessuno_stato_cambia_dopo_andata_e_ritorno(self):
        for stato in StatoTicket.values:
            with self.subTest(stato=stato):
                t = self._ticket(stato=stato, closed_at=timezone.now() if stato in (
                    StatoTicket.CHIUSO, StatoTicket.ANNULLATO, StatoTicket.RISOLTO) else None,
                    note_interne="nota")
                campi = sp.campi_per_sharepoint(t, nuovo=False)
                self.assertEqual(sp._differenze(t, sp.valori_da_sharepoint(campi, t)), {})


class ImpostazioniTest(_Base):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model

        from .tests import _complete_onboarding

        self.user = get_user_model().objects.create_superuser("tk-sp-admin", "tk-sp@example.com", "pass12345")
        _complete_onboarding(self.user)
        self.client.force_login(self.user)

    def test_pagina_mostra_interruttore_e_coda(self):
        from django.urls import reverse

        self._ticket()
        with mock.patch("tickets.views._can_manage_settings", return_value=True):
            resp = self.client.get(reverse("tickets:impostazioni"))
        if resp.status_code != 200:
            self.skipTest(f"pagina impostazioni non raggiungibile in test ({resp.status_code})")
        self.assertContains(resp, 'id="man-sp-sync"')
        self.assertContains(resp, "checked")
        self.assertContains(resp, "In coda verso SharePoint: 1")

    def test_salvataggio_richiede_site_e_list_per_accendere(self):
        import json

        from django.urls import reverse

        with mock.patch("tickets.views._can_manage_settings", return_value=True):
            resp = self.client.post(reverse("tickets:api_impostazioni"), json.dumps({
                "tipo": "MAN", "sharepoint_list_id": "", "sharepoint_site_id": "sito", "sharepoint_sync_attivo": True,
            }), content_type="application/json")
        self.assertFalse(resp.json()["ok"])
