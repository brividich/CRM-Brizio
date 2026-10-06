"""Import della fattura elettronica del fornitore MFC. Solo dati sintetici."""
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import fattura_import as fi
from .models import Fattura, Macchina
from .tests import _AuthedClientMixin


def _riga(apertura, chiusura, prezzo):
    totale = chiusura - apertura
    fmt = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
    return (f"COPIE EFFETTUATE C/C Dettaglio letture dal 01/04/2026 al 30/06/2026 "
            f"Lett. al 31/03/2026: {fmt(apertura)} Lett. al 30/06/2026: {fmt(chiusura)} "
            f"Totale : {fmt(totale)} A conguaglio : {fmt(totale)} Eccedenze:{prezzo} x {fmt(totale)} = 1,00")


RIGHE_K1 = [_riga(1000, 1100, "0,020000"), _riga(50000, 52500, "0,010000"),
            _riga(800, 850, "0,200000"), _riga(9000, 9900, "0,100000")]
RIGHE_K2 = [_riga(7000, 7700, "0,008000"), _riga(40, 45, "0,160000"), _riga(300, 330, "0,080000")]


def _xml(doctype=False):
    linee = ["N. Contratto: K-1 COSTO COPIA", "Articolo: SINTETICA Matricola:SYN0001"] + RIGHE_K1 + \
            ["N. Contratto: K-2 COSTO COPIA", "Articolo: SINTETICA Matricola:SYN0002"] + RIGHE_K2
    dettagli = "".join(f"<DettaglioLinee><NumeroLinea>{i}</NumeroLinea><Descrizione>{t}</Descrizione>"
                       f"<PrezzoUnitario>1.00</PrezzoUnitario></DettaglioLinee>" for i, t in enumerate(linee, 1))
    testa = '<?xml version="1.0"?>' + ('<!DOCTYPE x [<!ENTITY a "b">]>' if doctype else "")
    return (testa + '<p:FatturaElettronica xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">'
            "<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento>"
            "<Data>2026-07-05</Data><Numero>999/SYN</Numero></DatiGeneraliDocumento></DatiGenerali>"
            f"<DatiBeniServizi>{dettagli}</DatiBeniServizi></FatturaElettronicaBody></p:FatturaElettronica>").encode()


def _pdf():
    """PDF sintetico a due pagine: date spezzate a capo e una riga a cavallo di pagina."""
    import fitz
    doc = fitz.open()
    testata = "TD01 (fattura) 999/SYN 05-07-2026 XXXXXXX\n"
    p1 = testata + "N. Contratto: K-1 COSTO COPIA\nMatricola:SYN0001\n" + \
        "\n".join(r.replace("01/04/2026", "01/04\n/2026") for r in RIGHE_K1) + \
        "\nN. Contratto: K-2 COSTO COPIA\nMatricola:SYN0002\n" + RIGHE_K2[0] + "\n" + RIGHE_K2[1][:140]
    p2 = testata + RIGHE_K2[1][140:] + "\n" + RIGHE_K2[2]
    for testo in (p1, p2):
        pagina = doc.new_page()
        pagina.insert_textbox(fitz.Rect(30, 30, 560, 800), testo, fontsize=6)
    dati = doc.tobytes()
    doc.close()
    return dati


ATTESI = {"K-1": {"a4_bn": 52500, "a3_bn": 1100, "a4_col": 9900, "a3_col": 850},
          "K-2": {"a4_bn": 7700, "a3_bn": 0, "a4_col": 330, "a3_col": 45}}


class InterpretaTests(SimpleTestCase):
    def test_contatori_dal_prezzo_anche_con_riga_mancante(self):
        dati = fi.interpreta(" ".join(["N. Contratto: K-2"] + RIGHE_K2))
        righe = dati["contratti"][0]["righe"]
        self.assertEqual([(r["contatore"], r["lettura"]) for r in righe],
                         [("a4_bn", 7700), ("a3_col", 45), ("a4_col", 330)])
        self.assertTrue(all(r["certo"] and r["coerente"] for r in righe))
        self.assertEqual(dati["periodo_al"], date(2026, 6, 30))

    def test_rapporto_dieci_ambiguo_resta_incerto(self):
        righe = [{"prezzo": Decimal("0.005")}, {"prezzo": Decimal("0.05")}]
        fi._assegna_contatori(righe)
        self.assertFalse(any(r["certo"] for r in righe))

    def test_formato_non_riconosciuto(self):
        with self.assertRaises(fi.FatturaNonLeggibile):
            fi.interpreta("Fattura qualsiasi senza contratti")

    def test_xml_con_doctype_rifiutato(self):
        with self.assertRaises(fi.FatturaNonLeggibile):
            fi.dati_da_xml(_xml(doctype=True))


class LeggiFatturaTests(TestCase):
    def setUp(self):
        Macchina.objects.create(reparto="Alfa", matricola="SYN0001", contratto="K-1")
        Macchina.objects.create(reparto="Beta", matricola="SYN0002", contratto="K-2")

    def _verifica(self, letta):
        self.assertEqual(letta["testata"]["numero"], "999/SYN")
        self.assertEqual(letta["testata"]["data"], date(2026, 7, 5))
        self.assertEqual(letta["testata"]["trimestre"], "2026-Q2")
        self.assertEqual({r["contratto"]: {k: r[k] for k in ATTESI["K-1"]} for r in letta["righe"]}, ATTESI)
        self.assertEqual(len(letta["avvisi"]), 1)  # solo la riga A3 B/N assente in K-2
        self.assertIn("K-2", letta["avvisi"][0])

    def test_xml(self):
        self._verifica(fi.leggi_fattura("fattura.xml", _xml()))

    def test_pdf_con_riga_a_cavallo_di_pagina(self):
        self._verifica(fi.leggi_fattura("fattura.xml.pdf", _pdf()))

    def test_p7m_e_formati_ignoti(self):
        for nome, dati in (("f.xml.p7m", b"\x30\x80"), ("f.txt", b"ciao")):
            with self.assertRaises(fi.FatturaNonLeggibile):
                fi.leggi_fattura(nome, dati)


class ImportViewTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        Macchina.objects.create(reparto="Alfa", matricola="SYN0001", contratto="K-1")
        Macchina.objects.create(reparto="Beta", matricola="SYN0002", contratto="K-2")

    def test_import_precompila_senza_salvare(self):
        file = SimpleUploadedFile("fattura.xml", _xml(), content_type="text/xml")
        r = self.client.post(reverse("contatori:fattura_nuova"), {"azione": "importa", "file_fattura": file})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Fattura.objects.exists())
        self.assertEqual(r.context["form"]["numero"].value(), "999/SYN")
        self.assertEqual(r.context["form"]["trimestre"].value(), "2026-Q2")
        righe = r.context["righe"]
        self.assertEqual([f.initial["contratto"] for f in righe.forms], ["K-1", "K-2"])
        self.assertEqual(righe.forms[0].initial["a4_bn"], 52500)
        self.assertContains(r, "manca la riga di A3 B/N")

    def test_file_illeggibile_torna_alla_pagina_con_errore(self):
        file = SimpleUploadedFile("fattura.pdf", b"%PDF-rotto", content_type="application/pdf")
        r = self.client.post(reverse("contatori:fattura_nuova"), {"azione": "importa", "file_fattura": file},
                             follow=True)
        self.assertTrue(any("Fattura non importata" in str(m) for m in r.context["messages"]))
        self.assertFalse(Fattura.objects.exists())
