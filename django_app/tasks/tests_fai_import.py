"""Migrazione del file Situazione FAI-ISIR, con un file sintetico."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import tempfile
from io import StringIO

import openpyxl
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from .fai_regole import aggiungi_mesi
from .models import FaiArticolo, FaiDocumento, FaiFase, FaiGruppo, FaiOpzione, FaiRecord
from .services.fai import esito_progetto, prossimo_numero_fai, stato_articolo
from .services.fai_import import FileNonValido, importa, leggi_data
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, make_project

TESTATA = [
    "CLIENTE", "Faldone N°", "CCI CN\nN°", "ANNO\nCCI CN", "FAI CN\nN°", "ANNO\nFAI CN", "N° Invito", "LINEA", "P/N ASSY", "P/N",
    "NOME PARTICOLARE", "REV.", "P/N ALTERNATIVO", "REV. P/N ALTERNATIVO", "CRITICITA'", "PIANO FAI N°", "Descrizione Piano FAI",
    "AVANZAMENTO\nPIANO FAI", "STATO\nPIANO FAI", "DATA INVIO\nDOCUMENTAZIONE", "OP", "OdA/ITEM", "CHIUSURA FAI\nCON", "DATA CHIUSURA\nFAI",
    "VERISONE\nDI PRODUZIONE", "STATO VERSIONE", "DATA VERSIONE", "CODICE DIP", "DATA APPROVAZIONE\nDIP", "INVIO CQ", "CROSS-CORRELATION",
    "SDC", "PFC", "SINTESI", "FAI", "NOTE",
]


def riga(**campi):
    base = dict.fromkeys(TESTATA, "N/A")
    base.update({"CLIENTE": "Cliente Alfa", "P/N": "PN-1", "STATO\nPIANO FAI": "F1", "PIANO FAI N°": "PF-1"})
    base.update({k.replace("__", "\n"): v for k, v in campi.items()})
    return [base[c] for c in TESTATA]


class ImportBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        self.cartella = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cartella, True)

    def file(self, *righe, testata=TESTATA, foglio="Situazione FAI"):
        libro = openpyxl.Workbook()
        ws = libro.active
        ws.title = foglio
        ws.append(testata)
        for r in righe:
            ws.append(r)
        percorso = os.path.join(self.cartella, "situazione.xlsx")
        libro.save(percorso)
        return percorso


class LetturaDateTests(TasksBaseTestCase):
    def test_date(self):
        self.assertEqual(leggi_data(dt.datetime(2024, 3, 1)), (dt.date(2024, 3, 1), False))
        self.assertEqual(leggi_data("N/A"), (None, False))
        self.assertEqual(leggi_data("X"), (None, False))
        self.assertEqual(leggi_data(None), (None, False))

    def test_piu_date_conta_l_ultima(self):
        self.assertEqual(leggi_data("09/10/2024\n12/05/2025"), (dt.date(2025, 5, 12), False))

    def test_quello_che_non_e_una_data_non_lo_diventa(self):
        self.assertEqual(leggi_data("Previsione\n21/10/2020"), (None, True))
        self.assertEqual(leggi_data("16/06/202"), (None, True))
        self.assertEqual(leggi_data(dt.datetime(2099, 1, 1)), (None, True))
        self.assertEqual(leggi_data("In Attesa"), (None, True))


class ImportTests(ImportBase):
    def test_prova_non_scrive(self):
        esito = importa(self.file(riga()))
        self.assertEqual(esito.creati, 1)
        self.assertFalse(FaiRecord.objects.exists())
        self.assertFalse(FaiArticolo.objects.exists())
        self.assertFalse(FaiOpzione.objects.filter(etichetta="F1").exists())

    def test_riga_completa(self):
        importa(self.file(riga(**{
            "P/N": 12345, "NOME PARTICOLARE": "Coperchio", "REV.": "B", "OP": "OP-9", "OdA/ITEM": "O-1", "FAI CN__N°": 7,
            "ANNO__FAI CN": "2025", "CHIUSURA FAI__CON": "Mail", "DATA CHIUSURA__FAI": dt.datetime(2025, 2, 3),
            "DATA INVIO__DOCUMENTAZIONE": dt.datetime(2025, 1, 2), "SDC": "X", "PFC": "?", "SINTESI": "x", "FAI": "N/A",
            "CROSS-CORRELATION": "13/03/18\nInviata Con ZPN", "STATO VERSIONE": "NON Richiesta Approvazione",
        })), applica=True)
        fai = FaiRecord.objects.get()
        self.assertEqual(fai.articolo.part_number, "12345")
        self.assertEqual((fai.nome_particolare, fai.revisione, fai.op, fai.oda_item), ("Coperchio", "B", "OP-9", "O-1"))
        self.assertEqual((fai.fai_numero, fai.fai_anno), ("7", "2025"))
        self.assertEqual((fai.data_invio, fai.data_chiusura), (dt.date(2025, 1, 2), dt.date(2025, 2, 3)))
        self.assertEqual(fai.chiusura_con.etichetta, "Mail")
        self.assertEqual(fai.doc_sdc, FaiDocumento.PRESENTE)
        self.assertEqual(fai.doc_pfc, FaiDocumento.DA_VERIFICARE)
        self.assertEqual(fai.doc_sintesi, FaiDocumento.PRESENTE)
        self.assertEqual(fai.doc_fai, FaiDocumento.NON_APPLICABILE)
        self.assertEqual(fai.cross_correlation.etichetta, "Inviata con ZPN")
        self.assertEqual(fai.stato_versione.etichetta, "Non richiesta approvazione")
        self.assertIsNone(fai.causale)
        self.assertEqual(fai.tipo, "")
        self.assertEqual(fai.linea, "")
        self.assertEqual(fai.origine_excel["cross_correlation"], "13/03/18\nInviata Con ZPN")

    def test_data_a_parole_resta_negli_originali(self):
        esito = importa(self.file(riga(**{"DATA INVIO__DOCUMENTAZIONE": "Previsione\n21/10/2020"})), applica=True)
        fai = FaiRecord.objects.get()
        self.assertIsNone(fai.data_invio)
        self.assertEqual(esito.date_illeggibili, 1)
        self.assertIn("Previsione", fai.origine_excel["data_invio"])

    def test_ref_e_p_n_mancante(self):
        esito = importa(self.file(riga(**{"P/N": None}), riga(SDC="#REF!", **{"OP": "#REF!"})), applica=True)
        self.assertEqual((esito.scartate, esito.creati), (1, 1))
        self.assertEqual(esito.celle_errore, 2)
        self.assertEqual(FaiRecord.objects.get().op, "")

    def test_stati_configurabili_con_la_loro_fase(self):
        importa(self.file(
            riga(**{"STATO__PIANO FAI": "Annullato"}),
            riga(**{"STATO__PIANO FAI": "F2\nChiuso", "PIANO FAI N°": "PF-2"}),
            riga(**{"STATO__PIANO FAI": "SC-QC", "PIANO FAI N°": "PF-3"}),
            riga(**{"STATO__PIANO FAI": "N/A", "PIANO FAI N°": "PF-4"}),
        ), applica=True)
        fase = lambda nome: FaiOpzione.objects.get(gruppo=FaiGruppo.STATO, etichetta=nome).fase  # noqa: E731
        self.assertEqual(fase("Annullato"), FaiFase.ANNULLATO)
        self.assertEqual(fase("F2 Chiuso"), FaiFase.POSITIVO)
        self.assertEqual(fase("SC-QC"), FaiFase.IN_CORSO)
        self.assertEqual(fase("Non indicato"), FaiFase.IN_CORSO)

    def test_articolo_unico_e_cliente_maiuscolo(self):
        importa(self.file(riga(), riga(CLIENTE="CLIENTE ALFA", **{"PIANO FAI N°": "PF-2"})), applica=True)
        self.assertEqual(FaiArticolo.objects.count(), 1)
        self.assertEqual(FaiRecord.objects.count(), 2)

    def test_il_piu_recente_ha_l_id_piu_alto(self):
        importa(self.file(
            riga(**{"PIANO FAI N°": "NUOVO", "DATA CHIUSURA__FAI": dt.datetime(2025, 1, 1)}),
            riga(**{"PIANO FAI N°": "VECCHIO", "DATA CHIUSURA__FAI": dt.datetime(2019, 1, 1)}),
        ), applica=True)
        self.assertEqual(FaiArticolo.objects.get().fai.first().piano_numero, "NUOVO")

    def test_righe_identiche_restano_due(self):
        importa(self.file(riga(), riga()), applica=True)
        self.assertEqual(FaiRecord.objects.count(), 2)
        self.assertEqual(importa(self.file(riga(), riga()), applica=True).invariati, 2)
        self.assertEqual(FaiRecord.objects.count(), 2)

    def test_rilancio_aggiorna_ma_rispetta_il_portale(self):
        importa(self.file(riga(), riga(**{"PIANO FAI N°": "PF-2"})), applica=True)
        toccato = FaiRecord.objects.get(piano_numero="PF-2")
        FaiRecord.objects.filter(pk=toccato.pk).update(
            note="Dal portale", updated_at=timezone.now() + dt.timedelta(hours=1)
        )
        nuovo = self.file(riga(LINEA="Linea 1"), riga(LINEA="Linea 2", **{"PIANO FAI N°": "PF-2"}))
        esito = importa(nuovo, applica=True)
        self.assertEqual((esito.aggiornati, esito.modificati_nel_portale, esito.creati), (1, 1, 0))
        self.assertEqual(FaiRecord.objects.get(piano_numero="PF-1").linea, "Linea 1")
        toccato.refresh_from_db()
        self.assertEqual((toccato.linea, toccato.note), ("", "Dal portale"))

    def test_file_sbagliato(self):
        with self.assertRaises(FileNonValido):
            importa(self.file(riga(), foglio="Altro"))
        with self.assertRaises(FileNonValido):
            importa(self.file(["x"], testata=["CLIENTE"]))

    def test_comando(self):
        report = os.path.join(self.cartella, "report.csv")
        uscita = StringIO()
        call_command("importa_situazione_fai", self.file(riga(**{"P/N": None})), "--report", report, stdout=uscita)
        self.assertIn("PROVA", uscita.getvalue())
        self.assertIn("P/N mancante", open(report, encoding="utf-8-sig").read())
        self.assertFalse(FaiRecord.objects.exists())


class ScadenzaTests(ImportBase):
    def _articolo(self, **campi):
        importa(self.file(riga(**campi)), applica=True)
        return FaiArticolo.objects.get()

    def test_chiusura_vale_finche_manca_la_produzione(self):
        chiusura = timezone.localdate() - dt.timedelta(days=800)
        art = self._articolo(**{"DATA CHIUSURA__FAI": dt.datetime.combine(chiusura, dt.time())})
        stato = stato_articolo(art, art.fai.first())
        self.assertEqual(stato.codice, "da_ripetere")
        self.assertIn("chiusura del FAI", stato.nota)

    def test_produzione_piu_recente_vince(self):
        chiusura = timezone.localdate() - dt.timedelta(days=800)
        art = self._articolo(**{"DATA CHIUSURA__FAI": dt.datetime.combine(chiusura, dt.time())})
        art.ultima_produzione = timezone.localdate() - dt.timedelta(days=30)
        art.ultima_spedizione = timezone.localdate() - dt.timedelta(days=30)
        art.save()
        self.assertEqual(stato_articolo(art, art.fai.first()).codice, "in_regola")

    def test_chiuso_non_e_in_corso_qualunque_sia_lo_stato(self):
        chiusura = timezone.localdate() - dt.timedelta(days=10)
        art = self._articolo(**{"DATA CHIUSURA__FAI": dt.datetime.combine(chiusura, dt.time())})
        self.assertEqual(art.fai.first().stato.fase, FaiFase.IN_CORSO)
        self.assertEqual(stato_articolo(art, art.fai.first()).codice, "in_regola")

    def test_senza_chiusura_e_in_corso(self):
        art = self._articolo()
        self.assertEqual(stato_articolo(art, art.fai.first()).codice, "in_corso")

    def test_annullato_non_conta(self):
        importa(self.file(
            riga(**{"DATA CHIUSURA__FAI": dt.datetime.now() - dt.timedelta(days=30)}),
            riga(**{"STATO__PIANO FAI": "Annullato", "PIANO FAI N°": "PF-2", "DATA CHIUSURA__FAI": dt.datetime.now()}),
        ), applica=True)
        utente = _create_user_with_legacy(username="fai-imp", legacy_user_id=651, role_id=1, role_name="admin")
        progetto = make_project(name="C", created_by=utente, client_name="Cliente Alfa", part_number="PN-1")
        self.assertEqual(esito_progetto(progetto).titolo, "Nessun FAI per scadenza")

    def test_cliente_scritto_diversamente(self):
        importa(self.file(riga(**{"DATA CHIUSURA__FAI": dt.datetime.now()})), applica=True)
        utente = _create_user_with_legacy(username="fai-imp", legacy_user_id=651, role_id=1, role_name="admin")
        progetto = make_project(name="C", created_by=utente, client_name="ALFA SPA", part_number="PN-1")
        self.assertEqual(esito_progetto(progetto).titolo, "Nessun FAI per scadenza")

    def test_prossimo_numero(self):
        importa(self.file(
            riga(**{"FAI CN__N°": 7, "ANNO__FAI CN": "2030"}),
            riga(**{"FAI CN__N°": "12", "ANNO__FAI CN": "2030", "PIANO FAI N°": "PF-2"}),
            riga(**{"FAI CN__N°": "12 Bis", "ANNO__FAI CN": "2030", "PIANO FAI N°": "PF-3"}),
        ), applica=True)
        self.assertEqual(prossimo_numero_fai(2030), "13")
        self.assertEqual(prossimo_numero_fai(2031), "1")


class VisteTests(ImportBase):
    def setUp(self):
        super().setUp()
        self.admin = _create_user_with_legacy(username="fai-adm2", legacy_user_id=652, role_id=1, role_name="admin")
        self.admin.is_superuser = True
        self.admin.is_staff = True
        self.admin.save()
        self.client.force_login(self.admin)
        importa(self.file(
            riga(**{"NOME PARTICOLARE": "Coperchio", "OP": "OP-9", "DATA CHIUSURA__FAI": dt.datetime(2025, 2, 3), "SDC": "X"}),
            riga(**{"CLIENTE": "Cliente Beta", "P/N": "PN-2", "PIANO FAI N°": "PF-2", "STATO__PIANO FAI": "Annullato"}),
        ), applica=True)
        self.url = reverse("tasks:fai_registro")

    def test_tutti_i_fai(self):
        pagina = self.client.get(self.url, {"per": "fai"})
        self.assertEqual(pagina.context["totale"], 2)
        self.assertContains(pagina, "Coperchio")
        self.assertContains(pagina, aggiungi_mesi(dt.date(2025, 2, 3), 24).strftime("%d/%m/%Y"))

    def test_filtri(self):
        conta = lambda **q: self.client.get(self.url, {"per": "fai", **q}).context["totale"]  # noqa: E731
        self.assertEqual(conta(cliente="Cliente Beta"), 1)
        self.assertEqual(conta(q="op-9"), 1)
        self.assertEqual(conta(q="niente"), 0)
        annullato = FaiOpzione.objects.get(etichetta="Annullato")
        self.assertEqual(conta(stato=annullato.pk), 1)

    def test_csv_con_le_colonne_del_file(self):
        testo = self.client.get(self.url, {"per": "fai", "formato": "csv"}).content.decode("utf-8")
        self.assertIn("Nome particolare", testo)
        self.assertIn("Coperchio", testo)
        self.assertIn("Presente", testo)

    def test_per_articolo_senza_gli_annullati(self):
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "PN-1")
        self.assertNotContains(pagina, "PN-2")

    def test_scheda_storica_si_salva_senza_perche(self):
        fai = FaiRecord.objects.get(articolo__part_number="PN-1")
        url = reverse("tasks:fai_scheda", args=[fai.pk])
        pagina = self.client.get(url)
        self.assertContains(pagina, "Dati originali")
        self.assertContains(pagina, "<dt>Nome particolare</dt>")
        self.assertContains(pagina, 'value="Coperchio"')
        risposta = self.client.post(url, {
            "part_number": "PN-1", "client_name": "Cliente Alfa", "stato": fai.stato_id, "op": "OP-10",
            "nome_particolare": "Coperchio", "data_chiusura": "2025-02-03", "doc_sdc": "S",
            "chiusura_con": FaiOpzione.objects.get(gruppo=FaiGruppo.CHIUSURA, etichetta="Mail").pk,
        })
        self.assertEqual(risposta.status_code, 302)
        fai.refresh_from_db()
        self.assertEqual((fai.op, fai.chiusura_con.etichetta, fai.doc_sdc), ("OP-10", "Mail", "S"))

    def test_nuovo_fai_chiede_il_perche_e_propone_il_numero(self):
        url = reverse("tasks:fai_nuovo")
        anno = str(timezone.localdate().year)
        self.assertContains(self.client.get(url), f'value="{anno}"')
        self.assertEqual(self.client.post(url, {"part_number": "X", "stato": FaiOpzione.objects.filter(gruppo="STATO").first().pk}).status_code, 200)
        self.assertFalse(FaiRecord.objects.filter(articolo__part_number="X").exists())

    def test_impostazioni_voci_nuove(self):
        pagina = self.client.get(reverse("tasks:impostazioni"), {"tab": "fai"})
        self.assertContains(pagina, "Chiusura con")
        self.assertContains(pagina, "Cross-correlation")
        voce = FaiOpzione.objects.get(gruppo=FaiGruppo.CROSS, etichetta="Inviata")
        self.client.post(reverse("tasks:impostazioni"), {
            "tab": "fai", "gruppo": "CROSS", "opzione_id": voce.pk, "etichetta": "Inviata al cliente",
            "ordine": 5, "attiva": "on", "fai_action": "aggiorna",
        })
        voce.refresh_from_db()
        self.assertEqual(voce.etichetta, "Inviata al cliente")
