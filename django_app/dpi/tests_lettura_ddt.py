"""Magazzino DPI · «Leggi un DDT» (dpi.lettura_ddt + azioni della pagina magazzino). Dati sintetici."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.lettura_documenti import Lettura
from core.test_lettura_documenti import pdf_con_testo
from dpi.lettura_ddt import proponi
from dpi.models import CategoriaDPI, ModelloDPI, MovimentoMagazzinoDPI, TipoDPI

DDT = """FORNITORE SINTETICO DPI SPA
DOCUMENTO DI TRASPORTO N. 1234/26 DEL 14/10/2026
COD. ART. DESCRIZIONE U.M. Q.TA
GUA-ANT-09 Guanti antitaglio taglia 9 PZ 24
SCA-S3-42 Scarpe S3 numero 42 20 PA
XYZ-000 Articolo non a catalogo PZ 3
"""


class _Catalogo(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = CategoriaDPI.objects.create(nome="Protezione mani e piedi")
        tipo = TipoDPI.objects.create(categoria=cat, nome="Guanti e calzature")
        cls.guanti = ModelloDPI.objects.create(tipo=tipo, codice="GUA-ANT-09", nome="Guanti antitaglio 9")
        cls.scarpe = ModelloDPI.objects.create(tipo=tipo, codice="SCA-S3-42", nome="Scarpe S3 42", produttore="Fornitore Sintetico DPI SpA")
        ModelloDPI.objects.create(tipo=tipo, codice="SPENTO-01", nome="Fuori catalogo", is_active=False)


class PropostaDdtTests(_Catalogo):
    def test_testata_e_righe(self):
        p = proponi(Lettura(DDT))
        self.assertEqual(p["numero"], "1234/26")
        self.assertEqual(p["data"], "2026-10-14")
        self.assertEqual(p["fornitore"], "Fornitore Sintetico DPI SpA")
        righe = {r["codice"]: r for r in p["righe"]}
        self.assertEqual(set(righe), {"GUA-ANT-09", "SCA-S3-42"})
        self.assertEqual(righe["GUA-ANT-09"]["quantita"], 24)
        self.assertEqual(righe["SCA-S3-42"]["quantita"], 20)
        self.assertFalse(righe["GUA-ANT-09"]["da_controllare"])

    def test_quantita_non_letta_da_controllare(self):
        p = proponi(Lettura("DDT N. 9 DEL 01/10/2026\nGUA-ANT-09 Guanti antitaglio"))
        riga = p["righe"][0]
        self.assertEqual(riga["quantita"], 1)
        self.assertTrue(riga["da_controllare"])

    def test_nessun_codice_avvisa(self):
        p = proponi(Lettura("DDT N. 7 DEL 01/10/2026\nArticolo generico 10 PZ"))
        self.assertEqual(p["righe"], [])
        self.assertTrue(p["avvisi"])


class PaginaDdtTests(_Catalogo):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("ddt_admin", "ddt@example.invalid", "x")
        self.client.force_login(self.admin)
        self.url = reverse("dpi:magazzino")

    def test_leggi_ddt_json(self):
        pdf = SimpleUploadedFile("ddt.pdf", pdf_con_testo(DDT.strip().splitlines()), "application/pdf")
        resp = self.client.post(self.url, {"azione": "leggi_ddt", "file": pdf})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual({r["codice"] for r in data["righe"]}, {"GUA-ANT-09", "SCA-S3-42"})
        self.assertFalse(MovimentoMagazzinoDPI.objects.exists())  # leggere non carica

    def test_carico_solo_righe_spuntate(self):
        resp = self.client.post(self.url, {
            "azione": "carico_ddt", "ddt_numero": "1234/26", "data": "2026-10-14", "fornitore": "Fornitore Sintetico",
            "riga_modello": [str(self.guanti.pk), str(self.scarpe.pk)],
            f"riga_ok_{self.guanti.pk}": "1", f"riga_qta_{self.guanti.pk}": "24",
            f"riga_qta_{self.scarpe.pk}": "20",  # non spuntata
        }, follow=True)
        self.assertContains(resp, "Caricato il DDT 1234/26")
        mov = MovimentoMagazzinoDPI.objects.get()
        self.assertEqual((mov.modello_id, mov.quantita, mov.ddt_numero), (self.guanti.pk, 24, "1234/26"))

    def test_nessuna_riga_niente_carico(self):
        resp = self.client.post(self.url, {"azione": "carico_ddt", "riga_modello": [str(self.guanti.pk)]}, follow=True)
        self.assertContains(resp, "niente caricato")
        self.assertFalse(MovimentoMagazzinoDPI.objects.exists())
