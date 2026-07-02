"""Test comando A - importa_raw_allegato_da_share: promuove SOLO i raw pristini, dry-run/apply/idempotenza.

Share simulata in cartella temporanea; la scrittura dell'allegato cifrato e' mockata (storage.save).
"""
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

import fitz
from django.core.management import call_command
from django.test import TestCase, override_settings

from gestione_specifiche.models import EventoSpecifica, Specifica


def _crea_pdf(path, testi):
    doc = fitz.open()
    try:
        for t in testi:
            doc.new_page().insert_text((72, 100), t, fontsize=11)
        doc.save(path)
    finally:
        doc.close()


class ImportaRawTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.p_raw = os.path.join(self.root, "DMH 00-04.002 REV.02.pdf")
        self.p_cover = os.path.join(self.root, "COVER REV.A.pdf")
        _crea_pdf(self.p_raw, ["Documento cliente senza marker riconoscibile", "seconda pagina"])
        _crea_pdf(self.p_cover, ["SPECIFICA IN ATTESA DI COMPILAZIONE MOD.133", "contenuto"])
        self.raw = Specifica.objects.create(codice="RAW", revisione="02", titolo="t",
                                            percorso_esterno=self.p_raw)
        self.cover = Specifica.objects.create(codice="COVER", revisione="A", titolo="t",
                                              percorso_esterno=self.p_cover)

    def _run(self, *extra):
        buf = StringIO()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            call_command("importa_raw_allegato_da_share", *extra, stdout=buf)
        return buf.getvalue()

    def test_dryrun_seleziona_solo_pristino(self):
        out = self._run()
        self.assertIn("PROMUOVI", out)
        self.assertIn("RAW", out)
        self.assertIn("promuovibili: 1", out)
        self.assertIn("non-pristino", out)  # la cover e' saltata
        # nessuna scrittura in dry-run
        self.assertFalse(Specifica.objects.get(pk=self.raw.pk).allegato)
        self.assertEqual(EventoSpecifica.objects.filter(trigger="importa_raw_allegato").count(), 0)

    def test_apply_promuove_raw_e_audit(self):
        storage = Specifica._meta.get_field("allegato").storage
        with patch.object(storage, "save", return_value="specifiche/raw_fake.pdf"):
            self._run("--apply")
        raw = Specifica.objects.get(pk=self.raw.pk)
        self.assertEqual(raw.allegato.name, "specifiche/raw_fake.pdf")
        self.assertTrue(EventoSpecifica.objects.filter(
            specifica=raw, trigger="importa_raw_allegato").exists())
        self.assertFalse(Specifica.objects.get(pk=self.cover.pk).allegato)  # cover NON promossa

    def test_idempotente_salta_chi_ha_allegato(self):
        Specifica.objects.filter(pk=self.raw.pk).update(allegato="specifiche/gia.pdf")
        out = self._run("--apply")
        self.assertIn("promuovibili: 0", out)
