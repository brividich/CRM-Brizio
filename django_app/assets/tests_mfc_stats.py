"""Statistiche MFC sulla scheda asset (PROMPT 06 - B). Dati sintetici, IP 192.0.2.x."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_tz
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contatori.models import LetturaConsumabile, LetturaMensileContatori, Macchina

from .models import Asset, AssetEndpoint
from .services import mfc_stats

ORA = datetime(2026, 10, 10, 9, 0, tzinfo=dt_tz.utc)


def _mese(y, m, bn, col):
    return {"mese": date(y, m, 1), "a4_bn": bn, "a3_bn": 0, "a4_col": col, "a3_col": 0}


class PaginePerMeseTests(TestCase):
    def test_differenze_mensili_e_casi_non_calcolabili(self):
        letture = [
            _mese(2026, 1, 1000, 100),
            _mese(2026, 2, 1500, 160),   # gennaio: 500 B/N, 60 colore
            _mese(2026, 3, 1400, 170),   # contatore B/N sceso: febbraio non calcolabile
            _mese(2026, 5, 2000, 200),   # aprile mancante: marzo/aprile non calcolabili
        ]
        serie = mfc_stats.pagine_per_mese(letture)
        self.assertEqual(serie[0], {"mese": date(2026, 1, 1), "bn": 500, "col": 60, "totale": 560})
        self.assertIsNone(serie[1]["totale"])
        self.assertIsNone(serie[2]["totale"])
        self.assertEqual(len(serie), 3)

    def test_trend(self):
        serie = [{"totale": t} for t in (100, 100, 100, 150, 150, 150)]
        self.assertEqual(mfc_stats.trend(serie)["direzione"], "su")
        self.assertEqual(mfc_stats.trend(serie)["delta_pct"], 50)
        self.assertEqual(mfc_stats.trend([{"totale": t} for t in (100, 100, 100, 50, 50, 50)])["delta_abs"], 50)
        self.assertIsNone(mfc_stats.trend(serie[:5]))
        self.assertEqual(mfc_stats.trend([{"totale": 100}] * 6)["direzione"], "stabile")


class StatisticheTests(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-MFC-1", host="192.0.2.81",
                                         snmp_stato="ERROR", snmp_ultimo_errore="timeout sintetico")

    def _row(self):
        return Macchina.objects.filter(pk=self.m.pk).values(
            "id", "snmp_stato", "snmp_ultimo_controllo", "snmp_ultimo_errore").get()

    def test_senza_letture(self):
        stats = mfc_stats.statistiche_mfc([self._row()], ora=ORA)[self.m.pk]
        self.assertIsNone(stats["consumabili"])
        self.assertEqual(stats["pagine_mesi"], [])
        self.assertFalse(stats["consumabili_vecchi"])
        self.assertEqual(stats["errore_snmp"], "timeout sintetico")

    def test_stima_e_lettura_vecchia(self):
        for i, pct in enumerate((60, 50, 40)):
            LetturaConsumabile.objects.create(macchina=self.m, nome="Nero", pct=pct,
                                              rilevata_il=ORA - timedelta(days=30 - i * 10))
        stats = mfc_stats.statistiche_mfc([self._row()], ora=ORA)[self.m.pk]
        voce = stats["consumabili"]["voci"][0]
        self.assertEqual(voce["pct"], 40)
        self.assertEqual(voce["giorni"], 40)  # 20 punti in 20 giorni -> 40 giorni
        self.assertEqual(stats["consumabili_eta_giorni"], 10)
        self.assertTrue(stats["consumabili_vecchi"])
        with override_settings(ASSETS_MFC_CONSUMABILI_VECCHI_GIORNI=15):
            self.assertFalse(mfc_stats.statistiche_mfc([self._row()], ora=ORA)[self.m.pk]["consumabili_vecchi"])

    def test_pagine_dal_db_e_query_limitate(self):
        for i, (bn, col) in enumerate(((1000, 10), (1300, 30), (1700, 40))):
            LetturaMensileContatori.objects.create(
                macchina=self.m, mese=date(2026, 6 + i, 1), a4_bn=bn, a3_bn=0, a4_col=col, a3_col=0,
                rilevata_il=datetime(2026, 6 + i, 1, 1, 0, tzinfo=dt_tz.utc))
        row = self._row()
        with self.assertNumQueries(2):
            stats = mfc_stats.statistiche_mfc([row], ora=ORA)[self.m.pk]
        self.assertEqual([s["totale"] for s in stats["pagine_mesi"]], [320, 410])
        self.assertEqual(stats["pagine_ultimo_mese"]["mese"], date(2026, 7, 1))
        self.assertTrue(stats["contatori_vecchi"])  # ultima lettura 01/08, ora 10/10: manca settembre
        self.assertEqual(stats["contatori_eta_giorni"], 70)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SchedaAssetMfcTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("mfc-demo", "mfc@example.test", "synthetic-only")
        self.client.force_login(self.user)
        self.asset = Asset.objects.create(asset_tag="PR-MFC-1", name="MFC demo", asset_type="STAMPANTE",
                                          serial_number="SYN-MFC-SER")

    def test_livelli_automatici_senza_snmp_nella_request(self):
        m = Macchina.objects.create(reparto="Beta", matricola="SYN-MFC-2", host="192.0.2.82", asset=self.asset)
        LetturaConsumabile.objects.create(macchina=m, nome="Toner nero", pct=12, rilevata_il=timezone.now())
        with patch("contatori.snmp.leggi_consumabili", side_effect=AssertionError("no SNMP")), \
                patch("contatori.services.leggi_consumabili_macchina", side_effect=AssertionError("no SNMP")):
            response = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(response, "Toner nero")
        self.assertContains(response, "12%")
        self.assertContains(response, "Leggi adesso")
        self.assertContains(response, reverse("contatori:macchina", args=[m.pk]))
        self.assertNotContains(response, "il job non legge da")

    def test_lettura_vecchia_segnalata(self):
        m = Macchina.objects.create(reparto="Gamma", matricola="SYN-MFC-3", host="192.0.2.83", asset=self.asset)
        LetturaConsumabile.objects.create(macchina=m, nome="Toner nero", pct=70,
                                          rilevata_il=timezone.now() - timedelta(days=9))
        response = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(response, "il job non legge da 9 giorni")

    def test_stampante_non_collegata_propone_le_mfc_candidate(self):
        AssetEndpoint.objects.create(asset=self.asset, ip="192.0.2.84")
        cand = Macchina.objects.create(reparto="Delta", matricola="ALTRA", host="192.0.2.84")
        Macchina.objects.create(reparto="Epsilon", matricola="NON-C-ENTRA", host="192.0.2.99")
        response = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(response, "non è collegata a nessuna MFC")
        self.assertContains(response, f"mfc:{cand.pk}:{self.asset.pk}")
        self.assertNotContains(response, "NON-C-ENTRA")

    def test_collega_dalla_scheda_torna_alla_scheda(self):
        cand = Macchina.objects.create(reparto="Delta", matricola="SYN-MFC-SER", host="192.0.2.85")
        detail = reverse("assets:asset_view", args=[self.asset.pk])
        response = self.client.post(reverse("assets:it_reconciliation"),
                                    {"row": f"mfc:{cand.pk}:{self.asset.pk}", "next": detail})
        self.assertRedirects(response, detail, fetch_redirect_response=False)
        cand.refresh_from_db()
        self.assertEqual(cand.asset_id, self.asset.pk)
        evil = self.client.post(reverse("assets:it_reconciliation"), {"row": "x", "next": "https://evil.example/"})
        self.assertEqual(evil["Location"], reverse("assets:it_reconciliation"))
