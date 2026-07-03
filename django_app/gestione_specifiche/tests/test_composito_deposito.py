"""Test F6b-2 - deposito del composito controllato sulla share (dry-run / apply / swap / gating).

PDF sintetici, share simulata in una cartella temporanea. L'originale RAW e' mockato (l'allegato
cifrato non e' oggetto di questi test): si verifica la logica di deposito/scambio/backup/audit.
"""
import os
import shutil
import tempfile
from unittest.mock import patch

import fitz
from cryptography.fernet import Fernet
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from gestione_specifiche import constants as C
from gestione_specifiche.composito_deposito import (
    FORMA_APPROVATO,
    FORMA_ATTESA,
    deposita,
    deposita_auto,
    forma_corrente,
)
from gestione_specifiche.models import EventoSpecifica, MOD133, Specifica

_RAW = "gestione_specifiche.composito_deposito._leggi_raw"


def _pdf(pagine):
    doc = fitz.open()
    try:
        for t in pagine:
            doc.new_page().insert_text((72, 72), t)
        return doc.tobytes()
    finally:
        doc.close()


@override_settings(GESTIONE_SPECIFICHE={"PDF_OWNER_PASSWORD": "segreto"})
class DepositoCompositoTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.cart = os.path.join(self.root, "DUCATI")
        os.makedirs(self.cart)

    def _spec(self, **kw):
        return Specifica.objects.create(codice="DMH 00-04.002", revisione="02",
                                        titolo="T", cliente="Ducati", **kw)

    def test_dryrun_non_scrive(self):
        spec = self._spec()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]), \
                patch(_RAW, return_value=_pdf(["RAW"])):
            piano = deposita(spec, cartella=self.cart, dry_run=True)
        self.assertEqual(piano.esito, "ok")
        self.assertEqual(piano.forma, FORMA_ATTESA)
        self.assertGreater(piano.dimensione, 0)
        self.assertEqual(os.listdir(self.cart), [])  # dry-run: niente scritto

    def test_apply_scrive_protetto_e_audit(self):
        spec = self._spec()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]), \
                patch(_RAW, return_value=_pdf(["RAW"])):
            piano = deposita(spec, cartella=self.cart, dry_run=False)
        self.assertEqual(piano.esito, "ok")
        self.assertTrue(os.path.isfile(piano.target))
        d = fitz.open(piano.target)
        try:
            self.assertTrue(d.metadata.get("encryption"))   # composito protetto
            self.assertGreaterEqual(d.page_count, 2)         # cover + raw
        finally:
            d.close()
        spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protegge refresh_from_db)
        self.assertEqual(spec.percorso_esterno, piano.target)
        self.assertTrue(EventoSpecifica.objects.filter(
            specifica=spec, trigger="deposito_composito_share").exists())

    def test_deposita_con_allegato_reale_cifrato(self):
        # NON mockato: allegato REALE nello storage CIFRATO -> deposita deve leggere+decifrare+scrivere.
        # (Avrebbe preso il bug "originale_mancante": lettura sbagliata dell'allegato cifrato.)
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        spec = Specifica.objects.create(codice="ENC-1", revisione="0", titolo="t")
        with override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                               GESTIONE_SPECIFICHE_PRIVATE_ROOT=media,
                               GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            spec.allegato.save("enc.pdf", ContentFile(_pdf(["RAW-CIFRATO"])), save=False)
            Specifica.objects.filter(pk=spec.pk).update(allegato=spec.allegato.name)
            spec = Specifica.objects.get(pk=spec.pk)
            piano = deposita(spec, cartella=self.cart, dry_run=False)
        self.assertEqual(piano.esito, "ok")
        self.assertTrue(os.path.isfile(piano.target))

    def test_apply_legge_il_raw_una_sola_volta(self):
        # Regressione: l'allegato cifrato non e' ri-leggibile 2 volte nello stesso processo ->
        # il deposito deve leggere/generare il composito UNA sola volta (bug "originale non disponibile").
        spec = self._spec()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]), \
                patch(_RAW, return_value=_pdf(["RAW"])) as m:
            piano = deposita(spec, cartella=self.cart, dry_run=False)
        self.assertEqual(piano.esito, "ok")
        self.assertEqual(m.call_count, 1)

    def test_swap_attesa_poi_approvato(self):
        spec = self._spec()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]), \
                patch(_RAW, return_value=_pdf(["RAW1", "RAW2"])):
            deposita(spec, cartella=self.cart, dry_run=False)       # forma attesa
            spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protegge refresh_from_db)
            MOD133.objects.create(specifica=spec, esito=C.ESITO_APPROVATO)
            self.assertEqual(forma_corrente(spec), FORMA_APPROVATO)
            piano2 = deposita(spec, dry_run=False)                  # riusa percorso_esterno (scambio)
        self.assertEqual(piano2.esito, "ok")
        self.assertEqual(piano2.forma, FORMA_APPROVATO)
        # backup rimosso dopo il successo: nessun .bak residuo
        self.assertFalse([f for f in os.listdir(self.cart) if ".bak-" in f])

    def test_owner_pw_mancante(self):
        spec = self._spec()
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root],
                               GESTIONE_SPECIFICHE={"PDF_OWNER_PASSWORD": ""}), \
                patch(_RAW, return_value=_pdf(["RAW"])):
            piano = deposita(spec, cartella=self.cart, dry_run=True)
        self.assertEqual(piano.esito, "owner_pw_mancante")

    def test_originale_mancante(self):
        spec = self._spec()  # nessun allegato -> _leggi_raw reale ritorna None
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            piano = deposita(spec, cartella=self.cart, dry_run=True)
        self.assertEqual(piano.esito, "originale_mancante")

    def test_deposita_auto_gated(self):
        spec = self._spec()
        # flag OFF -> no-op
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root],
                               GESTIONE_SPECIFICHE_COMPOSITO_AUTO=False), \
                patch(_RAW, return_value=_pdf(["RAW"])):
            self.assertIsNone(deposita_auto(spec))
        # prepara una destinazione, poi flag ON -> deposita
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]), \
                patch(_RAW, return_value=_pdf(["RAW"])):
            deposita(spec, cartella=self.cart, dry_run=False)
            spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protegge refresh_from_db)
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root],
                               GESTIONE_SPECIFICHE_COMPOSITO_AUTO=True), \
                patch(_RAW, return_value=_pdf(["RAW"])):
            dep = deposita_auto(spec)
        self.assertIsNotNone(dep)
        self.assertEqual(dep.esito, "ok")
