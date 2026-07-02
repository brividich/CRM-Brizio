"""Test del detector/inventario PDF (management command analizza_pdf_specifiche, MOD.133 F1).

Costruisce PDF SINTETICI con fitz (nessun dato cliente reale) contenenti i marker di
ogni classe in una share-root temporanea (override_settings), crea Specifiche collegate
dentro/fuori allowlist e verifica la classificazione nel CSV e i conteggi.
"""
import csv
import os
import shutil
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from gestione_specifiche.models import Specifica


def _crea_pdf(path: str, testi) -> None:
    """Scrive un PDF con una pagina per riga di testo. `testi` vuoto => pagina senza testo."""
    import fitz

    doc = fitz.open()
    if not testi:
        doc.new_page()  # pagina vuota => nessun testo estraibile (classe 'incerto')
    else:
        for t in testi:
            page = doc.new_page()
            page.insert_text((72, 100), t, fontsize=11)
    doc.save(path)
    doc.close()


class AnalizzaPdfTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        # cartella FUORI allowlist per il caso 'irraggiungibile'
        self.fuori = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.fuori, ignore_errors=True)

        self.pdf_mod133 = os.path.join(self.root, "mod133.pdf")
        self.pdf_cover = os.path.join(self.root, "cover.pdf")
        self.pdf_senza = os.path.join(self.root, "senza.pdf")
        self.pdf_incerto = os.path.join(self.root, "incerto.pdf")
        self.pdf_fuori = os.path.join(self.fuori, "fuori.pdf")

        _crea_pdf(self.pdf_mod133, [
            "TABELLA DI VERIFICA DEI NUOVI REQUISITI",
            "FLOW DOWN FOR NEW REQUIREMENTS",
        ])
        _crea_pdf(self.pdf_cover, ["SPECIFICA IN ATTESA DI COMPILAZIONE MOD.133"])
        _crea_pdf(self.pdf_senza, ["Documento generico senza alcun marker riconoscibile"])
        _crea_pdf(self.pdf_incerto, [])  # pagina vuota
        _crea_pdf(self.pdf_fuori, ["TABELLA DI VERIFICA DEI NUOVI REQUISITI"])

        self.specs = {
            "MOD133": self._spec("MOD133", self.pdf_mod133),
            "COVER": self._spec("COVER", self.pdf_cover),
            "SENZA": self._spec("SENZA", self.pdf_senza),
            "INCERTO": self._spec("INCERTO", self.pdf_incerto),
            "FUORI": self._spec("FUORI", self.pdf_fuori),
        }

    def _spec(self, codice, percorso):
        return Specifica.objects.create(
            codice=codice, revisione="A", titolo="t", tipo="specifica",
            fonte="generica", percorso_esterno=percorso,
        )

    def _run(self, *extra):
        out_csv = os.path.join(self.root, "report.csv")
        buf = StringIO()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            call_command("analizza_pdf_specifiche", "--out", out_csv, *extra, stdout=buf)
        with open(out_csv, newline="", encoding="utf-8-sig") as fh:
            righe = list(csv.DictReader(fh, delimiter=";"))
        return {r["codice"]: r for r in righe}, buf.getvalue()

    def test_classificazione_per_classe_e_csv(self):
        per_codice, output = self._run()
        self.assertEqual(per_codice["MOD133"]["classe"], "mod133")
        self.assertEqual(per_codice["COVER"]["classe"], "cover_attesa")
        self.assertEqual(per_codice["SENZA"]["classe"], "senza")
        self.assertEqual(per_codice["INCERTO"]["classe"], "incerto")
        # PDF fuori dalla allowlist -> irraggiungibile (mai aperto)
        self.assertEqual(per_codice["FUORI"]["classe"], "irraggiungibile")
        # colonne del report (incl. prima_pagina + flag promuovibile)
        for r in per_codice.values():
            self.assertEqual(
                set(r.keys()),
                {"pk", "codice", "revisione", "classe", "prima_pagina", "promuovibile",
                 "pagine", "path", "note"},
            )
        # SENZA: prima pagina = contenuto -> raw pristino promuovibile
        self.assertEqual(per_codice["SENZA"]["prima_pagina"], "senza")
        self.assertEqual(per_codice["SENZA"]["promuovibile"], "si")
        # COVER: prima pagina = cover -> NON promuovibile (gia' compositato)
        self.assertEqual(per_codice["COVER"]["prima_pagina"], "cover_attesa")
        self.assertEqual(per_codice["COVER"]["promuovibile"], "")
        # il riepilogo a console riporta i conteggi per classe
        self.assertIn("mod133", output)
        self.assertIn("irraggiungibile", output)

    def test_conteggio_riepilogo(self):
        per_codice, output = self._run()
        classi = [r["classe"] for r in per_codice.values()]
        self.assertEqual(classi.count("mod133"), 1)
        self.assertEqual(classi.count("cover_attesa"), 1)
        self.assertEqual(classi.count("senza"), 1)
        self.assertEqual(classi.count("incerto"), 1)
        self.assertEqual(classi.count("irraggiungibile"), 1)
        self.assertIn("analizzate: 5", output)

    def test_mod133_ha_precedenza_su_cover(self):
        # PDF composito: cover + pagina MOD.133 -> classificato 'mod133'.
        composito = os.path.join(self.root, "composito.pdf")
        _crea_pdf(composito, [
            "SPECIFICA IN ATTESA DI COMPILAZIONE MOD.133",
            "TABELLA DI VERIFICA DEI NUOVI REQUISITI",
        ])
        Specifica.objects.create(
            codice="COMPOSITO", revisione="A", titolo="t", tipo="specifica",
            fonte="generica", percorso_esterno=composito,
        )
        per_codice, _ = self._run()
        self.assertEqual(per_codice["COMPOSITO"]["classe"], "mod133")

    def test_irraggiungibile_file_mancante(self):
        mancante = os.path.join(self.root, "mancante.pdf")  # dentro allowlist ma inesistente
        Specifica.objects.create(
            codice="MANCA", revisione="A", titolo="t", tipo="specifica",
            fonte="generica", percorso_esterno=mancante,
        )
        per_codice, _ = self._run()
        self.assertEqual(per_codice["MANCA"]["classe"], "irraggiungibile")

    def test_limit(self):
        out_csv = os.path.join(self.root, "report_limit.csv")
        buf = StringIO()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            call_command("analizza_pdf_specifiche", "--out", out_csv, "--limit", "2", stdout=buf)
        with open(out_csv, newline="", encoding="utf-8-sig") as fh:
            righe = list(csv.DictReader(fh, delimiter=";"))
        self.assertEqual(len(righe), 2)

    def test_ocr_flag_non_crash_su_incerto(self):
        # Con --ocr il PDF 'incerto' resta 'incerto' se il motore OCR non c'e' (nessun crash).
        per_codice, _ = self._run("--ocr")
        self.assertEqual(per_codice["INCERTO"]["classe"], "incerto")
        self.assertTrue(per_codice["INCERTO"]["note"])  # nota esplicativa presente

    def test_marker_multiriga_riconosciuti(self):
        # La cover/MOD.133 reali hanno il testo su piu' righe (celle di tabella): la
        # normalizzazione (whitespace collassato) deve comunque riconoscerli. Fixture
        # con marker spezzati su piu' righe, non pre-uniti.
        cover_ml = os.path.join(self.root, "cover_ml.pdf")
        _crea_pdf(cover_ml, ["SPECIFICA IN ATTESA\nDI COMPILAZIONE\nMOD.133"])
        Specifica.objects.create(
            codice="COVERML", revisione="A", titolo="t", tipo="specifica",
            fonte="generica", percorso_esterno=cover_ml,
        )
        mod_ml = os.path.join(self.root, "mod_ml.pdf")
        _crea_pdf(mod_ml, ["TABELLA DI VERIFICA\nDEI NUOVI REQUISITI"])
        Specifica.objects.create(
            codice="MODML", revisione="A", titolo="t", tipo="specifica",
            fonte="generica", percorso_esterno=mod_ml,
        )
        per_codice, _ = self._run()
        self.assertEqual(per_codice["COVERML"]["classe"], "cover_attesa")
        self.assertEqual(per_codice["MODML"]["classe"], "mod133")
