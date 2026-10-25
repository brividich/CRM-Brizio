"""Finestra di conferma del portale al posto di confirm() e schede unite della scheda dipendente.

Dati sintetici su domini ``example.invalid``.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente

from .tests import _ensure_anagrafica_table

User = get_user_model()
TEMPLATE_ANAGRAFICA = Path(__file__).resolve().parent / "templates" / "anagrafica"


class NienteConfirmDelBrowserTests(TestCase):
    def test_template_anagrafica_senza_confirm_nativo(self):
        """Le conferme passano da data-hub-confirm / hubConfirm(): mai la finestra del browser."""
        nativo = re.compile(r"(?<![\w.])(?:window\.)?confirm\(")
        trovati = [
            f"{f.relative_to(TEMPLATE_ANAGRAFICA)}:{n}"
            for f in TEMPLATE_ANAGRAFICA.rglob("*.html")
            for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
            if nativo.search(riga)
        ]
        self.assertEqual(trovati, [])

    def test_testi_di_conferma_senza_escapejs(self):
        """Dentro un attributo basta l'autoescape: |escapejs mostrerebbe \\u0027 a video."""
        attr = re.compile(r'data-hub-confirm="[^"]*\|escapejs')
        for f in TEMPLATE_ANAGRAFICA.rglob("*.html"):
            self.assertIsNone(attr.search(f.read_text(encoding="utf-8")), str(f))


@override_settings(LEGACY_AUTH_ENABLED=False)
class SchedaDipendenteSchedeUniteTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
        self.admin = User.objects.create_superuser("conf_admin", "conf_admin@example.invalid", "x")
        self.client.force_login(self.admin)
        self.dip = AnagraficaDipendente.objects.create(nome="Maria", cognome="D'Amico", aliasusername="m.damico",
                                                       email_notifica="m.damico@example.invalid")

    def test_nove_schede_e_vecchi_nomi_reindirizzati(self):
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.dip.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        barra = html.split('id="dp-tabbar"', 1)[1].split("</div>", 1)[0]
        self.assertEqual(
            re.findall(r'data-tab-target="([a-z]+)"', barra),
            ["riepilogo", "anagrafica", "ruolo", "contratto", "assenze", "formazione", "visite", "documenti",
             "dotazioni"],
        )
        self.assertIn("📅 Ferie e assenze", barra)
        self.assertIn("🧰 Dotazioni", barra)
        for vecchia in ("ferie", "dpi", "asset", "timbri", "onboarding"):
            self.assertNotIn(f'data-tab="{vecchia}"', html)
        self.assertIn("ferie: 'assenze', onboarding: 'contratto', dpi: 'dotazioni'", html)
        # Onboarding dentro Contratto, avvio chiuso finché non serve; timbri caricati quando entrano in vista.
        self.assertIn('data-tab="contratto" id="onboarding"', html)
        self.assertIn('class="dp-onb-avvia"', html)
        self.assertIn(reverse("timbri:operatore_embed", args=[self.dip.id]), html)
        self.assertIn('hx-trigger="intersect once"', html)

    def test_conferme_con_apostrofo_nel_nome(self):
        """Un apostrofo nel testo non rompe più la conferma (prima lo script falliva e l'azione partiva)."""
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.dip.id]))
        html = resp.content.decode()
        self.assertIn(
            "data-hub-confirm=\"Disattivare questo dipendente? L'account portale verrà scollegato.", html)
        self.assertIn("hub-confirm.js", html)
