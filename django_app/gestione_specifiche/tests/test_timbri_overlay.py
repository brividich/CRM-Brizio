"""#2 parte 2 — Overlay dei timbri sul composito."""
import fitz
from django.test import TestCase

from gestione_specifiche.timbri_overlay import applica_timbri


def _pdf_2pagine():
    doc = fitz.open()
    doc.new_page(width=595, height=842)  # MOD.133
    doc.new_page(width=595, height=842)  # documento originale
    return doc.tobytes()


def _png():
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 14), 0)
    pix.clear_with(120)
    return pix.tobytes("png")


class TimbriOverlayTest(TestCase):
    def test_ricevuto_e_data_solo_su_originale(self):
        out = applica_timbri(_pdf_2pagine(), ricevuto=_png(),
                             data_testo="03/07/2026", n_pagine_mod133=1)
        d = fitz.open(stream=out, filetype="pdf")
        self.assertEqual(d.page_count, 2)
        self.assertNotIn("03/07/2026", d[0].get_text())   # NON sul MOD.133
        self.assertIn("03/07/2026", d[1].get_text())       # sul documento originale
        self.assertEqual(len(d[0].get_images()), 0)        # nessun RICEVUTO sul MOD.133
        self.assertGreaterEqual(len(d[1].get_images()), 1)  # RICEVUTO sull'originale
        d.close()

    def test_firme_solo_sul_mod133(self):
        out = applica_timbri(_pdf_2pagine(), stamp_revisore=_png(), stamp_approvatore=_png(),
                             n_pagine_mod133=1)
        d = fitz.open(stream=out, filetype="pdf")
        self.assertGreaterEqual(len(d[0].get_images()), 1)  # firme sul MOD.133
        self.assertEqual(len(d[1].get_images()), 0)          # nulla sull'originale
        d.close()

    def test_nessun_timbro_non_modifica_pagine(self):
        out = applica_timbri(_pdf_2pagine(), n_pagine_mod133=1)
        d = fitz.open(stream=out, filetype="pdf")
        self.assertEqual(d.page_count, 2)
        self.assertEqual(len(d[0].get_images()), 0)
        self.assertEqual(len(d[1].get_images()), 0)
        d.close()
