"""Test F2 - deposito nuova revisione sulla share (share_write): dry-run, supersessione,
collisioni (identico/diverso/forza), rollback. Nessun dato reale: file PDF sintetici in una
share-root temporanea via override_settings.
"""
import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from gestione_specifiche.models import EventoSpecifica, Specifica
from gestione_specifiche import share_write
from gestione_specifiche.share_write import (
    elenca_cartelle_consentite,
    esegui,
    nome_canonico,
    pianifica,
    valida_cartella_destinazione,
    _sanitizza_nome,
)


@override_settings(GESTIONE_SPECIFICHE_SHARE_EXCLUDE=["_SUPERATO"])
class ShareWriteBase(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.cliente_dir = os.path.join(self.root, "FERRARI 359")
        os.makedirs(self.cliente_dir)
        os.makedirs(os.path.join(self.root, "_SUPERATO"))
        self._settings = override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root])
        self._settings.enable()
        self.addCleanup(self._settings.disable)

    def _file(self, path, dati=b"%PDF-1.4 vecchio"):
        with open(path, "wb") as fh:
            fh.write(dati)
        return path

    def _spec(self, codice="X", revisione="B", percorso=""):
        return Specifica.objects.create(
            codice=codice, revisione=revisione, titolo="t", tipo="specifica",
            fonte="generica", percorso_esterno=percorso,
        )


class NamingTest(TestCase):
    def test_nome_canonico(self):
        self.assertEqual(nome_canonico("ABC-123", "B"), "ABC-123 REV.B.pdf")
        self.assertEqual(nome_canonico("ABC-123", ""), "ABC-123.pdf")

    def test_sanitizza_nome(self):
        # caratteri illegali -> '_'; spazio/punto finale rimossi
        self.assertEqual(_sanitizza_nome("A/B:C*?"), "A_B_C__")
        self.assertEqual(_sanitizza_nome("nome . "), "nome")


class CartelleTest(ShareWriteBase):
    def test_elenca_esclude_superato(self):
        etichette = {c["label"] for c in elenca_cartelle_consentite()}
        self.assertIn("FERRARI 359", etichette)
        self.assertIn("(radice)", etichette)
        self.assertNotIn("_SUPERATO", etichette)

    def test_valida_cartella(self):
        self.assertIsNotNone(valida_cartella_destinazione(self.cliente_dir))
        # _SUPERATO escluso
        self.assertIsNone(valida_cartella_destinazione(os.path.join(self.root, "_SUPERATO")))
        # inesistente
        self.assertIsNone(valida_cartella_destinazione(os.path.join(self.root, "NON_ESISTE")))
        # fuori allowlist
        fuori = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, fuori, ignore_errors=True)
        self.assertIsNone(valida_cartella_destinazione(fuori))


class SupersessioneTest(ShareWriteBase):
    def setUp(self):
        super().setUp()
        self.vecchio = self._file(os.path.join(self.cliente_dir, "X REV.A.pdf"))
        self.spec = self._spec(codice="X", revisione="B", percorso=self.vecchio)

    def test_dry_run_non_scrive(self):
        piano = pianifica(self.spec, b"%PDF-1.4 nuovo")
        self.assertEqual(piano.esito, "ok")
        self.assertTrue(piano.target.endswith("X REV.B.pdf"))
        self.assertEqual(share_write._real_nc(piano.sposta_da), share_write._real_nc(self.vecchio))
        self.assertIn("_SUPERATO", piano.sposta_a)
        # nessuna scrittura in dry-run
        self.assertFalse(os.path.exists(piano.target))
        self.assertTrue(os.path.isfile(self.vecchio))

    def test_apply_deposita_e_supera(self):
        piano = esegui(self.spec, b"%PDF-1.4 nuovo", apply=True)
        self.assertEqual(piano.esito, "ok")
        # nuovo file presente
        self.assertTrue(os.path.isfile(piano.target))
        with open(piano.target, "rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.4 nuovo")
        # vecchio spostato in _SUPERATO (non piu' nella posizione attiva)
        self.assertFalse(os.path.exists(self.vecchio))
        self.assertTrue(os.path.isfile(piano.sposta_a))
        self.assertIn("_SUPERATO", piano.sposta_a)
        # collegamento aggiornato (via update, niente FSM)
        self.assertEqual(Specifica.objects.get(pk=self.spec.pk).percorso_esterno, piano.target)
        # audit immutabile creato
        ev = EventoSpecifica.objects.filter(specifica=self.spec, trigger="deposito_revisione_share")
        self.assertEqual(ev.count(), 1)
        self.assertEqual(ev.first().payload["target"], piano.target)


class NuovaSpecificaTest(ShareWriteBase):
    def test_senza_percorso_richiede_cartella(self):
        spec = self._spec(codice="Y", revisione="0", percorso="")
        piano = pianifica(spec, b"%PDF nuovo")
        self.assertEqual(piano.esito, "cartella_richiesta")

    def test_cartella_esplicita_deposita(self):
        spec = self._spec(codice="Y", revisione="0", percorso="")
        piano = esegui(spec, b"%PDF nuovo", cartella=self.cliente_dir, apply=True)
        self.assertEqual(piano.esito, "ok")
        self.assertTrue(piano.target.endswith("Y REV.0.pdf"))
        self.assertTrue(os.path.isfile(piano.target))
        self.assertEqual(piano.sposta_da, "")  # niente da superare
        self.assertEqual(Specifica.objects.get(pk=spec.pk).percorso_esterno, piano.target)


class CollisioneTest(ShareWriteBase):
    def setUp(self):
        super().setUp()
        # il file corrente E' gia' al path canonico (stesso codice+rev): caso replace
        self.target_path = os.path.join(self.cliente_dir, "Z REV.C.pdf")
        self._file(self.target_path, dati=b"%PDF-1.4 esistente")
        self.spec = self._spec(codice="Z", revisione="C", percorso=self.target_path)

    def test_identico_e_noop(self):
        piano = esegui(self.spec, b"%PDF-1.4 esistente", apply=True)
        self.assertEqual(piano.esito, "identico")
        # nessun nuovo evento, file intatto
        self.assertEqual(EventoSpecifica.objects.filter(specifica=self.spec, trigger="deposito_revisione_share").count(), 0)
        with open(self.target_path, "rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.4 esistente")

    def test_diverso_senza_forza_rifiuta(self):
        piano = esegui(self.spec, b"%PDF-1.4 DIVERSO", apply=True)
        self.assertEqual(piano.esito, "collisione")
        # non ha scritto: il file esistente e' intatto
        with open(self.target_path, "rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.4 esistente")

    def test_diverso_con_forza_archivia_e_scrive(self):
        piano = esegui(self.spec, b"%PDF-1.4 DIVERSO", forza=True, apply=True)
        self.assertEqual(piano.esito, "ok")
        self.assertTrue(os.path.isfile(piano.target))
        with open(piano.target, "rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.4 DIVERSO")
        # l'esistente e' stato archiviato in _SUPERATO
        self.assertIn("_SUPERATO", piano.collisione_a)
        self.assertTrue(os.path.isfile(piano.collisione_a))


class RollbackTest(ShareWriteBase):
    def setUp(self):
        super().setUp()
        self.vecchio = self._file(os.path.join(self.cliente_dir, "R REV.A.pdf"))
        self.spec = self._spec(codice="R", revisione="B", percorso=self.vecchio)

    def test_rollback_su_errore_ripristina_tutto(self):
        # forza un errore DOPO gli spostamenti file (creazione audit) e verifica il rollback.
        with mock.patch.object(EventoSpecifica.objects, "create", side_effect=RuntimeError("boom")):
            piano = esegui(self.spec, b"%PDF nuovo", apply=True)
        self.assertEqual(piano.esito, "errore")
        # il nuovo file e' stato rimosso
        self.assertFalse(os.path.exists(os.path.join(self.cliente_dir, "R REV.B.pdf")))
        # il vecchio e' tornato al suo posto (non resta in _SUPERATO)
        self.assertTrue(os.path.isfile(self.vecchio))
        # il collegamento NON e' cambiato
        self.assertEqual(Specifica.objects.get(pk=self.spec.pk).percorso_esterno, self.vecchio)
        # nessun evento persistito
        self.assertEqual(EventoSpecifica.objects.filter(specifica=self.spec, trigger="deposito_revisione_share").count(), 0)
