"""Rifinitura UI anomalie: dettaglio leggibile del log attività e plurali del Report OP."""
from __future__ import annotations

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from anomalie.views import _audit_detail_items


class AuditDetailItemsTests(SimpleTestCase):
    def test_dizionario_in_coppie_senza_vuoti(self):
        items = _audit_detail_items({"rows": 4, "filters": {"da": "", "q": "SN1", "limit": 50}, "note": ""})
        self.assertEqual(items, [("righe", "4"), ("filtri", "q=SN1, limit=50")])

    def test_valori_lunghi_troncati_e_non_dict(self):
        (label, value), = _audit_detail_items({"descrizione": "x" * 500})
        self.assertEqual(label, "descrizione")
        self.assertTrue(value.endswith("…"))
        self.assertLessEqual(len(value), 140)
        self.assertEqual(_audit_detail_items("testo libero"), [("", "testo libero")])
        self.assertEqual(_audit_detail_items(None), [])


class ReportRiepilogoPluraliTests(SimpleTestCase):
    def _render(self, tot, aperte, chiuse):
        return render_to_string("anomalie/pages/report_segnalazione.html", {
            "op": {"id": "OP/1"},
            "report": {"anomalie_totali": tot, "anomalie_aperte": aperte, "anomalie_chiuse": chiuse, "allegati_totali": 0},
            "anomalie": [], "anomalia": {}, "allegati": [],
        })

    def test_plurali_corretti(self):
        html = self._render(2, 0, 2)
        self.assertIn("anomalie registrate", html)
        self.assertIn("aperte", html)
        self.assertIn("chiuse", html)
        for sbagliato in ("anomaliae", "apertae", "chiusae", "registratae"):
            self.assertNotIn(sbagliato, html)

    def test_singolare(self):
        html = self._render(1, 1, 0)
        self.assertIn("anomalia registrata", html)
        self.assertIn("<strong>1</strong> aperta", html)
