"""Test del toolkit PDF offline (composizione + protezione MOD.133).

PDF sintetici costruiti con fitz: nessun dato cliente reale. Si verificano conteggio/ordine
pagine dopo anteponi/sostituisci e i permessi/filigrana/apertura-libera dopo la protezione.
"""
from django.test import SimpleTestCase

import fitz

from gestione_specifiche.pdf_compose import (
    anteponi_pagine,
    applica_protezione,
    sostituisci_prima_pagina,
)


def _pdf(etichette):
    """Crea un PDF con una pagina per ogni etichetta (testo marker in alto a sinistra)."""
    doc = fitz.open()
    try:
        for testo in etichette:
            page = doc.new_page()
            page.insert_text((72, 72), testo)
        return doc.tobytes()
    finally:
        doc.close()


def _testi_pagine(pdf_bytes):
    """Ritorna la lista dei testi (una stringa per pagina) di un PDF in bytes."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [doc[i].get_text().strip() for i in range(doc.page_count)]
    finally:
        doc.close()


class AnteponiPagineTest(SimpleTestCase):
    def test_antepone_una_pagina_conteggio_e_ordine(self):
        base = _pdf(["BASE-0", "BASE-1"])
        cover = _pdf(["COVER"])
        out = anteponi_pagine(base, [cover])
        testi = _testi_pagine(out)
        self.assertEqual(len(testi), 3)
        self.assertEqual(testi[0], "COVER")
        self.assertEqual(testi[1], "BASE-0")
        self.assertEqual(testi[2], "BASE-1")

    def test_antepone_piu_pagine_mantiene_ordine_lista(self):
        base = _pdf(["BASE-0"])
        out = anteponi_pagine(base, [_pdf(["P1"]), _pdf(["P2"])])
        testi = _testi_pagine(out)
        self.assertEqual(testi, ["P1", "P2", "BASE-0"])

    def test_lista_vuota_lascia_base(self):
        base = _pdf(["BASE-0", "BASE-1"])
        out = anteponi_pagine(base, [])
        self.assertEqual(_testi_pagine(out), ["BASE-0", "BASE-1"])


class SostituisciPrimaPaginaTest(SimpleTestCase):
    def test_sostituisce_prima_pagina_conserva_le_altre(self):
        base = _pdf(["COVER", "BASE-1", "BASE-2"])
        nuova = _pdf(["MOD133"])
        out = sostituisci_prima_pagina(base, nuova)
        testi = _testi_pagine(out)
        self.assertEqual(len(testi), 3)
        self.assertEqual(testi[0], "MOD133")
        self.assertEqual(testi[1], "BASE-1")
        self.assertEqual(testi[2], "BASE-2")

    def test_base_di_una_sola_pagina(self):
        base = _pdf(["COVER"])
        out = sostituisci_prima_pagina(base, _pdf(["MOD133"]))
        self.assertEqual(_testi_pagine(out), ["MOD133"])


class ApplicaProtezioneTest(SimpleTestCase):
    def test_default_nega_stampa_e_modifica_e_apre_senza_password(self):
        pdf = _pdf(["BASE-0"])
        out = applica_protezione(pdf, owner_password="segreto-owner")
        doc = fitz.open(stream=out, filetype="pdf")
        try:
            # user_pw vuota -> apertura libera, nessuna password richiesta.
            self.assertFalse(doc.needs_pass)
            # Il file resta cifrato (auto-autenticato come user con pw vuota).
            self.assertTrue(doc.metadata.get("encryption"))
            self.assertEqual(doc.permissions & fitz.PDF_PERM_PRINT, 0)
            self.assertEqual(doc.permissions & fitz.PDF_PERM_MODIFY, 0)
        finally:
            doc.close()

    def test_consenti_stampa_inverte_il_bit(self):
        pdf = _pdf(["BASE-0"])
        senza = applica_protezione(pdf, owner_password="o")
        con = applica_protezione(pdf, owner_password="o", consenti_stampa=True)

        d0 = fitz.open(stream=senza, filetype="pdf")
        d1 = fitz.open(stream=con, filetype="pdf")
        try:
            self.assertEqual(d0.permissions & fitz.PDF_PERM_PRINT, 0)
            self.assertTrue(d1.permissions & fitz.PDF_PERM_PRINT)
        finally:
            d0.close()
            d1.close()

    def test_consenti_modifica_e_copia_invertono_i_bit(self):
        pdf = _pdf(["BASE-0"])
        out = applica_protezione(
            pdf, owner_password="o", consenti_modifica=True, consenti_copia=True
        )
        doc = fitz.open(stream=out, filetype="pdf")
        try:
            self.assertTrue(doc.permissions & fitz.PDF_PERM_MODIFY)
            self.assertTrue(doc.permissions & fitz.PDF_PERM_COPY)
        finally:
            doc.close()

    def test_filigrana_presente_su_ogni_pagina(self):
        pdf = _pdf(["BASE-0", "BASE-1"])
        out = applica_protezione(pdf, owner_password="o", filigrana="RISERVATO")
        doc = fitz.open(stream=out, filetype="pdf")
        try:
            for i in range(doc.page_count):
                self.assertIn("RISERVATO", doc[i].get_text())
        finally:
            doc.close()

    def test_non_modifica_i_bytes_originali(self):
        pdf = _pdf(["BASE-0"])
        originale = bytes(pdf)
        applica_protezione(pdf, owner_password="o", filigrana="RISERVATO")
        self.assertEqual(pdf, originale)


class InputVuotoTest(SimpleTestCase):
    """Le tre funzioni falliscono con ValueError ESPLICITO su input vuoto/0-pagine."""

    def test_applica_protezione_stream_vuoto(self):
        with self.assertRaises(ValueError):
            applica_protezione(b"", owner_password="o")

    def test_anteponi_base_vuota(self):
        with self.assertRaises(ValueError):
            anteponi_pagine(b"", [_pdf(["X"])])

    def test_anteponi_pagina_vuota_nella_lista(self):
        with self.assertRaises(ValueError):
            anteponi_pagine(_pdf(["BASE"]), [b""])

    def test_sostituisci_base_vuota(self):
        with self.assertRaises(ValueError):
            sostituisci_prima_pagina(b"", _pdf(["X"]))


class AntiMutazioneMergeTest(SimpleTestCase):
    """Contratto 'non modifica gli input' anche per le due funzioni di merge."""

    def test_anteponi_non_muta_input(self):
        base = _pdf(["BASE-0"])
        cover = _pdf(["COVER"])
        b0, c0 = bytes(base), bytes(cover)
        anteponi_pagine(base, [cover])
        self.assertEqual(base, b0)
        self.assertEqual(cover, c0)

    def test_sostituisci_non_muta_input(self):
        base = _pdf(["COVER", "B1"])
        nuova = _pdf(["MOD"])
        b0, n0 = bytes(base), bytes(nuova)
        sostituisci_prima_pagina(base, nuova)
        self.assertEqual(base, b0)
        self.assertEqual(nuova, n0)
