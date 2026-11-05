"""Guida del modulo KICK-OFF: contenuto, immagini, ancore delle pagine, PDF."""
from __future__ import annotations

import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from tasks.guida import SEZIONI
from tasks.guida_ruoli import GUIDE_RUOLI

_TIPI = {"p", "passi", "ul", "def", "nota", "img"}
_TEMPLATES = Path(__file__).parent / "templates" / "tasks"


def _tutte_le_sezioni():
    yield from SEZIONI
    for guida in GUIDE_RUOLI.values():
        yield from guida["sezioni"]


class GuidaContenutoTests(SimpleTestCase):
    def test_sezioni_ben_formate_e_immagini_presenti(self):
        ids = [s["id"] for s in _tutte_le_sezioni()]
        self.assertEqual(len(ids), len(set(ids)))
        for s in _tutte_le_sezioni():
            with self.subTest(sezione=s["id"]):
                self.assertTrue(s["titolo"])
                self.assertTrue(s["blocchi"])
                for kind, contenuto in s["blocchi"]:
                    self.assertIn(kind, _TIPI)
                    self.assertTrue(contenuto)
                    if kind == "img":
                        self.assertIsNotNone(finders.find(contenuto[0]), contenuto[0])

    def test_ogni_ancora_delle_pagine_esiste(self):
        ids = {s["id"] for s in SEZIONI}
        trovate = 0
        for template in _TEMPLATES.rglob("*.html"):
            for ancora in re.findall(r"tasks_shell_guide_anchor %\}#([\w-]+)", template.read_text(encoding="utf-8")):
                trovate += 1
                with self.subTest(template=template.name):
                    self.assertIn(ancora, ids)
        self.assertGreaterEqual(trovate, 15)

    def test_nessun_testo_del_modulo_a_tre_fasi(self):
        testo = str(SEZIONI)
        for parola in ("Industrializzazione,", "sotto-parametri", "DIG"):
            self.assertNotIn(parola, testo)

    def test_assistente_ai_legge_i_passi_e_salta_le_immagini(self):
        from ai_assistant.guide_portale import sezioni_in_markdown

        testo = sezioni_in_markdown(SEZIONI)
        self.assertIn("Crea kickoff e convoca il primo incontro", testo)
        self.assertNotIn(".jpg", testo)


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class GuidaPagineTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="guida-ko", password="x", is_superuser=True, is_staff=True,
        )
        self.client.force_login(user)
        self.url = reverse("tasks:guida")

    def test_guida_completa(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Il percorso di una commessa")
        self.assertContains(response, "tasks/guida/piano.jpg")
        self.assertContains(response, "?per=gestione")
        self.assertContains(response, "?per=team")
        self.assertContains(response, "?pdf=1")
        self.assertContains(response, "già creata")

    def test_guide_rapide(self):
        for chiave, guida in GUIDE_RUOLI.items():
            with self.subTest(chiave=chiave):
                response = self.client.get(self.url, {"per": chiave})
                self.assertContains(response, guida["sezioni"][0]["titolo"])
                self.assertContains(response, "Guida completa")

    def test_ruolo_sconosciuto_apre_la_completa(self):
        response = self.client.get(self.url, {"per": "boh"})
        self.assertContains(response, "Il percorso di una commessa")

    def test_pdf(self):
        for parametri, nome in (
            ({"pdf": "1", "per": "team"}, "Guida_KickOff_Team.pdf"),
            ({"pdf": "1", "per": "gestione"}, "Guida_KickOff_Gestione.pdf"),
            ({"pdf": "1"}, "Guida_KickOff.pdf"),
        ):
            with self.subTest(nome=nome):
                response = self.client.get(self.url, parametri)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(b"%PDF"))
                self.assertIn(nome, response["Content-Disposition"])
