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

    def test_le_mie_richieste_blocchi_e_ancore(self):
        """Le tessere non ci sono più: i conteggi stanno nelle intestazioni dei blocchi."""
        from datetime import datetime

        from assenze import mie_richieste

        righe = [
            {"id": 1, "tipo": "Ferie", "tipo_raw": "Ferie", "stato": "In attesa",
             "inizio_iso": "2026-12-23T07:00:00.000Z", "fine_iso": "2026-12-24T16:00:00.000Z",
             "creata_label": "18-11-2026 09:00", "motivazione": "Natale"},
            {"id": 2, "tipo": "Permesso", "tipo_raw": "Permesso", "stato": "Approvato",
             "inizio_iso": "2026-10-16T07:00:00.000Z", "fine_iso": "2026-10-16T09:00:00.000Z"},
        ]
        with patch("assenze.mie_richieste._durate"):
            extra = mie_richieste.contesto(righe, now=datetime(2026, 11, 22, 10, 0))
        html = render_to_string("assenze/pages/gestione_assenze.html", {
            "summary_personali": {"total": 2, "waiting": 1, "approved": 1, "rejected": 0, "editable": 1},
            "summary_da_approvare": {"total": 1}, "n_da_approvare": 5, "limite_elenco": 40,
            "assenze_can_view_team": True, "richieste_personali": righe, "richieste_da_approvare": [],
            **extra,
        })
        self.assertIn(f'href="{reverse("assenze_car_dashboard")}#in-attesa"', html)
        self.assertIn("In elenco le prime 1.", html)
        # Ancore usate dai link in arrivo (home, «Le mie attività»).
        for ancora in ('id="mie-richieste"', 'id="dipendenti"', 'id="mr-attesa"', 'id="mr-passate"'):
            self.assertIn(ancora, html)
        self.assertNotIn('id="mr-rifiutate"', html)
        self.assertIn("la più vecchia da 4 giorni", html)
        self.assertIn('data-mr-mese="12"', html)
        self.assertIn('data-delete-url="/assenze/api/eventi/1/delete"', html)
        # «Modifica» solo sulla richiesta in attesa.
        self.assertEqual(html.count("btn-modifica"), 1)

    def test_menu_coda_porta_alla_dashboard_segnalazioni(self):
        html = render_to_string("assenze/pages/menu.html", {
            "assenze_can_view_team": True, "car_pending_count": 4, "recenti": [],
        })
        self.assertIn(f'href="{reverse("assenze_car_dashboard")}#in-attesa"', html)
        self.assertIn('id="richieste-recenti"', html)


class MieRichiesteContestoTests(SimpleTestCase):
    ORA = __import__("datetime").datetime(2026, 11, 22, 10, 0)

    def _riga(self, **kw):
        base = {"id": 1, "tipo": "Ferie", "tipo_raw": "Ferie", "stato": "Approvato",
                "inizio_iso": "2026-11-09T00:00:00", "fine_iso": "2026-11-11T23:59:00", "creata_label": ""}
        base.update(kw)
        return base

    def _contesto(self, righe):
        from assenze import mie_richieste

        with patch("assenze.mie_richieste._durate"):
            return mie_richieste.contesto(righe, now=self.ORA)

    def test_gruppi_per_momento(self):
        righe = [
            self._riga(id=1, stato="In attesa", inizio_iso="2026-12-23T08:00:00", fine_iso="2027-01-05T17:00:00",
                       creata_label="21-11-2026 08:00"),
            self._riga(id=2, inizio_iso="2026-12-07T00:00:00", fine_iso="2026-12-07T23:59:00"),
            self._riga(id=3),
            self._riga(id=4, stato="Rifiutato", tipo="Permesso", tipo_raw="Permesso",
                       inizio_iso="2026-10-16T08:00:00", fine_iso="2026-10-16T10:00:00"),
        ]
        ctx = self._contesto(righe)
        self.assertEqual([g["chiave"] for g in ctx["mr_gruppi"]], ["attesa", "programma", "passate", "rifiutate"])
        self.assertEqual([g["aperta"] for g in ctx["mr_gruppi"]], [True, True, False, False])
        self.assertEqual(righe[0]["periodo_label"], "23 dic → 5 gen 2027")
        self.assertEqual(righe[0]["attesa_label"], "da ieri")
        self.assertEqual(righe[1]["periodo_label"], "lun 7 dic")
        self.assertEqual(ctx["mr_gruppi"][1]["nota"], "prossima: lun 7 dic")
        self.assertEqual(righe[3]["periodo_label"], "ven 16 ott, 08:00–10:00")
        self.assertEqual(righe[3]["tipo_key"], "permesso")
        self.assertEqual(ctx["mr_anno"], "2026")

    def test_striscia_anno_esclude_rifiutate_e_taglia_a_fine_anno(self):
        righe = [
            self._riga(id=1, stato="In attesa", inizio_iso="2026-12-23T08:00:00", fine_iso="2027-01-05T17:00:00"),
            self._riga(id=4, stato="Rifiutato", inizio_iso="2026-10-16T08:00:00", fine_iso="2026-10-16T10:00:00"),
        ]
        ctx = self._contesto(righe)
        per_mese = {m["n"]: m["segmenti"] for m in ctx["mr_mesi"]}
        self.assertEqual(per_mese[10], [])
        self.assertEqual(len(per_mese[12]), 1)
        self.assertTrue(per_mese[12][0]["attesa"])
        self.assertEqual(per_mese[12][0]["style"], "left:71.0%;width:29.0%")
        self.assertEqual(righe[0]["mesi_attr"], ",12,")
        self.assertEqual(righe[1]["mesi_attr"], "")
        self.assertTrue(ctx["mr_mesi"][10]["corrente"])

    def test_date_mancanti_non_rompono_la_pagina(self):
        righe = [self._riga(inizio_iso="", fine_iso="", inizio="?", fine="")]
        ctx = self._contesto(righe)
        self.assertEqual(ctx["mr_gruppi"][0]["chiave"], "passate")
        self.assertFalse(ctx["mr_ha_segmenti"])


class HrCodaKpiTests(SimpleTestCase):
    def test_coda_hr_conta_con_la_funzione_della_dashboard(self):
        with patch("assenze.views.richieste.count_all_pending", return_value=7) as conta:
            self.assertEqual(hr_gestione._n_coda_attiva(), 7)
        conta.assert_called_once_with()
