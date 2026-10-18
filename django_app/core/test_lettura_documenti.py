"""Lettura dei documenti in ingresso (core.lettura_documenti). Documenti sintetici."""
from __future__ import annotations

import io
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from core import lettura_documenti as ld


def pdf_con_testo(righe: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for riga in righe:
        page.insert_text((60, y), riga, fontsize=11)
        y += 18
    data = doc.tobytes()
    doc.close()
    return data


class LetturaTests(SimpleTestCase):
    def test_pdf_nativo_senza_ocr(self):
        lettura = ld.leggi(pdf_con_testo(["Attestato di frequenza", "Corso svolto il 12/03/2026 durata 8 ore",
                                          "Rilasciato da Ente Sintetico Formazione"]))
        self.assertIn("12/03/2026", lettura.testo)
        self.assertFalse(lettura.ocr)
        self.assertEqual(lettura.pagine, 1)

    def test_scansione_senza_tesseract_avvisa(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
        with patch("anagrafica.services.referti_ocr.disponibile", return_value=False):
            lettura = ld.leggi(buf.getvalue())
        self.assertEqual(lettura.testo.strip(), "")
        self.assertTrue(any("Tesseract" in a for a in lettura.avvisi))

    def test_file_non_leggibili(self):
        for contenuto in (b"", b"%PDF-rotto", b"non un'immagine"):
            with self.subTest(contenuto=contenuto[:10]):
                with self.assertRaises(ld.DocumentoNonLeggibile):
                    ld.leggi(contenuto)

    def test_date_in_piu_formati(self):
        t = ld.normalizza("dal 3/4/2026 al 05-04-26 e il 7 maggio 2026, poi 31/02/2026 (non valida)")
        self.assertEqual([d for _, d in ld.date_nel_testo(t)],
                         [date(2026, 4, 3), date(2026, 4, 5), date(2026, 5, 7)])

    def test_data_dopo_etichetta_per_priorita(self):
        t = ld.normalizza("Data stampa 01/10/2026. Corso svolto in data 12/03/2026. Rilasciato il 15/03/2026")
        self.assertEqual(ld.data_dopo_etichetta(t, (r"SVOLT[OA]",)), date(2026, 3, 12))
        self.assertEqual(ld.data_dopo_etichetta(t, (r"RILASCIAT[OA]",)), date(2026, 3, 15))
        self.assertIsNone(ld.data_dopo_etichetta(t, (r"SCADENZA",)))

    def test_contiene_parola_intera_e_accenti(self):
        t = ld.normalizza("Partecipante: Niccolò ROSSI — codice SIC-01")
        self.assertTrue(ld.contiene_parola(t, "niccolo rossi"))
        self.assertTrue(ld.contiene_parola(t, "SIC-01"))
        self.assertFalse(ld.contiene_parola(t, "SIC-0"))
        self.assertFalse(ld.contiene_parola(t, "ROSS"))
