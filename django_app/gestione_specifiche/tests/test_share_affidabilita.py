"""Share specifiche: share giù non in cache, scrittura esclusiva/atomica, deposito in background."""
import os
import shutil
import tempfile
from unittest.mock import patch

import fitz
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche import cartelle_cliente as cc
from gestione_specifiche import share_write
from gestione_specifiche.composito_deposito import (
    _risolvi_target,
    accoda_deposito_auto,
    deposita,
)
from gestione_specifiche.models import ClienteCartellaShare, Specifica

_RAW = "gestione_specifiche.composito_deposito._leggi_raw"


def _pdf(testo="RAW") -> bytes:
    d = fitz.open()
    d.new_page().insert_text((72, 72), testo)
    b = d.tobytes()
    d.close()
    return b


class ShareGiuTest(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "DUCATI"))
        ClienteCartellaShare.objects.create(cliente="Ducati", cartella="DUCATI")

    def test_share_giu_non_si_mette_in_cache(self):
        assente = os.path.join(self.root, "non-montata")
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[assente]):
            self.assertEqual(cc.risolvi("Ducati"), (None, "share_non_raggiungibile"))
            self.assertFalse(cc.share_raggiungibile())
            self.assertEqual(cc.cartelle_disponibili(), [])
            os.makedirs(os.path.join(assente, "DUCATI"))
            # Tornata su: si legge subito, senza aspettare la scadenza della cache.
            path, fonte = cc.risolvi("Ducati")
        self.assertEqual(fonte, "mappatura")
        self.assertTrue(path.endswith("DUCATI"))

    def test_target_composito_dice_share_non_raggiungibile(self):
        spec = Specifica.objects.create(codice="X-1", revisione="01", titolo="T", cliente="Ducati")
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[os.path.join(self.root, "giu")]):
            self.assertEqual(_risolvi_target(spec, cartella=None), (None, "share_non_raggiungibile"))

    def test_partial_cartella_suggerita_avvisa(self):
        utente = get_user_model().objects.create_superuser("gs_aff", "g@example.invalid", "pwd12345")
        self.client.force_login(utente)
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[os.path.join(self.root, "giu")]):
            r = self.client.get(reverse("gestione_specifiche:cartella_suggerita"), {"cliente": "Ducati"})
        self.assertContains(r, "Share non raggiungibile")
        self.assertContains(r, "DUCATI")  # la mappatura confermata resta


class ScritturaTest(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_scrivi_esclusivo_non_sovrascrive(self):
        p = os.path.join(self.dir, "a.pdf")
        share_write.scrivi_esclusivo(p, b"uno")
        with self.assertRaises(FileExistsError):
            share_write.scrivi_esclusivo(p, b"due")
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), b"uno")

    def test_sostituisci_atomico_non_lascia_temporanei(self):
        p = os.path.join(self.dir, "a.pdf")
        share_write.scrivi_esclusivo(p, b"vecchio")
        share_write.sostituisci_atomico(p, b"nuovo")
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), b"nuovo")
        self.assertEqual(os.listdir(self.dir), ["a.pdf"])

    def test_sostituzione_fallita_lascia_il_vecchio(self):
        p = os.path.join(self.dir, "a.pdf")
        share_write.scrivi_esclusivo(p, b"vecchio")
        with patch("gestione_specifiche.share_write.os.replace", side_effect=OSError("bloccato")):
            with self.assertRaises(OSError):
                share_write.sostituisci_atomico(p, b"nuovo")
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), b"vecchio")
        self.assertEqual(os.listdir(self.dir), ["a.pdf"])


@override_settings(GESTIONE_SPECIFICHE={"PDF_OWNER_PASSWORD": "segreto"})
class DepositoTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.cart = os.path.join(self.root, "DUCATI")
        os.makedirs(self.cart)

    def test_backup_del_rollback_fuori_dalla_cartella_attiva(self):
        spec = Specifica.objects.create(codice="DMH 1", revisione="02", titolo="T", cliente="Ducati")
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]), \
                patch(_RAW, return_value=_pdf()):
            primo = deposita(spec, cartella=self.cart, dry_run=False)
            spec = Specifica.objects.get(pk=spec.pk)
            with patch("gestione_specifiche.composito_deposito.EventoSpecifica.objects.create",
                       side_effect=RuntimeError("db giù")):
                secondo = deposita(spec, dry_run=False)
        self.assertEqual(secondo.esito, "errore")
        self.assertTrue(os.path.isfile(primo.target), "rollback: la forma precedente resta")
        self.assertEqual(sorted(os.listdir(self.cart)), [os.path.basename(primo.target)],
                         "nessun .bak né temporaneo nella cartella del cliente")

    def test_deposito_auto_accodato_a_transazione_confermata(self):
        spec = Specifica.objects.create(codice="DMH 2", revisione="01", titolo="T", cliente="Ducati")
        with override_settings(GESTIONE_SPECIFICHE_COMPOSITO_AUTO=False):
            self.assertFalse(accoda_deposito_auto(spec))
        with override_settings(GESTIONE_SPECIFICHE_COMPOSITO_AUTO=True), \
                patch("django_q.tasks.async_task") as accoda, \
                self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(accoda_deposito_auto(spec))
        accoda.assert_called_once()
        self.assertEqual(accoda.call_args[0][:2],
                         ("gestione_specifiche.composito_deposito.esegui_deposito_auto", spec.pk))
