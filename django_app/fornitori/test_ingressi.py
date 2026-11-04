"""Ingressi esterni (GuestPortal) collegati a ticket MAN e ordini di lavoro."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import Asset, WorkOrder
from fornitori import guestportal as gp
from fornitori import ingressi as ing
from fornitori.models import DittaGuestPortal, IngressoIntervento
from tickets.models import StatoTicket, Ticket, TicketIntervento, TipoTicket

GP_DB = {"GUESTPORTAL_DB_HOST": "db", "GUESTPORTAL_DB_NAME": "GuestManagement", "GUESTPORTAL_DB_USER": "hub_ro"}


def _accesso(visita_id=11, ingresso=datetime(2026, 11, 4, 8, 0), uscita=datetime(2026, 11, 4, 12, 0), **extra):
    dati = dict(
        visita_id=visita_id, stato="CHECKEDOUT", tipo="SUPPLIER", nome="Tecnico Esempio",
        azienda="Ditta Manutenzioni Srl", referente="Referente", motivo="Manutenzione pressa",
        badge="04", ingresso=ingresso, uscita=uscita, ditta_gp_id=5,
    )
    dati.update(extra)
    return gp.Accesso(**dati)


class BaseIngressi(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("gp.admin", "gp.admin@example.com", "pwd12345")
        self.client.force_login(self.admin)
        self.fornitore = Fornitore.objects.create(ragione_sociale="Ditta Manutenzioni Srl")
        self.ticket = Ticket.objects.create(
            tipo=TipoTicket.MAN, titolo="Pressa ferma", descrizione="x", categoria="ALTRO",
            richiedente_nome="Richiedente", richiedente_user=self.admin, delegato_fornitore=self.fornitore,
        )
        asset = Asset.objects.create(asset_tag="PRS-01", name="Pressa di prova")
        self.odl = WorkOrder.objects.create(
            asset=asset, title="Revisione pressa", supplier=self.fornitore,
            execution_mode=WorkOrder.EXECUTION_EXTERNAL,
        )


class CollegamentoTests(BaseIngressi):
    def test_collega_salva_fotografia_ingresso(self):
        DittaGuestPortal.objects.create(ditta_gp_id=5, ditta_gp_nome="Ditta GP", fornitore=self.fornitore)
        iv = ing.intervento(ing.TIPO_TICKET, self.ticket.pk)
        with patch.object(gp, "visita", return_value=_accesso()):
            link = ing.collega(iv, 11, utente=self.admin, modo="PROPOSTA")
        link.refresh_from_db()
        self.assertEqual((link.visita_gp_id, link.tecnico_nome, link.badge, link.modo), (11, "Tecnico Esempio", "04", "PROPOSTA"))
        self.assertEqual(link.fornitore, self.fornitore)
        self.assertEqual(link.durata_minuti, 240)
        self.assertTrue(timezone.is_aware(link.ingresso))

    def test_stesso_ingresso_non_si_collega_due_volte(self):
        iv = ing.intervento(ing.TIPO_ODL, self.odl.pk)
        with patch.object(gp, "visita", return_value=_accesso()):
            ing.collega(iv, 11, utente=self.admin, modo="MANUALE")
            with self.assertRaises(ing.CollegamentoNonValido):
                ing.collega(iv, 11, utente=self.admin, modo="MANUALE")
        self.assertEqual(IngressoIntervento.objects.filter(work_order=self.odl).count(), 1)

    def test_intervento_chiuso_rifiuta(self):
        self.ticket.stato = StatoTicket.CHIUSO
        self.ticket.save()
        iv = ing.intervento(ing.TIPO_TICKET, self.ticket.pk)
        with patch.object(gp, "visita", return_value=_accesso()), self.assertRaises(ing.CollegamentoNonValido):
            ing.collega(iv, 11, utente=self.admin, modo="PROPOSTA")

    def test_visita_cancellata_o_anonimizzata_rifiuta(self):
        iv = ing.intervento(ing.TIPO_TICKET, self.ticket.pk)
        with patch.object(gp, "visita", return_value=None), self.assertRaises(ing.CollegamentoNonValido):
            ing.collega(iv, 11, utente=self.admin, modo="PROPOSTA")
        with patch.object(gp, "visita", return_value=_accesso(nome="Ospite anonimizzato")), \
                self.assertRaises(ing.CollegamentoNonValido):
            ing.collega(iv, 11, utente=self.admin, modo="PROPOSTA")

    def test_proposte_usano_abbinamento_e_ragione_sociale_ed_escludono_collegati(self):
        DittaGuestPortal.objects.create(ditta_gp_id=5, ditta_gp_nome="Ditta GP", fornitore=self.fornitore)
        iv = ing.intervento(ing.TIPO_TICKET, self.ticket.pk)
        with patch.object(gp, "visita", return_value=_accesso(visita_id=11)):
            ing.collega(iv, 11, utente=self.admin, modo="PROPOSTA")
        with patch.object(gp, "ingressi_ditta", return_value=[_accesso(visita_id=11), _accesso(visita_id=12)]) as m:
            righe = ing.proposte(iv)
        self.assertEqual([a.visita_id for a in righe], [12])
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["ditte_gp"], [5])
        self.assertEqual(kwargs["nomi"], ["Ditta Manutenzioni Srl"])
        self.assertLessEqual((kwargs["al"] - kwargs["dal"]).days, ing.FINESTRA_MAX_GIORNI)

    def test_senza_ditta_delegata_nessuna_proposta(self):
        self.ticket.delegato_fornitore = None
        self.ticket.save()
        with patch.object(gp, "ingressi_ditta") as m:
            self.assertEqual(ing.proposte(ing.intervento(ing.TIPO_TICKET, self.ticket.pk)), [])
        m.assert_not_called()

    def test_ore_dichiarate_oltre_la_presenza_da_controllare(self):
        iv = ing.intervento(ing.TIPO_TICKET, self.ticket.pk)
        with patch.object(gp, "visita", return_value=_accesso()):  # 4 h in azienda
            ing.collega(iv, 11, utente=self.admin, modo="PROPOSTA")
        TicketIntervento.objects.create(ticket=self.ticket, tecnico_nome="Tecnico", data_inizio=timezone.now(), ore_lavorate=6)
        confronto = ing.confronto_ore(iv, list(iv.collegamenti()))
        self.assertEqual((confronto.presenza_minuti, confronto.dichiarate_minuti), (240, 360))
        self.assertTrue(confronto.da_controllare)

    def test_ore_entro_tolleranza_ok(self):
        iv = ing.intervento(ing.TIPO_TICKET, self.ticket.pk)
        with patch.object(gp, "visita", return_value=_accesso()):
            ing.collega(iv, 11, utente=self.admin, modo="PROPOSTA")
        TicketIntervento.objects.create(ticket=self.ticket, tecnico_nome="Tecnico", data_inizio=timezone.now(), ore_lavorate=4.2)
        self.assertFalse(ing.confronto_ore(iv, list(iv.collegamenti())).da_controllare)


@override_settings(**GP_DB)
class VistePresenzeTests(BaseIngressi):
    def setUp(self):
        super().setUp()
        # Gestore dei ticket: la regola vera (tickets._ticket_access_flags) è testata in tickets.
        patcher = patch("tickets.services.accesso.utente_puo_gestire_ticket", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
    def test_riquadro_ticket_mostra_proposte_e_collega(self):
        url = reverse("fornitori:presenze_intervento", args=["ticket", self.ticket.pk])
        with patch.object(gp, "ingressi_ditta", return_value=[_accesso()]):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ingressi della ditta da collegare")
        self.assertContains(resp, "Tecnico Esempio")

        with patch.object(gp, "visita", return_value=_accesso()), patch.object(gp, "ingressi_ditta", return_value=[_accesso()]), \
                patch("fornitori.views.log_action"):
            resp = self.client.post(reverse("fornitori:presenze_collega", args=["ticket", self.ticket.pk]),
                                    {"visita_id": "11", "modo": "PROPOSTA"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "collegato")
        self.assertEqual(IngressoIntervento.objects.filter(ticket=self.ticket).count(), 1)
        self.assertNotContains(resp, "Ingressi della ditta da collegare")  # già collegato, non più proposto

    def test_scollega(self):
        link = IngressoIntervento.objects.create(visita_gp_id=11, work_order=self.odl, ingresso=timezone.now())
        with patch.object(gp, "ingressi_ditta", return_value=[]), patch.object(gp, "visita", return_value=None), \
                patch("fornitori.views.log_action"):
            resp = self.client.post(reverse("fornitori:presenze_scollega", args=[link.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(IngressoIntervento.objects.filter(pk=link.pk).exists())

    def test_utente_senza_permesso_ticket_403(self):
        from core.models import UserOnboarding

        semplice = get_user_model().objects.create_user("semplice", "s@example.com", "pwd12345")
        UserOnboarding.objects.create(user=semplice, completed=True, completed_at=timezone.now())
        self.client.force_login(semplice)
        with patch("tickets.services.accesso.utente_puo_gestire_ticket", return_value=False):
            resp = self.client.post(reverse("fornitori:presenze_collega", args=["ticket", self.ticket.pk]), {"visita_id": "11"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(IngressoIntervento.objects.exists())

    def test_tipo_sconosciuto_404(self):
        self.assertEqual(self.client.get("/fornitori/presenze/altro/1/").status_code, 404)

    def test_gp_non_raggiungibile_mostra_collegati(self):
        IngressoIntervento.objects.create(visita_gp_id=11, ticket=self.ticket, tecnico_nome="Tecnico Salvato",
                                          ingresso=timezone.now() - timedelta(hours=2), uscita=timezone.now())
        with patch.object(gp, "ingressi_ditta", side_effect=gp.GuestPortalNonRaggiungibile("down")):
            resp = self.client.get(reverse("fornitori:presenze_intervento", args=["ticket", self.ticket.pk]))
        self.assertContains(resp, "Tecnico Salvato")
        self.assertContains(resp, "non risponde")

    def test_ditte_abbinamento_e_rimozione(self):
        url = reverse("fornitori:guestportal_ditte")
        with patch.object(gp, "ditte_guestportal", return_value=[(5, "DITTA MANUTENZIONI SRL")]):
            resp = self.client.get(url)
        self.assertContains(resp, "Proposta per nome uguale")
        with patch("fornitori.views.log_action"):
            self.client.post(url, {"ditta_gp_id": "5", "ditta_gp_nome": "DITTA MANUTENZIONI SRL", "fornitore_id": str(self.fornitore.pk)})
        self.assertEqual(DittaGuestPortal.objects.get(ditta_gp_id=5).fornitore, self.fornitore)
        with patch("fornitori.views.log_action"):
            self.client.post(url, {"ditta_gp_id": "5", "ditta_gp_nome": "DITTA MANUTENZIONI SRL", "fornitore_id": ""})
        self.assertFalse(DittaGuestPortal.objects.exists())

    def test_accessi_esterni_mostra_incaricato_per(self):
        IngressoIntervento.objects.create(visita_gp_id=11, ticket=self.ticket, ingresso=timezone.now())
        with patch.object(gp, "presenti_ora", return_value=[_accesso(uscita=None, stato="CHECKEDIN")]), \
                patch.object(gp, "storico", return_value=([], False)):
            resp = self.client.get(reverse("fornitori:accessi_esterni"))
        self.assertContains(resp, "Incaricato per")
        self.assertContains(resp, reverse("tickets:gestione_detail", args=[self.ticket.pk]))

    def test_pagine_ticket_e_odl_includono_il_riquadro(self):
        from core import middleware

        for nome in ("fornitori:presenze_intervento", "fornitori:presenze_collega", "fornitori:presenze_scollega"):
            self.assertIn(nome, middleware._ACL_SHARED_ROUTE_NAMES)
        resp = self.client.get(reverse("assets:wo_view", args=[self.odl.pk]))
        self.assertContains(resp, reverse("fornitori:presenze_intervento", args=["odl", self.odl.pk]))
