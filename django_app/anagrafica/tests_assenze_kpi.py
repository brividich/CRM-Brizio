"""1.11 — KPI annuali assenze: conteggio richieste per anno×tipologia."""
from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from .views import _assenze_kpi_annuali


class AssenzeKpiAnnualiTests(SimpleTestCase):
    def test_conteggio_per_anno_e_tipologia(self):
        rows = [
            {"data_inizio": date(2026, 1, 10), "tipo_assenza": "Ferie", "moderation_status": 0},
            {"data_inizio": date(2026, 3, 5), "tipo_assenza": "Ferie", "moderation_status": 2},
            {"data_inizio": date(2026, 4, 2), "tipo_assenza": "Malattia", "moderation_status": 0},
            {"data_inizio": date(2025, 7, 1), "tipo_assenza": "Permesso", "moderation_status": 0},
        ]
        kpi = _assenze_kpi_annuali(rows)
        anni = {k["anno"]: k for k in kpi}
        self.assertEqual(anni[2026]["totale"], 3)
        tipi_2026 = {t["tipo"]: t["conteggio"] for t in anni[2026]["tipi"]}
        self.assertEqual(tipi_2026["Ferie"], 2)
        self.assertEqual(tipi_2026["Malattia"], 1)
        self.assertEqual(anni[2025]["totale"], 1)

    def test_ordinamento_anni_desc(self):
        rows = [
            {"data_inizio": date(2024, 1, 1), "tipo_assenza": "Ferie", "moderation_status": 0},
            {"data_inizio": date(2026, 1, 1), "tipo_assenza": "Ferie", "moderation_status": 0},
        ]
        kpi = _assenze_kpi_annuali(rows)
        self.assertEqual([k["anno"] for k in kpi], [2026, 2024])

    def test_ignora_righe_senza_data(self):
        kpi = _assenze_kpi_annuali(
            [{"data_inizio": None, "tipo_assenza": "X", "moderation_status": 0}]
        )
        self.assertEqual(kpi, [])

    def test_tipo_vuoto_diventa_altro(self):
        kpi = _assenze_kpi_annuali(
            [{"data_inizio": date(2026, 1, 1), "tipo_assenza": "", "moderation_status": 0}]
        )
        tipi = {t["tipo"] for t in kpi[0]["tipi"]}
        self.assertIn("Altro", tipi)
