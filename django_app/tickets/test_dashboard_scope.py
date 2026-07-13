from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from tickets import views
from tickets.models import Ticket, TipoTicket


class TicketDashboardScopeTests(TestCase):
    """SEC: la dashboard ticket esponeva numero/titolo/categoria/asset e flag
    "Sicurezza" di TUTTI i ticket a qualsiasi utente autenticato. Chi non è
    gestore/admin deve vedere solo i ticket di cui è richiedente."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tk_user", email="tk@example.com")
        self.other = User.objects.create_user(username="tk_other", email="other@example.com")
        self.own = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Mio ticket", descrizione="x",
            categoria="ALTRO", richiedente_nome="Mio", richiedente_user=self.user,
        )
        self.foreign = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="Ticket altrui", descrizione="y",
            categoria="ALTRO", richiedente_nome="Altro", richiedente_user=self.other,
        )
        self.factory = RequestFactory()

    def _run_dashboard(self, as_gestore=False):
        req = self.factory.get("/tickets/")
        req.user = self.user
        captured = {}

        def fake_render(request, template, ctx):
            captured["ctx"] = ctx
            return HttpResponse("ok")

        with patch("tickets.views._legacy_identity", return_value=("", "", None)), \
             patch("tickets.views.get_legacy_user", return_value=None), \
             patch("tickets.views.is_legacy_admin", return_value=False), \
             patch("tickets.views._can_manage_tickets", return_value=as_gestore), \
             patch("tickets.views._can_open_tickets", return_value=False), \
             patch("tickets.views.render", side_effect=fake_render):
            views.ticket_dashboard(req)
        return captured["ctx"]

    def test_non_gestore_sees_only_own_tickets(self):
        ctx = self._run_dashboard(as_gestore=False)
        tickets = list(ctx["tickets"])
        self.assertIn(self.own, tickets)
        self.assertNotIn(self.foreign, tickets)
        # I KPI sono coerenti con lo scope: 1 sola aperta (la propria)
        self.assertEqual(ctx["n_aperte"], 1)

    def test_gestore_sees_all_tickets(self):
        ctx = self._run_dashboard(as_gestore=True)
        tickets = list(ctx["tickets"])
        self.assertIn(self.own, tickets)
        self.assertIn(self.foreign, tickets)
        self.assertEqual(ctx["n_aperte"], 2)
