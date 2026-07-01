"""Test del bulk-attach PDF → Specifica.allegato (intake_export.attacca_pdf)."""
import os
import shutil
import tempfile

from django.test import TestCase, override_settings

from gestione_specifiche.intake_export import attacca_pdf
from gestione_specifiche.models import Specifica


class AttaccaPdfTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "SPEC-1 REV.A.pdf")
        with open(self.src, "wb") as fh:
            fh.write(b"%PDF-1.4 contenuto di prova")
        self.spec = Specifica.objects.create(
            codice="SPEC-1", revisione="A", titolo="t", tipo="specifica", fonte="generica",
        )
        self.priv = os.path.join(self.tmp, "priv")

    def test_dry_run_non_scrive(self):
        # refresh_from_db è vietato dal campo FSM 'stato': si re-fetcha via objects.get.
        with override_settings(GESTIONE_SPECIFICHE_PRIVATE_ROOT=self.priv):
            self.assertEqual(attacca_pdf(self.spec, self.src), "da_allegare")
        self.assertFalse(Specifica.objects.get(pk=self.spec.pk).allegato)

    def test_apply_scrive_e_idempotente(self):
        with override_settings(GESTIONE_SPECIFICHE_PRIVATE_ROOT=self.priv):
            self.assertEqual(attacca_pdf(self.spec, self.src, apply=True), "allegato")
            ricaricata = Specifica.objects.get(pk=self.spec.pk)
            self.assertTrue(ricaricata.allegato.name)
            ricaricata.allegato.open("rb")
            self.assertEqual(ricaricata.allegato.read(), b"%PDF-1.4 contenuto di prova")
            ricaricata.allegato.close()
            # idempotente: la spec in-memory ha già l'allegato → salta
            self.assertEqual(attacca_pdf(self.spec, self.src, apply=True), "gia_allegato")
            # forza → ri-attacca
            self.assertEqual(attacca_pdf(self.spec, self.src, apply=True, forza=True), "allegato")

    def test_file_mancante(self):
        with override_settings(GESTIONE_SPECIFICHE_PRIVATE_ROOT=self.priv):
            self.assertEqual(
                attacca_pdf(self.spec, os.path.join(self.tmp, "nope.pdf")), "file_mancante"
            )
