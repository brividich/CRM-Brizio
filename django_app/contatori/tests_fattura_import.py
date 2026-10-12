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


# --- Tracciato Copylab: un blocco per macchina, solo totali B/N e colore ------------

def _blocco_copylab(matricola, contratto, bn, col):
    fmt = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
    righe = [f"Riga di commento Descr.agg.: Matricola:{matricola} Contratto:{contratto} "
             "Descr.agg.: Articolo:SINTETICA 1 AswTRiga: Descrittivo #DE#"]
    for nome, sigla, (apertura, chiusura) in (("B/N", "CBN", bn), ("COLORE", "COL1", col)):
        righe.append(f"COPIE EFFETTUATE {nome} NOL. 01/04/2026 30/06/2026 1,00 NR 1,00 € 1,00 € 22,00 "
                     "Descr.agg.: dal 01/04/2026 al 30/06/2026 "
                     f"Descr.agg.: * {matricola} Descr.agg.: Lett. al 30/06/2026: {fmt(chiusura)} "
                     f"Descr.agg.: Lett. al 31/03/2026: {fmt(apertura)} "
                     f"Descr.agg.: Differenza {sigla} : {fmt(chiusura - apertura)} "
                     f"Descr.agg.: Tot. copie : {fmt(chiusura - apertura)} "
                     "Descr.agg.: C/Copia : 0,005000x 1 = 1,00")
    righe.append("CANONE DI NOLEGGIO 01/07/2026 30/09/2026 1,00 NR Descr.agg.: dal 01/07/2026 al 30/09/2026")
    return " ".join(righe)


COPYLAB = ("COPY LAB S.R.L. TD01 (Fattura) nr. 77/SYN del 05/07/2026 (EUR) "
           + _blocco_copylab("SYNCL01", "11/U.T.", (1000, 1500), (200, 260))
           + _blocco_copylab("SYNCL02", "12/sala prove", (5000, 5400), (90, 95))
           + _blocco_copylab("SYNCL03", "12/sala prove", (300, 320), (10, 12)))


def _pdf_copylab():
    import fitz
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.insert_textbox(fitz.Rect(30, 30, 560, 800), COPYLAB.replace(" Descr.agg.:", "\nDescr.agg.:"),
                          fontsize=6)
    dati = doc.tobytes()
    doc.close()
    return dati


def _xml_copylab():
    """FatturaPA sintetica: le «Descr.agg.» stanno in AltriDatiGestionali/RiferimentoTesto."""
    linee = []
    for pezzo in _blocco_copylab("SYNCL01", "11/U.T.", (1000, 1500), (200, 260)).split(" Descr.agg.: "):
        if pezzo.startswith(("Riga di commento", "COPIE", "CANONE")):
            linee.append([pezzo, []])
        else:
            linee[-1][1].append(pezzo)
    dettagli = "".join(
        f"<DettaglioLinee><NumeroLinea>{i}</NumeroLinea><Descrizione>{d}</Descrizione>"
        + "".join(f"<AltriDatiGestionali><TipoDato>TXT</TipoDato><RiferimentoTesto>{a}</RiferimentoTesto>"
                  "</AltriDatiGestionali>" for a in agg)
        + "<PrezzoUnitario>1.00</PrezzoUnitario></DettaglioLinee>" for i, (d, agg) in enumerate(linee, 1))
    return ('<?xml version="1.0"?><p:FatturaElettronica '
            'xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">'
            "<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento>"
            "<Data>2026-07-05</Data><Numero>77/SYN</Numero></DatiGeneraliDocumento></DatiGenerali>"
            f"<DatiBeniServizi>{dettagli}</DatiBeniServizi></FatturaElettronicaBody></p:FatturaElettronica>").encode()


class CopylabTests(TestCase):
    def test_interpreta_totali_e_contratto_testo_libero(self):
        dati = fi.interpreta(COPYLAB)
        self.assertEqual(dati["dettaglio"], fi.DETTAGLIO_TOTALI)
        self.assertEqual([c["contratto"] for c in dati["contratti"]],
                         ["11/U.T.", "12/sala prove", "12/sala prove"])
        prima = dati["contratti"][0]["righe"]
        self.assertEqual([(r["contatore"], r["lettura"], r["totale"]) for r in prima],
                         [("a4_bn", 1500, 500), ("a4_col", 260, 60)])
        self.assertTrue(all(r["certo"] and r["coerente"] for r in prima))
        # Il periodo del canone (luglio-settembre) non sposta la chiusura delle letture.
        self.assertEqual(dati["periodo_al"], date(2026, 6, 30))

    def test_pdf_contratto_da_anagrafica_e_pool_sommato(self):
        Macchina.objects.create(reparto="UT", matricola="SYNCL01", contratto="K-UT")
        Macchina.objects.create(reparto="Prove A", matricola="SYNCL02", contratto="K-PROVE")
        Macchina.objects.create(reparto="Prove B", matricola="SYNCL03", contratto="K-PROVE")
        letta = fi.leggi_fattura("copylab.pdf", _pdf_copylab())
        t = letta["testata"]
        self.assertEqual((t["numero"], t["data"], t["fornitore"], t["dettaglio"], t["trimestre"]),
                         ("77/SYN", date(2026, 7, 5), "COPYLAB", "TOTALI", "2026-Q2"))
        righe = {r["contratto"]: (r["a4_bn"], r["a3_bn"], r["a4_col"], r["a3_col"]) for r in letta["righe"]}
        self.assertEqual(righe, {"K-UT": (1500, 0, 260, 0), "K-PROVE": (5720, 0, 107, 0)})
        self.assertEqual(letta["avvisi"], [])

    def test_matricola_senza_contratto_in_anagrafica(self):
        Macchina.objects.create(reparto="UT", matricola="SYNCL01", contratto="")
        letta = fi.leggi_fattura("f.xml", _xml_copylab())
        self.assertTrue(any("SYNCL01" in a and "11/U.T." in a for a in letta["avvisi"]))

    def test_xml_legge_altri_dati_gestionali(self):
        testo, numero, _ = fi.dati_da_xml(_xml_copylab())
        self.assertEqual(numero, "77/SYN")
        self.assertIn("Lett. al 30/06/2026: 1.500", testo)
