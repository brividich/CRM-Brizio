"""Ruolo con «vedere» solo sui ticket manutenzione: il ticket IT aperto da sé
deve restare visibile in elenco (prima spariva: insieme vuoto per ticket_it)."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from tickets import views
from tickets.models import Ticket, TipoTicket


class PropriSempreVisibiliTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tk_prop", email="prop@example.com")
        other = User.objects.create_user(username="tk_altro", email="altro@example.com")
        self.mio_it = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Mio IT", descrizione="x", categoria="ALTRO",
            richiedente_nome="Mio", richiedente_user=self.user,
        )
        self.altrui_it = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Altrui IT", descrizione="y", categoria="ALTRO",
            richiedente_nome="Altro", richiedente_user=other,
        )
        self.request = RequestFactory().get("/tickets/")
        self.request.user = self.user

    def test_ticket_it_proprio_visibile_senza_vedere_su_ticket_it(self):
        def visibili(_request, chiave, _azione):
            return frozenset({42}) if chiave == "ticket_manutenzione" else frozenset()

        with patch("tickets.views._legacy_identity", return_value=("", "", None)), \
                patch("tickets.views.utenti_visibili", side_effect=visibili):
            ids = set(Ticket.objects.filter(views.filtro_ticket_visibili(self.request)).values_list("pk", flat=True))
        self.assertIn(self.mio_it.pk, ids)
        self.assertNotIn(self.altrui_it.pk, ids)
