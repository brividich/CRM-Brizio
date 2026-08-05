"""Lettura di codici QR da immagini e PDF (`core.qr`).

Il contratto da difendere è tanto quello che riesce quanto quello che *fallisce
in silenzio*: chi chiama deve poter contare su una lista vuota, mai su
un'eccezione, perché una scansione illeggibile è normale amministrazione e la
strada alternativa (digitare il codice) deve restare percorribile.
"""
from io import BytesIO

from django.test import SimpleTestCase

from core import qr


def _png_con_qr(testo: str, *, margine: int = 40) -> bytes:
    """PNG con un QR al centro di un foglio bianco, come uscirebbe da uno scanner."""
    import qrcode
    from PIL import Image

    codice = qrcode.QRCode(box_size=6, border=2)
    codice.add_data(testo)
    codice.make(fit=True)
    img = codice.make_image(fill_color="black", back_color="white").convert("RGB")

    foglio = Image.new("RGB", (img.width + margine * 2, img.height + margine * 2), "white")
    foglio.paste(img, (margine, margine))
    buf = BytesIO()
    foglio.save(buf, format="PNG")
    return buf.getvalue()


def _pdf_con_qr(testo: str) -> bytes:
    """PDF A4 con il QR in alto a destra, come il foglio firme vero."""
    import qrcode
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    codice = qrcode.QRCode(box_size=4, border=1)
    codice.add_data(testo)
    codice.make(fit=True)
    png = BytesIO()
    codice.make_image(fill_color="black", back_color="white").save(png, format="PNG")
    png.seek(0)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    larghezza, altezza = A4
    c.drawImage(ImageReader(png), larghezza - 46 * mm, altezza - 48 * mm, 26 * mm, 26 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()


class LetturaCodiciTest(SimpleTestCase):

    def test_legge_il_codice_da_un_png(self):
        trovati = qr.leggi_codici(_png_con_qr("K7MQ2XR4TB"), "scansione.png")
        self.assertIn("K7MQ2XR4TB", trovati)

    def test_legge_il_codice_da_un_pdf(self):
        trovati = qr.leggi_codici(_pdf_con_qr("AB3D5F7H"), "foglio.pdf")
        self.assertIn("AB3D5F7H", trovati)

    def test_legge_anche_da_immagine_gia_aperta(self):
        """Chi ha già rasterizzato non deve rifarlo: si passa il PIL diretto."""
        from PIL import Image

        img = Image.open(BytesIO(_png_con_qr("PILDIRETTO")))
        img.load()
        self.assertIn("PILDIRETTO", qr.leggi_codici(img))

    def test_legge_il_codice_su_foglio_ruotato(self):
        """Uno scanner storto è la norma, non l'eccezione."""
        from PIL import Image

        img = Image.open(BytesIO(_png_con_qr("STORTO99")))
        girata = img.rotate(6, expand=True, fillcolor="white")
        buf = BytesIO()
        girata.save(buf, format="PNG")
        self.assertIn("STORTO99", qr.leggi_codici(buf.getvalue(), "storto.png"))

    def test_foglio_senza_codice_restituisce_lista_vuota(self):
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (600, 800), "white").save(buf, format="PNG")
        self.assertEqual(qr.leggi_codici(buf.getvalue(), "vuoto.png"), [])

    def test_file_corrotto_non_solleva(self):
        """Il caso che conta: mai un'eccezione in faccia a chi carica."""
        self.assertEqual(qr.leggi_codici(b"non sono un file", "rotto.pdf"), [])
        self.assertEqual(qr.leggi_codici(b"%PDF-1.4 spazzatura", "rotto.pdf"), [])
        self.assertEqual(qr.leggi_codici(b"", "vuoto.png"), [])

    def test_leggi_codice_filtra_per_prefisso(self):
        contenuto = _png_con_qr("FF-K7MQ2X")
        self.assertEqual(qr.leggi_codice(contenuto, "x.png", prefisso="FF-"), "FF-K7MQ2X")
        self.assertIsNone(qr.leggi_codice(contenuto, "x.png", prefisso="ZZ-"))

    def test_leggi_codice_senza_prefisso_prende_il_primo(self):
        self.assertEqual(qr.leggi_codice(_png_con_qr("PRIMO1"), "x.png"), "PRIMO1")

    def test_disponibile_riflette_la_libreria(self):
        """In un ambiente aggiornato deve dire di sì: se dice no, manca il pacchetto."""
        self.assertTrue(qr.disponibile())

    def test_senza_libreria_degrada_a_lista_vuota(self):
        """Un ambiente aggiornato a metà non può tirare giù il portale."""
        originale = qr._zxing
        qr._zxing = lambda: None
        try:
            self.assertFalse(qr.disponibile())
            self.assertEqual(qr.leggi_codici(_png_con_qr("IGNORATO"), "x.png"), [])
            self.assertIsNone(qr.leggi_codice(_png_con_qr("IGNORATO"), "x.png"))
        finally:
            qr._zxing = originale
