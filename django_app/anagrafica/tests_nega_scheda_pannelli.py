"""Pannelli e pagine di una sola persona: rispettano l'ambito del ruolo come la scheda."""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase

from anagrafica.views import dipendenti


class NegaSchedaTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/anagrafica/dipendenti/2/libretto-sanitario/")
        self.request.user = get_user_model().objects.create_user(username="caporeparto_test", password="x")
        self.request.session = SessionStore()

    def test_sistema_ruoli_spento_non_decide(self):
        with mock.patch.object(dipendenti._helpers, "_ruoli_attivi", return_value=False):
            self.assertIsNone(dipendenti._nega_scheda(self.request, 2))

    def test_scheda_fuori_ambito_negata(self):
        with mock.patch.object(dipendenti._helpers, "_ruoli_attivi", return_value=True), \
                mock.patch.object(dipendenti, "_schede_visibili", return_value={1}):
            risposta = dipendenti._nega_scheda(self.request, 2)
        self.assertIsNotNone(risposta)
        self.assertEqual(risposta.status_code, 403)

    def test_scheda_nel_team_o_ambito_tutti_ammessa(self):
        with mock.patch.object(dipendenti._helpers, "_ruoli_attivi", return_value=True):
            with mock.patch.object(dipendenti, "_schede_visibili", return_value={1, 2}):
                self.assertIsNone(dipendenti._nega_scheda(self.request, 2))
            with mock.patch.object(dipendenti, "_schede_visibili", return_value=None):
                self.assertIsNone(dipendenti._nega_scheda(self.request, 2))
