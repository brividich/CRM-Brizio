from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImportPagesUITests(TestCase):
    """Le pagine import contratti/cedolini montano la subnav di modulo e
    dichiarano gli override dark mode (`body.theme-dark`) per gli stili locali."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser(
            username="import-ui", email="import-ui@example.com", password="pass12345",
        )
        self.client.force_login(self.user)

    def test_contratti_import_ha_subnav_e_dark(self):
        resp = self.client.get(reverse("anagrafica:contratti_import"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hrnav")  # subnav modulo anagrafica
        self.assertContains(resp, "body.theme-dark .ci-card")

    def test_cedolini_import_vive_in_ferie_e_permessi(self):
        # Da ottobre 2026 l'import cedolini è la sezione «Importazione» della pagina Ferie e permessi.
        resp = self.client.get(reverse("anagrafica:cedolini_import"))
        self.assertRedirects(resp, reverse("anagrafica:ratei_list") + "#importazione", fetch_redirect_response=False)
        resp = self.client.get(reverse("anagrafica:ratei_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hrnav")
        self.assertContains(resp, 'id="importazione"')
        self.assertContains(resp, "body.theme-dark .ci-card")
        self.assertContains(resp, f'action="{reverse("anagrafica:cedolini_import")}"')

    def test_retribuzioni_import_vive_in_cedolini(self):
        resp = self.client.get(reverse("anagrafica:retribuzioni_import"))
        self.assertRedirects(resp, reverse("anagrafica:retribuzioni_globale") + "#importazione",
                             fetch_redirect_response=False)
        resp = self.client.get(reverse("anagrafica:retribuzioni_globale"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="importazione"')
        self.assertContains(resp, "body.theme-dark .ri-card")
        self.assertContains(resp, f'action="{reverse("anagrafica:retribuzioni_import")}"')

    def test_import_senza_file_torna_alla_pagina_unita(self):
        resp = self.client.post(reverse("anagrafica:retribuzioni_import"), {})
        self.assertRedirects(resp, reverse("anagrafica:retribuzioni_globale") + "#importazione",
                             fetch_redirect_response=False)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DarkModeTableOverrideTests(TestCase):
    """Le pagine con tabelle segnalate illeggibili in dark dichiarano gli
    override `body.theme-dark` per le righe/celle con colori hardcodati."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser(
            username="dark-ui", email="dark-ui@example.com", password="pass12345",
        )
        self.client.force_login(self.user)

    def test_qualifiche_list_override_righe_scadenza(self):
        resp = self.client.get(reverse("anagrafica:qualifiche_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "body.theme-dark .fmd-scad-red")

    def test_organigramma_niente_link_inline_scuri(self):
        resp = self.client.get(reverse("anagrafica:organigramma"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "body.theme-dark .org-select")
