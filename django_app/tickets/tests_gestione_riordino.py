"""Pagina di gestione riordinata (24/11) e link della lista per chi gestisce un solo tipo."""

from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse

from tickets.models import StatoTicket, Ticket, TipoTicket
from tickets.tests_lavorazione import LavorazioneBase


class GestioneRiordinoTests(LavorazioneBase):
    def test_barra_unica_e_annulla_nel_menu(self):
        ticket = self._ticket()
        html = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk])).content.decode()
        self.assertIn('id="stato-dialog"', html)
        self.assertIn('class="tkt-pop tkt-altro"', html)
        self.assertIn('data-stato="ANNULLATO"', html)
        self.assertIn('id="meta-assegnato"', html)
        self.assertNotIn("Aggiorna stato", html)
        self.assertNotIn("Riepilogo ticket", html)
        self.assertIn("Chiudi pannello", html)

    def test_dati_di_chiusura_dopo_la_risoluzione(self):
        ticket = self._ticket(stato=StatoTicket.RISOLTO)
        html = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk])).content.decode()
        self.assertIn('id="an-save"', html)
        self.assertIn("Dati di chiusura", html)

    def test_copilota_solo_su_ticket_nuovi(self):
        ticket = self._ticket(stato=StatoTicket.IN_CARICO, assegnato_a="Tec Nico")
        html = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk])).content.decode()
        self.assertNotIn('id="copilota-card"', html)

    def test_rimuovi_asset_sempre_presente_nascosto_se_vuoto(self):
        ticket = self._ticket()
        html = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk])).content.decode()
        self.assertRegex(html, r'id="ag-clear"[^>]*hidden')
        ticket.asset_descrizione_libera = "Macchina sintetica"
        ticket.save(update_fields=["asset_descrizione_libera"])
        html = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk])).content.decode()
        self.assertNotRegex(html, r'id="ag-clear"[^>]*hidden')


class ListaLinkPerTipoGestitoTests(LavorazioneBase):
    def test_gestore_man_apre_il_proprio_ticket_it_nella_scheda(self):
        it = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="PC sintetico", descrizione="x", categoria="PC",
            richiedente_nome="Tec", richiedente_user=self.tecnico,
        )
        man = self._ticket(richiedente_user=self.tecnico)

        def gestisce(_request, tipo=None):
            return tipo in (None, TipoTicket.MAN)

        with patch("tickets.views._can_manage_tickets", side_effect=gestisce):
            html = self.client.get(reverse("tickets:dashboard")).content.decode()
        self.assertIn(reverse("tickets:detail", args=[it.pk]), html)
        self.assertNotIn(reverse("tickets:gestione_detail", args=[it.pk]), html)
        self.assertIn(reverse("tickets:gestione_detail", args=[man.pk]), html)
