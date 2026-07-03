"""#1 — Render del MOD.133 sul template REALE (overlay pymupdf)."""
import fitz
from django.test import TestCase

from gestione_specifiche.mod133_overlay import render_mod133_overlay


def _dati(n_righe=3):
    return {
        "fonte": "Ferrari S.p.A.",
        "documento_analizzato": "SP-2026-0042 Rev.B - Requisiti speciali",
        "documenti_cn_interessati": "MT CN 06; PR CN 12",
        "data": "03/07/2026",
        "revisore": "Luca Bova",
        "approvatore": "Mario Rossi",
        "righe": [{
            "paragrafi": f"{i}.1",
            "argomenti": "Nuovo requisito molto lungo da mandare a capo " * 3,
            "impatto_doc": "SI" if i % 2 else "NO",
            "impatto_operativo": "NO" if i % 2 else "SI",
            "paragrafi_cn": "MT 06 §4",
            "argomenti_cn": "Aggiornata procedura di controllo",
        } for i in range(n_righe)],
    }


class Mod133OverlayTest(TestCase):
    def test_render_contiene_testata_righe_firme(self):
        pdf = render_mod133_overlay(_dati(3))
        d = fitz.open(stream=pdf, filetype="pdf")
        self.assertEqual(d.page_count, 1)
        txt = d[0].get_text()
        # form reale
        self.assertIn("FLOW DOWN FOR NEW REQUIREMENTS", txt)
        self.assertIn("Mod.133", txt)
        # dati sovrapposti
        self.assertIn("Ferrari", txt)
        self.assertIn("SP-2026-0042", txt)
        self.assertIn("03/07/2026", txt)
        self.assertIn("Luca Bova", txt)      # revisore
        self.assertIn("Mario Rossi", txt)    # approvatore
        d.close()

    def test_render_argomento_lungo_non_sparisce(self):
        # con testo lungo l'overlay deve rimpicciolire/troncare, mai lasciare la cella vuota
        pdf = render_mod133_overlay(_dati(1))
        d = fitz.open(stream=pdf, filetype="pdf")
        txt = d[0].get_text()
        self.assertIn("Nuovo requisito", txt)
        d.close()

    def test_render_multipagina_oltre_7_righe(self):
        pdf = render_mod133_overlay(_dati(10))
        d = fitz.open(stream=pdf, filetype="pdf")
        self.assertEqual(d.page_count, 2)  # 7 + 3
        # la seconda pagina è comunque il template reale
        self.assertIn("FLOW DOWN FOR NEW REQUIREMENTS", d[1].get_text())
        d.close()

    def test_render_senza_righe_non_crasha(self):
        pdf = render_mod133_overlay({"fonte": "X", "righe": []})
        d = fitz.open(stream=pdf, filetype="pdf")
        self.assertEqual(d.page_count, 1)
        d.close()
