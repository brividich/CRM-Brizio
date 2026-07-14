from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from anagrafica.models import Reparto

from .models import EstrazioneStato, ProdottoChimico, SchedaSicurezza
from .services.ingestion import _extract_frasi_h, _extract_frasi_p, _extract_pittogrammi, _split_sections, estrai_sds


def _build_sample_sds_pdf() -> bytes:
    """Costruisce un PDF SDS minimale ma realistico (16 sezioni) con reportlab."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)

    testo_sezioni = {
        1: "Identificazione della sostanza e della società",
        2: (
            "Pittogrammi: GHS02 GHS07\n"
            "Frasi H: H225 H319\n"
            "Frasi P: P210 P280\n"
            "Classificazione: Liquido infiammabile categoria 2."
        ),
        3: "Composizione: miscela di solventi organici.",
        4: "Misure di primo soccorso: in caso di contatto con gli occhi sciacquare abbondantemente.",
        5: "Misure antincendio: usare estintore a polvere.",
        6: "Misure in caso di rilascio accidentale.",
        7: "Manipolazione e immagazzinamento in luogo areato.",
        8: "Controllo dell'esposizione: indossare guanti e occhiali protettivi.",
        9: "Proprieta' fisiche e chimiche: liquido incolore.",
        10: "Stabilita' e reattivita': incompatibile con ossidanti forti.",
        11: "Informazioni tossicologiche.",
        12: "Informazioni ecologiche.",
        13: "Considerazioni sullo smaltimento.",
        14: "Informazioni sul trasporto.",
        15: "Informazioni sulla regolamentazione.",
        16: "Altre informazioni.",
    }

    y = 800
    for num, testo in testo_sezioni.items():
        c.drawString(50, y, f"SEZIONE {num}: sezione di prova")
        y -= 15
        for line in testo.splitlines():
            c.drawString(60, y, line)
            y -= 15
        y -= 10
        if y < 80:
            c.showPage()
            y = 800
    c.save()
    return buf.getvalue()


def _upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class SplitSectionsTest(TestCase):
    def test_riconosce_header_tollerante_a_maiuscole_e_spazi(self):
        text = (
            "SEZIONE 1: Identificazione\ntesto uno\n"
            "sezione  2 - Identificazione dei pericoli\ntesto due\n"
            "Sezione 4. Primo soccorso\ntesto quattro\n"
        )
        sections = _split_sections(text)
        self.assertIn(1, sections)
        self.assertIn(2, sections)
        self.assertIn(4, sections)
        self.assertIn("testo due", sections[2])

    def test_nessun_header_ritorna_mappa_vuota(self):
        self.assertEqual(_split_sections("testo qualunque senza sezioni"), {})


class ExtractHelpersTest(TestCase):
    def test_estrae_pittogrammi_ghs(self):
        self.assertEqual(_extract_pittogrammi("Pittogrammi: GHS02 GHS07 ghs02"), ["GHS02", "GHS07"])

    def test_estrae_frasi_h(self):
        self.assertEqual(_extract_frasi_h("Frasi H: H225 H319 EUH066"), ["EUH066", "H225", "H319"])

    def test_estrae_frasi_p(self):
        self.assertEqual(_extract_frasi_p("Frasi P: P210 P280"), ["P210", "P280"])


class EstraiSdsTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)

    def test_estrazione_pdf_valido_popola_campi_curati(self):
        pdf_bytes = _build_sample_sds_pdf()
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_upload("sds.pdf", pdf_bytes), versione="1",
        )
        estrai_sds(scheda)
        scheda.refresh_from_db()

        self.assertEqual(scheda.estrazione_stato, EstrazioneStato.OK)
        self.assertIn("GHS02", scheda.pittogrammi)
        self.assertIn("H225", scheda.frasi_h)
        self.assertIn("P210", scheda.frasi_p)
        self.assertIn("sciacquare", scheda.primo_soccorso.lower())
        self.assertIn("guanti", scheda.dpi_testo.lower())
        self.assertIn("ossidanti", scheda.incompatibilita.lower())
        self.assertTrue(scheda.estratto_grezzo)

    def test_pdf_malformato_non_solleva_eccezione(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto,
            pdf=_upload("corrotto.pdf", b"non sono affatto un PDF valido"),
            versione="1",
        )
        try:
            estrai_sds(scheda)
        except Exception as exc:  # pragma: no cover - non deve mai accadere
            self.fail(f"estrai_sds ha sollevato un'eccezione non gestita: {exc}")
        scheda.refresh_from_db()
        self.assertEqual(scheda.estrazione_stato, EstrazioneStato.FALLITA)
        self.assertEqual(scheda.pittogrammi, [])

    def test_pdf_senza_sezioni_riconoscibili_e_parziale_o_fallita(self):
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(50, 800, "Documento senza intestazioni di sezione standard.")
        c.save()

        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_upload("senza_sezioni.pdf", buf.getvalue()), versione="1",
        )
        estrai_sds(scheda)
        scheda.refresh_from_db()
        self.assertEqual(scheda.estrazione_stato, EstrazioneStato.FALLITA)
        self.assertEqual(scheda.pittogrammi, [])
