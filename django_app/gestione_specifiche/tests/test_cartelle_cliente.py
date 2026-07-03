"""Test mappatura Cliente -> cartella share: ricerca/suggerimento, risoluzione, seed, aggancio F6b-2."""
import os
import shutil
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche import cartelle_cliente as cc
from gestione_specifiche.composito_deposito import _risolvi_target
from gestione_specifiche.models import ClienteCartellaShare, Specifica


class CartelleClienteTest(TestCase):
    def setUp(self):
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for f in ("DUCATI", "FERRARI - FERRARI GES", "GE AVIO AERO"):
            os.makedirs(os.path.join(self.root, f))
        # sotto-cartella dentro un cliente (le cartelle cliente hanno sotto-cartelle)
        self.sub = os.path.join("FERRARI - FERRARI GES", "Motori")
        os.makedirs(os.path.join(self.root, self.sub))

    def _ctx(self):
        return override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root])

    def test_include_sottocartelle(self):
        with self._ctx():
            disp = cc.cartelle_disponibili()
        self.assertIn("FERRARI - FERRARI GES", disp)
        self.assertIn(self.sub, disp)   # cliente\sottocartella presente (depth 2 default)

    def test_risolvi_sottocartella(self):
        ClienteCartellaShare.objects.create(cliente="Ferrari Motori", cartella=self.sub)
        with self._ctx():
            path, fonte = cc.risolvi("Ferrari Motori")
        self.assertEqual(fonte, "mappatura")
        self.assertTrue(path and path.endswith(self.sub))

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


class CartellaSuggeritaViewTest(TestCase):
    """Fase 2: endpoint HTMX + salvataggio (conferma) della mappatura dal form."""

    def setUp(self):
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for f in ("DUCATI", "FERRARI - FERRARI GES"):
            os.makedirs(os.path.join(self.root, f))
        self.su = get_user_model().objects.create_superuser("cs_su", "a@x.it", "x")
        self.client.force_login(self.su)

    def _ctx(self):
        return override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root])

    def test_endpoint_cliente_mappato(self):
        ClienteCartellaShare.objects.create(cliente="Ducati", cartella="DUCATI")
        with self._ctx():
            r = self.client.get(reverse("gestione_specifiche:cartella_suggerita"), {"cliente": "Ducati"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "già in memoria")
        self.assertContains(r, "DUCATI")

    def test_endpoint_cliente_nuovo_suggerisce(self):
        with self._ctx():
            r = self.client.get(reverse("gestione_specifiche:cartella_suggerita"), {"cliente": "Ferrari"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "cartella_share")            # menu presente
        self.assertContains(r, "FERRARI - FERRARI GES")     # suggerita

    def test_endpoint_cliente_vuoto(self):
        r = self.client.get(reverse("gestione_specifiche:cartella_suggerita"), {"cliente": ""})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "cartella_share")

    def test_nuova_specifica_conferma_mappatura(self):
        with self._ctx():
            r = self.client.post(reverse("gestione_specifiche:nuova"), {
                "codice": "NEW-X", "revisione": "0", "titolo": "T",
                "tipo": "specifica", "fonte": "cliente", "cliente": "Ducati",
                "tag": "", "note": "", "commessa_ref": "", "famiglia_ref": "",
                "cartella_share": "DUCATI",
            })
        self.assertEqual(r.status_code, 302)  # creata -> redirect
        self.assertTrue(ClienteCartellaShare.objects.filter(cliente="Ducati", cartella="DUCATI").exists())
