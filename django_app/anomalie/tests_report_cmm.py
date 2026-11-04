"""Lettura delle righe di un protocollo ZEISS (PiWeb/CALYPSO) da uno screenshot.

Le righe di testo sono quelle restituite davvero da Tesseract su catture di protocolli
(valori tecnici, nessun dato personale), compresi gli errori tipici dell'OCR.
"""
from __future__ import annotations

import shutil
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from anomalie import report_cmm as rc

User = get_user_model()

RIGHE_OCR = [
    "DIMENSIONE DEI DENTI",
    "Length",
    "m 178,00 9? 4 0539 40000 0,1000 0,0000 0,0539 | : |",       # virgola letta come spazio
    "® 175,00 Y 0,3025 0,0000 02500 00000 03025 00525",           # virgole perse + eccedenza
    "Paralaism",
    "® 176,00 J/ 0,0057 0,0000 0,1000 0,0000 0,0057",
    "m 178,02 e 3,9910 4,0000 01000 00000 -0,0000 _ 0:0090",      # scostamento letto male
    "m 17503 Y 0,3316 0,0000 02500 00000 03316 _ 20816",          # nome senza virgola
    "W 141,00 Dist M-N of 12519842 12520000 02500 -0.2500 -0,0158 .,",
    "® 163,01 DiaG e 69,0570 69,0000 0,0300 0,0000 0,0570 9,0270",
    "FORI o 8.050-8.070 LATO PIANO N",
    "® 170,00 Dia C %) 8,0854 80760 00100 00000 00094",
]


class LetturaRigheTests(SimpleTestCase):
    def setUp(self):
        self.righe = {r["nome"].split()[0]: r for r in rc.righe_da_testo(RIGHE_OCR)}

    def test_righe_e_nomi(self):
        self.assertEqual(list(self.righe), ["178,00", "175,00", "176,00", "178,02", "175,03", "141,00", "163,01", "170,00"])
        self.assertEqual(self.righe["141,00"]["nome"], "141,00 Dist M-N")
        self.assertEqual(self.righe["170,00"]["nome"], "170,00 Dia C")

    def test_valori_corretti_anche_senza_virgola(self):
        r = self.righe["178,00"]
        self.assertEqual((r["misurato"], r["nominale"], r["tol_sup"], r["tol_inf"]), (4.0539, 4.0, 0.1, 0.0))
        self.assertEqual(self.righe["175,00"]["tol_sup"], 0.25)
        self.assertEqual(self.righe["141,00"]["misurato"], 1251.9842)

    def test_scostamento_letto_male_da_verificare(self):
        r = self.righe["178,02"]
        self.assertTrue(r["da_verificare"])
        self.assertEqual(r["scostamento"], -0.009)
        self.assertFalse(self.righe["178,00"]["da_verificare"])

    def test_tipo_da_etichetta_storpiata_o_dal_nome(self):
        self.assertEqual(self.righe["178,00"]["tipo"], "length")
        self.assertEqual(self.righe["176,00"]["tipo"], "parallelism")
        self.assertEqual(self.righe["163,01"]["tipo"], "diameter")   # «Dia» nel nome
        self.assertEqual(self.righe["141,00"]["tipo"], "distance")

    def test_sezione(self):
        self.assertEqual(self.righe["178,00"]["sezione"], "Dimensione Dei Denti")
        self.assertEqual(self.righe["170,00"]["sezione"], "Fori O 8.050-8.070 Lato Piano N")


class PropostaMisuraTests(SimpleTestCase):
    def test_minmax_e_fuori(self):
        p = rc.proposta_misura({"nome": "163,01 Dia G", "tipo": "diameter", "misurato": 69.057, "nominale": 69.0,
                                "tol_sup": 0.03, "tol_inf": 0.0, "scostamento": 0.057, "sezione": "Diametro G"})
        self.assertEqual((p["car"], p["modo"], p["a"], p["b"], p["ril"]), ("diametro", "minmax", "69", "69.03", "69.057"))
        self.assertTrue(p["fuori"])
        self.assertEqual(p["dove"], "car. 163,01 Dia G · Diametro G")

    def test_geometrica_max_e_tolleranza_negativa_senza_segno(self):
        g = rc.proposta_misura({"nome": "175,00", "tipo": "position", "misurato": 0.3025, "nominale": 0.0,
                                "tol_sup": 0.25, "tol_inf": 0.0, "scostamento": 0.3025})
        self.assertEqual((g["car"], g["modo"], g["a"]), ("posizione", "max", "0.25"))
        q = rc.proposta_misura({"nome": "141,00", "tipo": "distance", "misurato": 1251.9842, "nominale": 1252.0,
                                "tol_sup": 0.25, "tol_inf": 0.25, "scostamento": -0.0158})
        self.assertEqual((q["a"], q["b"]), ("1251.75", "1252.25"))  # -0,25 anche se l'OCR perde il segno
        self.assertFalse(q["fuori"])

    def test_unisci_letture_tiene_la_riga_coerente(self):
        buona = {"nome": "178,01", "tipo": "", "misurato": 4.0188, "nominale": 4.0, "tol_sup": 0.1, "tol_inf": 0.0,
                 "scostamento": 0.0188, "da_verificare": False, "sezione": "S"}
        cattiva = {**buona, "tol_sup": 0.0, "tipo": "length"}
        unite = rc.unisci_letture([cattiva], [buona])
        self.assertEqual(len(unite), 1)
        self.assertEqual(unite[0]["tol_sup"], 0.1)
        self.assertEqual(unite[0]["tipo"], "length")


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class EndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="cmm-op", password="pass12345", email="c@example.local")
        self.client.force_login(self.user)
        self.url = reverse("api_anomalie_report_cmm_leggi")

    def test_proposte_senza_salvare_l_immagine(self):
        finto = {"righe": [{"car": "diametro", "fuori": True}], "testo": ["x"]}
        with patch("anomalie.report_cmm.leggi_screenshot", return_value=finto) as leggi, \
                patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            r = self.client.post(self.url, {"op_id": "OP/2026/0001",
                                            "immagine": SimpleUploadedFile("r.png", b"\x89PNG", "image/png")})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["righe"], finto["righe"])
        leggi.assert_called_once()

    def test_permesso_e_parametri(self):
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=False), \
                patch("anomalie.controllo_views._op_ancora_da_creare", return_value=False):
            r = self.client.post(self.url, {"op_id": "OP/2026/0001",
                                            "immagine": SimpleUploadedFile("r.png", b"x", "image/png")})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post(self.url, {}).status_code, 400)

    def test_errore_leggibile(self):
        with patch("anomalie.report_cmm.leggi_screenshot", side_effect=rc.ErroreReport("Tesseract non installato")), \
                patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            r = self.client.post(self.url, {"op_id": "OP/2026/0001",
                                            "immagine": SimpleUploadedFile("r.png", b"x", "image/png")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("Tesseract", r.json()["error"])


class OcrVeroTests(SimpleTestCase):
    """Con Tesseract installato: un'immagine sintetica di una riga del protocollo."""

    def test_riga_disegnata(self):
        from anagrafica.services.referti_ocr import percorso_tesseract

        if not percorso_tesseract() and not shutil.which("tesseract"):
            self.skipTest("Tesseract non installato")
        import io

        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (1100, 90), "white")
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except OSError:
            font = ImageFont.load_default()
        d.text((10, 10), "DIAMETRO F - PIANO M", fill="black", font=font)
        d.text((10, 50), "196,00      131,3309    131,3610    0,0250    0,0000    -0,0301", fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        righe = rc.leggi_screenshot(buf.getvalue())["righe"]
        self.assertEqual(len(righe), 1)
        self.assertEqual((righe[0]["ril"], righe[0]["a"], righe[0]["b"]), ("131.3309", "131.361", "131.386"))
        self.assertTrue(righe[0]["fuori"])
