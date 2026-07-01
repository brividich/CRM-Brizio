"""Test del renderer PDF MOD.133 (mod133_render.render_mod133).

Usa SOLO dati sintetici (nessun dato cliente reale). Verifica:
- l'output e' un PDF valido (magic %PDF) e riapribile con fitz;
- compaiono le etichette-chiave del modulo e i valori passati;
- chiavi mancanti / righe vuote non sollevano eccezioni;
- con molte righe il documento va in multipagina.
"""
from __future__ import annotations

import re

import fitz  # PyMuPDF
from django.test import SimpleTestCase

from gestione_specifiche.mod133_render import CAMPI_MOD133, render_mod133


def _dati_sintetici():
    return {
        "fonte": "ENTE-SINTETICO-EN9100",
        "documento_analizzato": "DOC-ANALIZZATO-42 Rev.C",
        "documenti_cn_interessati": "PROC-CN-07; ISTR-CN-11",
        "data": "2026-07-01",
        "righe": [
            {
                "paragrafi": "PAR-3.2",
                "argomenti": "Requisito tracciabilita lotti",
                "impatto_doc": "SI",
                "impatto_doc_desc": "Aggiornare modulo controllo",
                "impatto_operativo": "NO",
                "paragrafi_cn": "CN-4.1",
                "argomenti_cn": "Revisione istruzione operativa",
            },
            {
                "paragrafi": "PAR-5.8",
                "argomenti": "Nuovo criterio accettazione",
                "impatto_doc": "NO",
                "impatto_doc_desc": "",
                "impatto_operativo": "SI",
                "paragrafi_cn": "CN-9.2",
                "argomenti_cn": "Aggiornamento piano collaudo",
            },
        ],
        "note": "Nota sintetica di verifica requisiti.",
        "revisore": "Mario Bianchi Sintetico",
        "approvatore": "Luigi Verdi Sintetico",
    }


def _testo_pdf(pdf_bytes: bytes) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


class RenderMod133Test(SimpleTestCase):
    def test_output_e_pdf_valido(self):
        pdf = render_mod133(_dati_sintetici())
        self.assertIsInstance(pdf, (bytes, bytearray))
        self.assertTrue(bytes(pdf).startswith(b"%PDF"))

    def test_contiene_etichette_e_valori(self):
        pdf = render_mod133(_dati_sintetici())
        testo = _testo_pdf(pdf)
        # Le celle strette mandano a capo il testo: per i valori/etichette multi-parola
        # si confronta sul testo con whitespace collassato (indipendente dal wrapping).
        testo_norm = re.sub(r"\s+", " ", testo)
        # Titoli / footer disegnati a canvas.
        self.assertIn("FLOW DOWN FOR NEW REQUIREMENTS", testo_norm)
        self.assertIn("Mod.133", testo_norm)
        # Etichette testata e colonne tabella.
        self.assertIn("SOURCE (issuing body)", testo_norm)
        self.assertIn("Reviewed Document", testo_norm)
        self.assertIn("Operational Impact", testo_norm)
        self.assertIn("NOTE", testo_norm)
        self.assertIn("Authorized Reviewer", testo_norm)
        self.assertIn("Approver", testo_norm)
        # Valori sintetici passati.
        self.assertIn("ENTE-SINTETICO-EN9100", testo_norm)
        self.assertIn("DOC-ANALIZZATO-42", testo_norm)
        self.assertIn("PAR-3.2", testo_norm)
        self.assertIn("Requisito tracciabilita lotti", testo_norm)
        self.assertIn("Nota sintetica di verifica requisiti.", testo_norm)
        self.assertIn("Mario Bianchi Sintetico", testo_norm)
        self.assertIn("Luigi Verdi Sintetico", testo_norm)

    def test_chiavi_mancanti_non_crasha(self):
        # Dizionario vuoto.
        pdf = render_mod133({})
        self.assertTrue(bytes(pdf).startswith(b"%PDF"))
        # Dizionario parziale con righe incomplete / valori None / righe non-dict.
        parziale = {
            "fonte": "SOLO-FONTE",
            "righe": [
                {"paragrafi": "P1"},          # chiavi mancanti
                {},                            # riga vuota
                {"argomenti": None},           # valore None
                "riga-non-dict",              # tipo errato
            ],
            "note": None,
        }
        pdf2 = render_mod133(parziale)
        self.assertTrue(bytes(pdf2).startswith(b"%PDF"))
        self.assertIn("SOLO-FONTE", _testo_pdf(pdf2))

    def test_input_non_dict_non_crasha(self):
        # Robustezza estrema: input non-dizionario.
        pdf = render_mod133(None)  # type: ignore[arg-type]
        self.assertTrue(bytes(pdf).startswith(b"%PDF"))

    def test_multipagina_con_molte_righe(self):
        dati = _dati_sintetici()
        dati["righe"] = [
            {
                "paragrafi": "PAR-%d" % i,
                "argomenti": "Argomento sintetico numero %d con testo di riempimento" % i,
                "impatto_doc": "SI" if i % 2 else "NO",
                "impatto_doc_desc": "Dettaglio impatto %d" % i,
                "impatto_operativo": "NO" if i % 2 else "SI",
                "paragrafi_cn": "CN-%d" % i,
                "argomenti_cn": "Modifica documento CN riga %d" % i,
            }
            for i in range(80)
        ]
        pdf = render_mod133(dati)
        self.assertTrue(bytes(pdf).startswith(b"%PDF"))
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            self.assertGreater(doc.page_count, 1)

    def test_cella_testo_lunghissimo_non_crasha(self):
        # Una singola cella con testo enorme non deve sollevare LayoutError: il renderer
        # ritenta col troncamento e produce comunque un PDF (rete anti-overflow).
        dati = _dati_sintetici()
        dati["righe"] = [{"argomenti": "X " * 5000}]
        pdf = render_mod133(dati)
        self.assertTrue(bytes(pdf).startswith(b"%PDF"))

    def test_nota_lunghissima_non_crasha(self):
        dati = _dati_sintetici()
        dati["note"] = "Nota molto lunga di verifica requisiti. " * 2000
        pdf = render_mod133(dati)
        self.assertTrue(bytes(pdf).startswith(b"%PDF"))

    def test_campi_mod133_contratto(self):
        # La costante deve documentare testata, righe, note e firme.
        self.assertIn("testata", CAMPI_MOD133)
        self.assertIn("righe", CAMPI_MOD133)
        self.assertIn("firme", CAMPI_MOD133)
        self.assertIn("fonte", CAMPI_MOD133["testata"])
        self.assertIn("paragrafi", CAMPI_MOD133["righe"])
