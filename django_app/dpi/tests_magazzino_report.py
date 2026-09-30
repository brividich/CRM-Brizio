"""Report magazzino DPI: consumi, coperture, riordino, export CSV."""

from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import magazzino
from .models import CategoriaDPI, ModelloDPI, MovimentoMagazzinoDPI, RichiestaDPI, StatoRichiesta, TipoDPI

User = get_user_model()
OGGI = date(2026, 9, 30)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MagazzinoReportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-rep", password="x", email="r@y.z")
        self.client.force_login(self.admin)
        cat = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves", vita_utile_giorni=180)
        tipo = TipoDPI.objects.create(categoria=cat, nome="Guanti")
        self.a = ModelloDPI.objects.create(tipo=tipo, codice="GT-1", nome="Blade Safe", scorta_minima=10)
        self.b = ModelloDPI.objects.create(tipo=tipo, codice="GT-2", nome="Grip Pro")
        self.cat = cat

    def _scarico(self, modello, quantita, giorni_fa, reparto="Tornitura"):
        richiesta = RichiestaDPI.objects.create(
            categoria=self.cat, modello_dpi=modello, quantita=quantita, stato=StatoRichiesta.CONSEGNATA,
            richiedente_nome="Mario Rossi", richiedente_reparto=reparto,
        )
        MovimentoMagazzinoDPI.objects.create(
            modello=modello, tipo="SCARICO", quantita=-quantita, data=OGGI - timedelta(days=giorni_fa), richiesta=richiesta
        )

    def test_report_aggrega_consumi_per_modello_reparto_e_mese(self):
        magazzino.carica_ddt(self.a, 100, data=OGGI - timedelta(days=40))
        self._scarico(self.a, 30, 10)
        self._scarico(self.a, 10, 50, reparto="Montaggio")
        self._scarico(self.b, 5, 200)
        dati = magazzino.report(90, oggi=OGGI)
        self.assertEqual(dati["consumati"], 40)
        self.assertEqual(dati["caricati"], 100)
        self.assertEqual(dati["top"][0]["modello"], self.a)
        self.assertEqual(dict(dati["reparti"]), {"Tornitura": 30, "Montaggio": 10})
        self.assertEqual(len(dati["serie"]), 12)
        self.assertEqual(sum(s["pezzi"] for s in dati["serie"]), 45)  # include i 5 di 200 giorni fa (entro 12 mesi)

    def test_riordino_include_esauriti_e_sotto_scorta_con_quantita_suggerita(self):
        magazzino.carica_ddt(self.a, 8, data=OGGI - timedelta(days=60))
        dati = magazzino.report(90, oggi=OGGI)
        riga_a = next(r for r in dati["riordino"] if r["modello"] == self.a)
        self.assertEqual(riga_a["stato"], magazzino.STATO_SOTTO_SCORTA)
        self.assertEqual(riga_a["suggerito"], 12)  # 2 x soglia(10) - giacenza(8)
        self.assertTrue(any(r["modello"] == self.b and r["stato"] == magazzino.STATO_ESAURITO for r in dati["riordino"]))

    def test_copertura_in_giorni_dal_consumo_medio(self):
        magazzino.carica_ddt(self.a, 130, data=OGGI - timedelta(days=80))
        self._scarico(self.a, 30, 20)  # 30 pezzi in 90 giorni -> 1/3 al giorno; giacenza 100 -> 300 gg
        riga = next(r for r in magazzino.report(90, oggi=OGGI)["righe"] if r["modello"] == self.a)
        self.assertEqual(riga["giacenza"], 100)
        self.assertEqual(riga["copertura"], 300)

    def test_pagina_e_csv(self):
        magazzino.carica_ddt(self.a, 20, ddt_numero="=CMD()", fornitore="Alfa")
        page = self.client.get(reverse("dpi:magazzino_report"), {"giorni": "30"})
        self.assertContains(page, "Report magazzino DPI")
        csv_resp = self.client.get(reverse("dpi:magazzino_report"), {"giorni": "365", "formato": "csv"})
        self.assertEqual(csv_resp.status_code, 200)
        body = csv_resp.content.decode("utf-8-sig")
        self.assertIn("Carico da DDT", body)
        self.assertIn("'=CMD()", body)  # formula neutralizzata

    def test_riservato_ai_gestori(self):
        with mock.patch("dpi.views._is_gestore", return_value=False):
            self.assertEqual(self.client.get(reverse("dpi:magazzino_report")).status_code, 302)
            self.assertEqual(self.client.get(reverse("dpi:magazzino_report"), {"formato": "csv"}).status_code, 302)
