"""Test F6a — composito ufficiale (offline): mapping dati MOD.133, [MOD.133]+[originale],
protezione. PDF sintetici, nessuna scrittura sulla share.
"""
import os
import shutil
import tempfile

import fitz
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from gestione_specifiche.composito import (
    componi_composito_da_spec,
    componi_composito_ufficiale,
    dati_mod133_da_spec,
    _leggi_pdf_originale,
)
from gestione_specifiche.mod133_render import render_mod133
from gestione_specifiche.models import MOD133, RigaMOD133, Specifica

User = get_user_model()


def _pdf(pagine):
    doc = fitz.open()
    try:
        for t in pagine:
            doc.new_page().insert_text((72, 72), t)
        return doc.tobytes()
    finally:
        doc.close()


def _npag(b):
    d = fitz.open(stream=b, filetype="pdf")
    try:
        return d.page_count
    finally:
        d.close()


class DatiMod133Test(TestCase):
    def test_mapping_da_spec(self):
        u1 = User.objects.create_user("comp_c", "c@x.it", "x")
        u2 = User.objects.create_user("appr_a", "a@x.it", "x")
        spec = Specifica.objects.create(codice="C1", revisione="B", titolo="Trattamento",
                                        cliente="FINCANTIERI", fonte="cliente", note="nota")
        mod = MOD133.objects.create(specifica=spec, compilatore=u1, approvatore=u2)
        RigaMOD133.objects.create(
            mod133=mod, ordine=1, rif_paragrafo="3.2", argomento="Tolleranze",
            descrizione_modifiche="Rev toll", descrizione_impatto="Aggiornare MT",
            rif_doc_cn="MT CN 06", rif_paragrafo_cn="4.1",
            impatto_documenti=True, impatto_operativo=False,
        )
        dati = dati_mod133_da_spec(spec)
        self.assertEqual(dati["fonte"], "FINCANTIERI")
        self.assertIn("C1 Rev.B", dati["documento_analizzato"])
        self.assertEqual(dati["documenti_cn_interessati"], "MT CN 06")
        self.assertEqual(len(dati["righe"]), 1)
        r = dati["righe"][0]
        self.assertEqual(r["paragrafi"], "3.2")
        self.assertEqual(r["argomenti"], "Tolleranze")
        self.assertEqual(r["impatto_doc"], "SI")
        self.assertEqual(r["impatto_operativo"], "NO")
        self.assertEqual(r["argomenti_cn"], "Rev toll")   # descrizione_modifiche
        self.assertEqual(r["impatto_doc_desc"], "Aggiornare MT")
        self.assertEqual(dati["revisore"], "comp_c")       # username (no full name)
        self.assertEqual(dati["approvatore"], "appr_a")

    def test_spec_senza_mod133(self):
        spec = Specifica.objects.create(codice="C2", titolo="T")
        dati = dati_mod133_da_spec(spec)
        self.assertEqual(dati["righe"], [])
        self.assertEqual(dati["revisore"], "")


class ComponiCompositoTest(TestCase):
    def test_pagine_e_protezione(self):
        spec = Specifica.objects.create(codice="C3", revisione="0", titolo="T")
        MOD133.objects.create(specifica=spec)
        orig = _pdf(["ORIG-1", "ORIG-2"])
        comp = componi_composito_da_spec(spec, originale=orig, owner_password="segreto")
        self.assertTrue(comp.startswith(b"%PDF"))
        # pagine composito = pagine MOD.133 + pagine originale (2)
        mod_pag = _npag(render_mod133(dati_mod133_da_spec(spec)))
        self.assertEqual(_npag(comp), mod_pag + 2)
        # protetto: nega stampa/modifica e apre senza password (user_pw vuota)
        d = fitz.open(stream=comp, filetype="pdf")
        try:
            self.assertFalse(d.needs_pass)
            self.assertEqual(d.permissions & fitz.PDF_PERM_PRINT, 0)
            self.assertEqual(d.permissions & fitz.PDF_PERM_MODIFY, 0)
        finally:
            d.close()

    def test_senza_protezione(self):
        comp = componi_composito_ufficiale(_pdf(["O"]), {"righe": []}, proteggi=False)
        d = fitz.open(stream=comp, filetype="pdf")
        try:
            self.assertFalse(d.metadata.get("encryption"))
        finally:
            d.close()

    def test_owner_password_dai_settings(self):
        spec = Specifica.objects.create(codice="C3b", titolo="T")
        MOD133.objects.create(specifica=spec)
        with override_settings(GESTIONE_SPECIFICHE={"PDF_OWNER_PASSWORD": "dal-env"}):
            comp = componi_composito_da_spec(spec, originale=_pdf(["O"]))  # owner_password non passata
        d = fitz.open(stream=comp, filetype="pdf")
        try:
            self.assertTrue(d.metadata.get("encryption"))
            self.assertEqual(d.permissions & fitz.PDF_PERM_PRINT, 0)
        finally:
            d.close()

    def test_originale_mancante_solleva(self):
        spec = Specifica.objects.create(codice="C5", titolo="T")  # ne allegato ne percorso
        with self.assertRaises(ValueError):
            componi_composito_da_spec(spec)
        with self.assertRaises(ValueError):
            componi_composito_ufficiale(b"", {})

    def test_legge_originale_da_share(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        p = os.path.join(root, "X REV.0.pdf")
        with open(p, "wb") as fh:
            fh.write(_pdf(["SHARE-ORIG"]))
        spec = Specifica.objects.create(codice="C6", titolo="T", percorso_esterno=p)
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[root]):
            b = _leggi_pdf_originale(spec)
        self.assertTrue(b and b.startswith(b"%PDF"))
