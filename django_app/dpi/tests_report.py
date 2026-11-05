"""Report DPI: conformita' di tutte le persone, registro consegne, perimetro, export."""
from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import magazzino, report
from .models import (
    CategoriaDPI,
    ConfermaConsegnaDPI,
    ConsegnaDPI,
    ModelloDPI,
    MovimentoMagazzinoDPI,
    RichiestaDPI,
    StatoRichiesta,
    TipoDPI,
)

OGGI = date(2026, 9, 30)


def persona(pk, nome, cognome="Prova", reparto="Tornitura", mansione="Operatore"):
    return {"id": pk, "nome": nome, "cognome": cognome, "nominativo": f"{nome} {cognome}", "reparto": reparto, "mansione": mansione, "attivo": True}


class Base(TestCase):
    def setUp(self):
        self.scarpe = CategoriaDPI.objects.create(nome="Scarpe", obbligatoria_mansionario=True, order_index=1)
        self.guanti = CategoriaDPI.objects.create(nome="Guanti", order_index=2)
        patcher = mock.patch("dpi.report._dovute_per_mansione", return_value=({}, False))
        self.mansione = patcher.start()
        self.addCleanup(patcher.stop)

    def _consegna(self, pid, categoria=None, *, giorni_fa=10, scadenza=None, nome="Anna Prova", reparto="Tornitura", **kw):
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria or self.scarpe, stato=StatoRichiesta.CONSEGNATA, richiedente_legacy_id=pid,
            richiedente_nome=nome, richiedente_reparto=reparto, quantita=kw.pop("quantita", 1),
        )
        return ConsegnaDPI.objects.create(
            richiesta=richiesta, data_consegna=date.today() - timedelta(days=giorni_fa), data_scadenza_stimata=scadenza, **kw
        )


class ConformitaTests(Base):
    def _esito(self, pid=1):
        return report.conformita([persona(pid, "Anna")], oggi=OGGI)["persone"][0]

    def test_stati_della_categoria_obbligatoria(self):
        self.assertEqual(self._esito()["esito"], report.MANCANTE)
        c = self._consegna(1, scadenza=OGGI - timedelta(days=1))
        self.assertEqual(self._esito()["esito"], report.SCADUTO)
        ConsegnaDPI.objects.filter(pk=c.pk).update(data_scadenza_stimata=OGGI + timedelta(days=30))
        self.assertEqual(self._esito()["esito"], report.IN_SCADENZA)
        self.assertTrue(self._esito()["conforme"])
        ConsegnaDPI.objects.filter(pk=c.pk).update(data_scadenza_stimata=OGGI + timedelta(days=31))
        self.assertEqual(self._esito()["esito"], report.OK)

    def test_la_mansione_aggiunge_categorie_dovute(self):
        self._consegna(1, scadenza=OGGI + timedelta(days=100))
        self.assertEqual(self._esito()["esito"], report.OK)
        self.mansione.return_value = ({1: [self.guanti]}, False)
        situazione = self._esito()
        self.assertEqual(situazione["esito"], report.MANCANTE)
        self.assertEqual({r["categoria"].nome: r["origine"] for r in situazione["righe"]}, {"Scarpe": "Per tutti", "Guanti": "Dalla mansione"})

    def test_consegna_sostituita_non_conta(self):
        nuova = self._consegna(1, scadenza=OGGI + timedelta(days=100), giorni_fa=5)
        vecchia = self._consegna(1, scadenza=OGGI + timedelta(days=100), giorni_fa=1)
        ConsegnaDPI.objects.filter(pk=vecchia.pk).update(sostituita_da=nuova, data_scadenza_stimata=OGGI - timedelta(days=9))
        self.assertEqual(self._esito()["esito"], report.OK)

    def test_senza_dovuti_e_categorie_non_dovute(self):
        CategoriaDPI.objects.filter(pk=self.scarpe.pk).update(obbligatoria_mansionario=False)
        self.assertEqual(self._esito()["esito"], report.NON_PREVISTO)
        tutte = report.conformita([persona(1, "Anna")], tutte_le_categorie=True, oggi=OGGI)["persone"][0]
        self.assertEqual({r["stato"] for r in tutte["righe"]}, {report.NON_PREVISTO})
        self.assertEqual(tutte["esito"], report.NON_PREVISTO)

    def test_conteggi_e_testo_con_richiesta_in_corso(self):
        RichiestaDPI.objects.create(categoria=self.scarpe, stato=StatoRichiesta.INVIATA, richiedente_legacy_id=1, richiedente_nome="Anna Prova")
        self._consegna(2, scadenza=OGGI - timedelta(days=1))
        self._consegna(3, scadenza=OGGI + timedelta(days=100))
        dati = report.conformita([persona(1, "Anna"), persona(2, "Bruno"), persona(3, "Carla")], oggi=OGGI)
        c = dati["conteggi"]
        self.assertEqual((c["totale"], c["mancante"], c["scaduto"], c["ok"], c["da_sistemare"]), (3, 1, 1, 1, 2))
        self.assertEqual([p["id"] for p in dati["persone"]], [1, 2, 3])
        self.assertIn("in corso", report.testo_da_sistemare(dati["persone"][0]))
        self.assertEqual([p["id"] for p in report.filtra_esito(dati["persone"], report.DA_SISTEMARE)], [1, 2])

    def test_una_persona_conta_in_ogni_stato_che_ha(self):
        self._consegna(1, scadenza=OGGI - timedelta(days=1))
        self.mansione.return_value = ({1: [self.guanti]}, False)
        dati = report.conformita([persona(1, "Anna")], oggi=OGGI)
        c = dati["conteggi"]
        self.assertEqual((c["mancante"], c["scaduto"], c["da_sistemare"], c["ok"]), (1, 1, 1, 0))
        self.assertEqual(dati["persone"][0]["esito"], report.MANCANTE)
        for esito in (report.MANCANTE, report.SCADUTO, report.DA_SISTEMARE):
            self.assertEqual(len(report.filtra_esito(dati["persone"], esito)), c[esito])

    def test_errore_sulle_mansioni_viene_segnalato(self):
        self.mansione.return_value = ({}, True)
        self.assertTrue(report.conformita([persona(1, "Anna")], oggi=OGGI)["errore_requisiti"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PagineTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="dpi-rep2", password="x", email="r2@example.com")
        self.client.force_login(self.admin)
        rows = [persona(i, f"Nome{i:02d}", mansione="=FORMULA()") for i in range(1, 61)]
        for target in ("dpi.views.fetch_anagrafica_rows",):
            p = mock.patch(target, return_value=rows)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("dpi.views.ensure_anagrafica_schema", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_elenco_paginato_con_numeri_su_tutte_le_righe(self):
        r = self.client.get(reverse("dpi:report_persone"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["conteggi"]["totale"], 60)
        self.assertEqual(len(r.context["page_obj"].object_list), 50)
        self.assertContains(r, "Persone 1–50 di 60")

    def test_export_contiene_tutte_le_righe_filtrate(self):
        with mock.patch("dpi.views_report.make_xlsx_response") as xlsx:
            xlsx.return_value = self.client.get(reverse("dpi:report_persone"))
            self.client.get(reverse("dpi:report_persone"), {"export": "xlsx", "esito": "mancante"})
        self.assertEqual(len(xlsx.call_args.kwargs["rows"]), 60)
        pdf = self.client.get(reverse("dpi:report_persone"), {"export": "pdf", "q": "Nome01"})
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertEqual(pdf.content[:4], b"%PDF")

    def test_perimetro_vale_per_elenco_dettaglio_ed_export(self):
        with mock.patch("dpi.views.sistema_ruoli_attivo", return_value=True), mock.patch(
            "dpi.views._anagrafiche_visibili", return_value={1, 2}
        ):
            elenco = self.client.get(reverse("dpi:report_persone"))
            self.assertEqual(elenco.context["conteggi"]["totale"], 2)
            fuori = self.client.get(reverse("dpi:report_conformita"), {"dipendente_id": "3"})
            self.assertIsNone(fuori.context["dipendente"])
            self.assertContains(fuori, "Dipendente non trovato")
            self.assertEqual(len(fuori.context["dipendenti"]), 2)
            dentro = self.client.get(reverse("dpi:report_conformita"), {"dipendente_id": "1"})
            self.assertEqual(dentro.context["dipendente"]["id"], 1)
            self._consegna(1, nome="Dentro Perimetro")
            self._consegna(3, nome="Fuori Perimetro")
            registro = self.client.get(reverse("dpi:report_consegne"))
            self.assertContains(registro, "Dentro Perimetro")
            self.assertNotContains(registro, "Fuori Perimetro")

    def test_elenco_del_dettaglio_non_si_ferma_a_cento(self):
        rows = [persona(i, f"N{i}") for i in range(1, 131)]
        with mock.patch("dpi.views.fetch_anagrafica_rows", return_value=rows):
            r = self.client.get(reverse("dpi:report_conformita"))
        self.assertEqual(len(r.context["dipendenti"]), 130)

    def test_registro_periodo_ricevuta_e_conteggi(self):
        firmata = self._consegna(1, firmato_ricevuta=True, quantita=2, nome="Anna Prova")
        self._consegna(2, nome="Bruno Prova")
        conferma = ConfermaConsegnaDPI.objects.create(richiedente_nome="Carla Prova", destinatario_tipo="DIPENDENTE")
        self._consegna(3, nome="Carla Prova", conferma=conferma)
        self._consegna(4, nome="Dario Vecchio", giorni_fa=200, firmato_ricevuta=True)

        r = self.client.get(reverse("dpi:report_consegne"))
        self.assertEqual(r.context["totali"], {"consegne": 3, "pezzi": 4, "persone": 3})
        stati = {s["chiave"]: s["n"] for s in r.context["stati_ricevuta"]}
        self.assertEqual((stati["firmata"], stati["senza_firma"], stati["da_confermare"]), (1, 1, 1))
        self.assertNotContains(r, "Dario Vecchio")

        solo = self.client.get(reverse("dpi:report_consegne"), {"ricevuta": "senza_firma"})
        self.assertEqual(solo.context["totali"]["consegne"], 1)
        self.assertEqual({s["chiave"]: s["n"] for s in solo.context["stati_ricevuta"]}["firmata"], 1)
        self.assertContains(solo, "Bruno Prova")
        self.assertEqual(report.ricevuta(firmata), report.FIRMATA)

    def test_registro_data_non_valida_ed_export_pdf(self):
        self._consegna(1, firmato_ricevuta=True)
        r = self.client.get(reverse("dpi:report_consegne"), {"da": "domani", "a": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["totali"]["consegne"], 1)
        pdf = self.client.get(reverse("dpi:report_consegne"), {"export": "pdf"})
        self.assertEqual(pdf.content[:4], b"%PDF")
        xlsx = self.client.get(reverse("dpi:report_consegne"), {"export": "xlsx"})
        self.assertEqual(xlsx.content[:2], b"PK")

    def test_riservato_ai_gestori(self):
        with mock.patch("dpi.views_report._is_gestore", return_value=False):
            for nome in ("dpi:report_persone", "dpi:report_consegne"):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 302)
                self.assertEqual(self.client.get(reverse(nome), {"export": "xlsx"}).status_code, 302)

    def test_voce_e_schede(self):
        r = self.client.get(reverse("dpi:report_persone"))
        for testo in ("Registro consegne", "Consumi e magazzino", reverse("dpi:report_consegne"), reverse("dpi:magazzino_report")):
            self.assertContains(r, testo)

    def test_consegne_senza_giacenza_nel_report_magazzino(self):
        tipo = TipoDPI.objects.create(categoria=self.guanti, nome="Da lavoro")
        modello = ModelloDPI.objects.create(tipo=tipo, codice="GT-9", nome="Grip")
        richiesta = RichiestaDPI.objects.create(categoria=self.guanti, modello_dpi=modello, quantita=2, stato=StatoRichiesta.CONSEGNATA, richiedente_nome="Anna Prova")
        magazzino.scarica_per_consegna(richiesta, date.today(), motivo="carico non registrato")
        MovimentoMagazzinoDPI.objects.create(modello=modello, tipo="CARICO", quantita=5)
        r = self.client.get(reverse("dpi:magazzino_report"))
        self.assertEqual([(s["pezzi"], s["motivo"]) for s in r.context["senza_giacenza"]], [(2, "carico non registrato")])
        self.assertContains(r, "Consegne senza giacenza")
