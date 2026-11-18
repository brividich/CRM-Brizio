"""Tessere KPI di «I miei ticket»: ogni tessera apre la lista filtrata che conta lo stesso numero."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from tickets import views
from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket


class TicketDashboardKpiLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tk_kpi", email="tkkpi@example.com")
        base = {"tipo": TipoTicket.IT, "descrizione": "x", "categoria": "ALTRO", "richiedente_nome": "Io",
                "richiedente_user": self.user}
        Ticket.objects.create(titolo="Urgente aperto", priorita=PrioritaTicket.URGENTE, stato=StatoTicket.APERTA, **base)
        Ticket.objects.create(titolo="Urgente in carico", priorita=PrioritaTicket.URGENTE, stato=StatoTicket.IN_CARICO, **base)
        Ticket.objects.create(titolo="Urgente in attesa", priorita=PrioritaTicket.URGENTE, stato=StatoTicket.IN_ATTESA, **base)
        Ticket.objects.create(titolo="Media aperto", priorita=PrioritaTicket.MEDIA, stato=StatoTicket.APERTA, **base)
        self.factory = RequestFactory()

    def _dashboard(self, query: dict | None = None):
        req = self.factory.get("/tickets/", query or {})
        req.user = self.user
        captured = {}

        def fake_render(request, template, ctx):
            captured["ctx"] = ctx
            return HttpResponse("ok")

        with patch("tickets.views._legacy_identity", return_value=("", "", None)), \
             patch("tickets.views.get_legacy_user", return_value=None), \
             patch("tickets.views.is_legacy_admin", return_value=False), \
             patch("tickets.views._can_manage_tickets", return_value=False), \
             patch("tickets.views._can_open_tickets", return_value=False), \
             patch("tickets.views.render", side_effect=fake_render):
            views.ticket_dashboard(req, sezione="miei")
        return captured["ctx"]

    def test_filtri_delle_tessere_contano_lo_stesso_numero(self):
        ctx = self._dashboard()
        self.assertEqual(ctx["n_urgenti"], 2)
        self.assertEqual(self._dashboard({"priorita": "URGENTE", "attivi": "1"})["tickets"].count(), ctx["n_urgenti"])
        self.assertEqual(self._dashboard({"stato": "APERTA"})["tickets"].count(), ctx["n_aperte"])
        self.assertEqual(self._dashboard({"stato": "IN_CARICO"})["tickets"].count(), ctx["n_in_carico"])

    def test_tessere_sono_link(self):
        ctx = self._dashboard()
        html = render_to_string("tickets/pages/dashboard.html", {**ctx, "user": self.user})
        self.assertIn(f'href="{reverse("tickets:dashboard")}?priorita=URGENTE&amp;attivi=1#tkt-elenco"', html)
        self.assertIn("kpi-link", html)
        self.assertIn('id="tkt-elenco"', html)
