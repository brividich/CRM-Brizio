"""Test modalità COLLEGAMENTO: allowlist path, collega_specifica, download dalla share."""
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche.models import Specifica
from gestione_specifiche.share_link import (
    collega_specifica,
    costruisci_indice_nomi,
    path_consentito,
)


class PathConsentitoTest(TestCase):
    @override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[r"\\novisrv\Area Produzione\SPECIFICHE"])
    def test_unc_dentro_radice(self):
        self.assertTrue(path_consentito(r"\\novisrv\Area Produzione\SPECIFICHE\x\a.pdf"))
        # case-insensitive
        self.assertTrue(path_consentito(r"\\NOVISRV\area produzione\specifiche\a.pdf"))
        # fuori radice
        self.assertFalse(path_consentito(r"\\novisrv\Area Produzione\HR\stipendi.xlsx"))
        # server diverso
        self.assertFalse(path_consentito(r"\\altro\Area Produzione\SPECIFICHE\a.pdf"))

    @override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[r"C:\base"])
    def test_traversal_e_non_assoluti(self):
        self.assertTrue(path_consentito(r"C:\base\sub\a.pdf"))
        self.assertFalse(path_consentito(r"C:\base\..\altro\a.pdf"))  # traversal
        self.assertFalse(path_consentito(r"relativo\a.pdf"))           # non assoluto
        self.assertFalse(path_consentito(""))
        self.assertFalse(path_consentito(r"C:\altro\a.pdf"))           # fuori radice


class PathConsentitoHardeningTest(TestCase):
    """Regressioni sui bypass della review avversariale (semantica path Windows)."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_traversal_con_spazio_o_punto_finale(self):
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            self.assertFalse(path_consentito(self.root + "\\.. \\fuori\\x.pdf"))
            self.assertFalse(path_consentito(self.root + "\\.. .\\fuori\\x.pdf"))

    def test_alternate_data_stream(self):
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            self.assertFalse(path_consentito(os.path.join(self.root, "a.pdf") + ":secret"))
            self.assertFalse(path_consentito(os.path.join(self.root, "a.pdf") + "::$DATA"))

    def test_nome_con_spazio_o_punto_finale(self):
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            self.assertFalse(path_consentito(os.path.join(self.root, "doc.pdf ")))
            self.assertFalse(path_consentito(os.path.join(self.root, "doc.pdf.")))

    def test_junction_fuori_radice_rifiutata(self):
        import subprocess

        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with open(os.path.join(outside, "segreto.pdf"), "wb") as fh:
            fh.write(b"SECRET-FUORI-RADICE")
        link = os.path.join(self.root, "link")
        res = subprocess.run(["cmd", "/c", "mklink", "/J", link, outside],
                             capture_output=True, text=True)
        if res.returncode != 0:
            self.skipTest("junction non creabile: " + (res.stderr or res.stdout))
        self.addCleanup(lambda: subprocess.run(["cmd", "/c", "rmdir", link], capture_output=True))
        via = os.path.join(link, "segreto.pdf")
        self.assertTrue(os.path.isfile(via))  # esiste (attraverso la junction)
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            self.assertFalse(path_consentito(via))  # ma realpath lo porta FUORI → rifiutato


class CollegaSpecificaTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.pdf = os.path.join(self.root, "SPEC-1 REV.A.pdf")
        with open(self.pdf, "wb") as fh:
            fh.write(b"%PDF-1.4 x")
        self.spec = Specifica.objects.create(
            codice="SPEC-1", revisione="A", titolo="t", tipo="specifica", fonte="generica",
        )

    def test_dry_run_apply_idempotenza(self):
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            self.assertEqual(collega_specifica(self.spec, self.pdf), "da_collegare")
            self.assertEqual(Specifica.objects.get(pk=self.spec.pk).percorso_esterno, "")
            self.assertEqual(collega_specifica(self.spec, self.pdf, apply=True), "collegato")
            self.assertEqual(Specifica.objects.get(pk=self.spec.pk).percorso_esterno, self.pdf)
            # idempotente (spec in-memory ha già il percorso)
            self.spec.percorso_esterno = self.pdf
            self.assertEqual(collega_specifica(self.spec, self.pdf, apply=True), "gia_collegato")
            self.assertEqual(collega_specifica(self.spec, self.pdf, apply=True, forza=True), "collegato")

    def test_path_non_consentito_e_file_mancante(self):
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[r"\\altro\share"]):
            self.assertEqual(collega_specifica(self.spec, self.pdf), "path_non_consentito")
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            mancante = os.path.join(self.root, "assente.pdf")
            self.assertEqual(collega_specifica(self.spec, mancante), "file_mancante")


class CollegaFallbackNomeTest(TestCase):
    """Fallback per-nome: indice esclude le cartelle superate, collega solo su match unico."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "A"))
        os.makedirs(os.path.join(self.root, "_SUPERATO"))
        self.valido = os.path.join(self.root, "A", "doc.pdf")
        with open(self.valido, "wb") as fh:
            fh.write(b"OK")
        with open(os.path.join(self.root, "_SUPERATO", "doc.pdf"), "wb") as fh:
            fh.write(b"OLD")
        self.spec = Specifica.objects.create(
            codice="C1", revisione="0", titolo="t", tipo="specifica", fonte="generica",
        )

    def test_indice_esclude_superato_e_collega_per_nome(self):
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root],
                               GESTIONE_SPECIFICHE_SHARE_EXCLUDE=["_SUPERATO"]):
            idx = costruisci_indice_nomi()
            self.assertEqual(len(idx.get("doc.pdf", [])), 1)  # solo il valido, non il superato
            missing = os.path.join(self.root, "REGISTRATO", "doc.pdf")  # path registrato inesistente
            self.assertEqual(
                collega_specifica(self.spec, missing, apply=True, indice=idx), "collegato_nome"
            )
            self.assertEqual(Specifica.objects.get(pk=self.spec.pk).percorso_esterno, self.valido)

    def test_match_multiplo_e_ambiguo(self):
        os.makedirs(os.path.join(self.root, "B"))
        with open(os.path.join(self.root, "B", "doc.pdf"), "wb") as fh:
            fh.write(b"ALT")
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root],
                               GESTIONE_SPECIFICHE_SHARE_EXCLUDE=["_SUPERATO"]):
            idx = costruisci_indice_nomi()  # doc.pdf ora in A e B -> 2 candidati
            missing = os.path.join(self.root, "X", "doc.pdf")
            self.assertEqual(collega_specifica(self.spec, missing, indice=idx), "ambiguo")


class DownloadShareTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.pdf = os.path.join(self.root, "doc.pdf")
        with open(self.pdf, "wb") as fh:
            fh.write(b"%PDF-1.4 contenuto")
        self.user = get_user_model().objects.create_superuser("u", "u@example.com", "x")
        self.client.force_login(self.user)

    def _spec(self, percorso):
        return Specifica.objects.create(
            codice="D1", revisione="0", titolo="t", tipo="specifica",
            fonte="generica", percorso_esterno=percorso,
        )

    def test_download_da_share_consentito(self):
        spec = self._spec(self.pdf)
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[self.root]):
            r = self.client.get(reverse("gestione_specifiche:allegato_download", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 contenuto")

    def test_download_path_non_consentito_404(self):
        spec = self._spec(self.pdf)
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[r"\\altro\share"]):
            r = self.client.get(reverse("gestione_specifiche:allegato_download", args=[spec.pk]))
        self.assertEqual(r.status_code, 404)

    def test_dettaglio_mostra_link_con_percorso_esterno(self):
        # F0: la scheda mostra il link di download anche per le specifiche solo "collegate".
        spec = Specifica.objects.create(
            codice="X1", revisione="0", titolo="t", tipo="specifica", fonte="generica",
            percorso_esterno=r"\\novisrv\Area Produzione\SPECIFICHE\GE AVIO AERO\X1 REV.0.pdf",
        )
        r = self.client.get(reverse("gestione_specifiche:dettaglio", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("gestione_specifiche:allegato_download", args=[spec.pk]))
        self.assertContains(r, "X1 REV.0.pdf")
