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

    def _run_dashboard(self, as_gestore=False, sezione="miei"):
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
            views.ticket_dashboard(req, sezione=sezione)
        return captured["ctx"]

    def test_non_gestore_sees_only_own_tickets(self):
        ctx = self._run_dashboard(as_gestore=False)
        tickets = list(ctx["tickets"])
        self.assertIn(self.own, tickets)
        self.assertNotIn(self.foreign, tickets)
        # I KPI sono coerenti con lo scope: 1 sola aperta (la propria)
        self.assertEqual(ctx["n_aperte"], 1)

    def test_gestore_sees_all_tickets_in_sezione_ticket(self):
        ctx = self._run_dashboard(as_gestore=True, sezione="tutti")
        tickets = list(ctx["tickets"])
        self.assertIn(self.own, tickets)
        self.assertIn(self.foreign, tickets)
        self.assertEqual(ctx["n_aperte"], 2)

    def test_i_miei_ticket_sono_solo_i_propri_anche_per_il_gestore(self):
        ctx = self._run_dashboard(as_gestore=True, sezione="miei")
        tickets = list(ctx["tickets"])
        self.assertIn(self.own, tickets)
        self.assertNotIn(self.foreign, tickets)
        self.assertEqual(ctx["sezione"], "miei")


class SezioneTicketCarTests(TestCase):
    """Un CAR con «vedere = Tutti» vede tutti i ticket nella sezione «Ticket», ma
    «I miei ticket» resta solo suo e sui ticket altrui non puo' commentare."""

    def setUp(self):
        from tickets.tests import _complete_onboarding

        User = get_user_model()
        self.car = User.objects.create_user(username="tk_car", email="car@example.com", password="x")
        self.altro = User.objects.create_user(username="tk_altro", email="altro@example.com")
        _complete_onboarding(self.car)
        self.mio = Ticket.objects.create(
            tipo=TipoTicket.MAN, titolo="Mio del CAR", descrizione="x",
            categoria="ALTRO", richiedente_nome="Car", richiedente_user=self.car,
        )
        self.altrui = Ticket.objects.create(
            tipo=TipoTicket.MAN, titolo="Di un operatore", descrizione="y",
            categoria="ALTRO", richiedente_nome="Altro", richiedente_user=self.altro,
        )

    def _decisione(self, ambito):
        from types import SimpleNamespace

        return lambda request, chiave, azione: SimpleNamespace(consentito=True, ambito=ambito)

    def test_puo_vedere_altri_ticket_secondo_l_ambito(self):
        req = RequestFactory().get("/tickets/elenco/")
        req.user = self.car
        with patch("tickets.views.sistema_ruoli_attivo", return_value=True):
            with patch("tickets.views.decisione", side_effect=self._decisione("tutti")):
                self.assertTrue(views.puo_vedere_altri_ticket(req))
            with patch("tickets.views.decisione", side_effect=self._decisione("propri")):
                self.assertFalse(views.puo_vedere_altri_ticket(req))

    def test_elenco_rimanda_a_i_miei_ticket_chi_vede_solo_i_propri(self):
        req = RequestFactory().get("/tickets/elenco/")
        req.user = self.car
        with patch("tickets.views.puo_vedere_altri_ticket", return_value=False):
            risposta = views.ticket_elenco(req)
        self.assertEqual(risposta.status_code, 302)
        self.assertTrue(risposta.url.endswith("/tickets/"))

    def test_dettaglio_altrui_in_sola_lettura(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore

        req = RequestFactory().get(f"/tickets/{self.altrui.pk}/")
        req.user = self.car
        req.session = SessionStore()
        req._messages = FallbackStorage(req)
        flags = {"name": "", "email": "", "legacy_id": None, "is_admin": False,
                 "is_gestore": False, "is_richiedente": False, "can_view": True}
        with patch("tickets.views._ticket_access_flags", return_value=flags):
            risposta = views.ticket_detail(req, self.altrui.pk)
        self.assertEqual(risposta.status_code, 200)
        html = risposta.content.decode()
        self.assertNotIn('id="commento-testo"', html)
        self.assertIn("sola lettura", html)
