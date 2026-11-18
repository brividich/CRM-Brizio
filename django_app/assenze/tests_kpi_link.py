"""Tessere KPI cliccabili del modulo assenze: link alla sezione o alla lista che conta lo stesso numero."""
from __future__ import annotations

from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from assenze.views import hr_gestione


class AssenzeKpiLinkTests(TestCase):
    def test_dashboard_segnalazioni_tessere_e_ancore(self):
        html = render_to_string("assenze/pages/car_dashboard.html", {
            "da_gestire": [], "n_in_attesa": 3, "riepilogo_oggi": [], "riepilogo_settimana": [],
            "gestite": [], "history_page": 1, "history_period": "tutte", "pending_scope": "all",
            "can_view_all": True,
        })
        u = reverse("assenze_car_dashboard")
        self.assertIn(f'href="{u}?scope=all#in-attesa"', html)
        self.assertIn(f'href="{u}?scope=all#oggi"', html)
        self.assertIn(f'href="{u}?scope=all#settimana"', html)
        self.assertIn(f'href="{u}?scope=all&amp;periodo_storico=tutte#storico"', html)
        for ancora in ('id="in-attesa"', 'id="oggi"', 'id="settimana"', 'id="storico"'):
            self.assertIn(ancora, html)

    def test_le_mie_richieste_tessere(self):
        html = render_to_string("assenze/pages/gestione_assenze.html", {
            "summary_personali": {"total": 2, "waiting": 1, "approved": 1, "rejected": 0, "editable": 1},
            "summary_da_approvare": {"total": 1}, "n_da_approvare": 5, "limite_elenco": 40,
            "assenze_can_view_team": True, "richieste_personali": [], "richieste_da_approvare": [],
        })
        u = reverse("assenze_gestione")
        self.assertIn(f'href="{u}?stato=waiting#mie-richieste"', html)
        self.assertIn(f'href="{u}#dipendenti"', html)
        self.assertIn("In elenco le prime 1.", html)
        self.assertIn('id="mie-richieste"', html)
        self.assertIn('id="dipendenti"', html)

    def test_menu_coda_porta_alla_dashboard_segnalazioni(self):
        html = render_to_string("assenze/pages/menu.html", {
            "assenze_can_view_team": True, "car_pending_count": 4, "recenti": [],
        })
        self.assertIn(f'href="{reverse("assenze_car_dashboard")}#in-attesa"', html)
        self.assertIn('id="richieste-recenti"', html)


class HrCodaKpiTests(SimpleTestCase):
    def test_coda_hr_conta_con_la_funzione_della_dashboard(self):
        with patch("assenze.views.richieste.count_all_pending", return_value=7) as conta:
            self.assertEqual(hr_gestione._n_coda_attiva(), 7)
        conta.assert_called_once_with()
