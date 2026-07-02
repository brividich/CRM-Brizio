"""Test mappatura Cliente -> cartella share: ricerca/suggerimento, risoluzione, seed, aggancio F6b-2."""
import os
import shutil
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from gestione_specifiche import cartelle_cliente as cc
from gestione_specifiche.composito_deposito import _risolvi_target
from gestione_specifiche.models import ClienteCartellaShare, Specifica


class CartelleClienteTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for f in ("DUCATI", "FERRARI - FERRARI GES", "GE AVIO AERO"):
            os.makedirs(os.path.join(self.root, f))

    def _ctx(self):
        return override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root])

    def test_suggerisci_match_lessicale(self):
        with self._ctx():
            self.assertEqual(cc.suggerisci("Ducati")[0], "DUCATI")
            self.assertIn("FERRARI - FERRARI GES", cc.suggerisci("Ferrari"))
            self.assertEqual(cc.suggerisci("Cliente Sconosciuto"), [])

    def test_risolvi_mappato(self):
        ClienteCartellaShare.objects.create(cliente="Ducati", cartella="DUCATI")
        with self._ctx():
            path, fonte = cc.risolvi("Ducati")
        self.assertEqual(fonte, "mappatura")
        self.assertTrue(path and path.endswith("DUCATI"))

    def test_risolvi_non_mappato(self):
        with self._ctx():
            self.assertEqual(cc.risolvi("Pincopallo")[1], "nessuna")

    def test_risolvi_cartella_mancante(self):
        ClienteCartellaShare.objects.create(cliente="Ducati", cartella="CARTELLA_INESISTENTE")
        with self._ctx():
            self.assertEqual(cc.risolvi("Ducati"), (None, "cartella_mancante"))

    def test_seed_da_percorsi_reali(self):
        Specifica.objects.create(codice="A", titolo="t", cliente="Ducati",
                                 percorso_esterno=os.path.join(self.root, "DUCATI", "A REV.0.pdf"))
        Specifica.objects.create(codice="B", titolo="t", cliente="Ferrari",
                                 percorso_esterno=os.path.join(self.root, "FERRARI - FERRARI GES", "B REV.0.pdf"))
        buf = StringIO()
        with self._ctx():
            call_command("seed_cartelle_cliente", "--apply", stdout=buf)
        self.assertEqual(ClienteCartellaShare.objects.get(cliente="Ducati").cartella, "DUCATI")
        self.assertEqual(ClienteCartellaShare.objects.get(cliente="Ferrari").cartella, "FERRARI - FERRARI GES")

    def test_seed_dryrun_non_salva(self):
        Specifica.objects.create(codice="A", titolo="t", cliente="Ducati",
                                 percorso_esterno=os.path.join(self.root, "DUCATI", "A REV.0.pdf"))
        with self._ctx():
            call_command("seed_cartelle_cliente", stdout=StringIO())
        self.assertEqual(ClienteCartellaShare.objects.count(), 0)

    def test_f6b2_usa_mappatura_per_nuova_spec(self):
        ClienteCartellaShare.objects.create(cliente="Ducati", cartella="DUCATI")
        spec = Specifica.objects.create(codice="NEW-1", revisione="0", titolo="t", cliente="Ducati")
        with self._ctx():
            target, motivo = _risolvi_target(spec, cartella=None)  # nessun file share collegato
        self.assertEqual(motivo, "ok")
        self.assertTrue(target and "DUCATI" in target and target.endswith(".pdf"))

    def test_f6b2_nuova_spec_senza_mappatura(self):
        spec = Specifica.objects.create(codice="NEW-2", revisione="0", titolo="t", cliente="ClienteNuovo")
        with self._ctx():
            self.assertEqual(_risolvi_target(spec, cartella=None), (None, "cartella_richiesta"))
