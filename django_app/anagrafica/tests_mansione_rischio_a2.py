"""A2 — scheda dipendente: pannello "Profilo di rischio" derivato (mansione di rischio
a vista) e assegnazione diretta di esposizioni (punto 1.9)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from dpi.models import CategoriaDPI

from .models import Mansione
from .models_rischi import EsposizioneRischio, FattoreRischio
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ProfiloRischioPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="a2panel", email="a2panel@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["v.rossi", "Vito", "Rossi", "Verniciatore-A2", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername=%s", ["v.rossi"])
            self.legacy_id = int(cur.fetchone()[0])

    def test_panel_mostra_profilo_rischio_da_mansione(self):
        dpi_guanti = CategoriaDPI.objects.create(nome="Guanti chimici A2")
        fattore = FattoreRischio.objects.create(codice="CHI2", nome="Chimico A2")
        fattore.categorie_dpi.add(dpi_guanti)
        mansione = Mansione.objects.create(nome="Verniciatore-A2")
        EsposizioneRischio.objects.create(fattore=fattore, mansione=mansione)
        resp = self.client.get(
            reverse("anagrafica:dipendente_conformita_panel", args=[self.legacy_id])
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Profilo di rischio", body)
        self.assertIn("Guanti chimici A2", body)
        self.assertIn("Chimico A2", body)

    def test_panel_mostra_esposizione_diretta(self):
        fattore = FattoreRischio.objects.create(codice="RUM2", nome="Rumore A2")
        EsposizioneRischio.objects.create(fattore=fattore, legacy_anagrafica_id=self.legacy_id)
        resp = self.client.get(
            reverse("anagrafica:dipendente_conformita_panel", args=[self.legacy_id])
        )
        body = resp.content.decode()
        self.assertIn("Esposizioni dirette", body)
        self.assertIn("Rumore A2", body)

    def test_admin_aggiunge_esposizione_diretta(self):
        fattore = FattoreRischio.objects.create(codice="X1", nome="Fattore X1")
        resp = self.client.post(
            reverse("anagrafica:dipendente_esposizione_rischio_add", args=[self.legacy_id]),
            {"fattore_id": str(fattore.pk), "note": "assegnazione manuale"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            EsposizioneRischio.objects.filter(
                legacy_anagrafica_id=self.legacy_id, fattore=fattore
            ).exists()
        )
        self.assertIn("Fattore X1", resp.content.decode())

    def test_admin_rimuove_esposizione_diretta(self):
        fattore = FattoreRischio.objects.create(codice="X2", nome="Fattore X2")
        esp = EsposizioneRischio.objects.create(
            fattore=fattore, legacy_anagrafica_id=self.legacy_id
        )
        resp = self.client.post(
            reverse("anagrafica:dipendente_esposizione_rischio_remove", args=[self.legacy_id, esp.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(EsposizioneRischio.objects.filter(pk=esp.pk).exists())
