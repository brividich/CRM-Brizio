"""Integrazione remediation formazione (26/11/2026 sera): pulsante «Ricalcola scadenze». Dati sintetici."""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class RicalcolaScadenzeTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.ricalcola", "hr@example.invalid", "pwd12345")
        self.client.force_login(self.admin)

    def test_pulsante_e_ricalcolo(self):
        r = self.client.get(reverse("anagrafica:formazione_scadenzario"))
        self.assertContains(r, "Ricalcola scadenze")
        esito = {"formazione": {"persone": 3, "create": 2, "aggiornate": 1, "cancellate": 0}, "visite": {}}
        with mock.patch("anagrafica.services.scadenze.ricalcola_tutto", return_value=esito) as m:
            r = self.client.post(reverse("anagrafica:formazione_scadenze_ricalcola"), {"next": "/anagrafica/formazione/scadenzario/?x=1"})
        m.assert_called_once()
        self.assertRedirects(r, "/anagrafica/formazione/scadenzario/?x=1", fetch_redirect_response=False)

    def test_solo_post_e_next_esterno_ignorato(self):
        self.assertEqual(self.client.get(reverse("anagrafica:formazione_scadenze_ricalcola")).status_code, 405)
        with mock.patch("anagrafica.services.scadenze.ricalcola_tutto", return_value={}):
            r = self.client.post(reverse("anagrafica:formazione_scadenze_ricalcola"), {"next": "//evil.example"})
        self.assertRedirects(r, reverse("anagrafica:formazione_scadenzario"), fetch_redirect_response=False)

    def test_chi_non_modifica_non_ricalcola(self):
        u = get_user_model().objects.create_user("lettore", "l@example.invalid", "pwd12345")
        self.client.force_login(u)
        with mock.patch("anagrafica.services.scadenze.ricalcola_tutto") as m:
            self.client.post(reverse("anagrafica:formazione_scadenze_ricalcola"))
        m.assert_not_called()
