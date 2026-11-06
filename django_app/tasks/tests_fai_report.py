"""Report FAI, scheda FAI e scheda attività ridisegnate."""
from __future__ import annotations

import datetime as dt
from io import BytesIO

import openpyxl
from django.urls import reverse
from django.utils import timezone

from .fai_regole import aggiungi_mesi
from .models import FaiArticolo, FaiFase, FaiGruppo, FaiOpzione, FaiRecord, Task, TaskStatus
from .services import fai_report as rep
from .services.fai import righe_registro, ripetizione_entro
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


class FaiBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        self.admin = _create_user_with_legacy(username="rep-adm", legacy_user_id=661, role_id=1, role_name="admin")
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.stato_ok = FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO, fase=FaiFase.POSITIVO).first()
        self.stato_corso = FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO, fase=FaiFase.IN_CORSO).first()
        self.scaduto = self._fai("Cliente Alfa", "PN-OLD", chiusura=aggiungi_mesi(self.oggi, -30))
        self.vicino = self._fai("Cliente Alfa", "PN-NEAR", chiusura=aggiungi_mesi(self.oggi, -20))
        self.lontano = self._fai("Cliente Beta", "PN-OK", chiusura=self.oggi - dt.timedelta(days=10))
        self.aperto = self._fai("Cliente Beta", "PN-RUN", stato=self.stato_corso)

    def _fai(self, cliente, pn, chiusura=None, stato=None):
        articolo = FaiArticolo.objects.create(client_name=cliente, part_number=pn)
        return FaiRecord.objects.create(
            articolo=articolo, stato=stato or self.stato_ok, tipo="COMPLETO",
            data_invio=chiusura - dt.timedelta(days=20) if chiusura else self.oggi, data_chiusura=chiusura,
        )

    def _righe(self):
        return righe_registro(FaiRecord.objects.select_related("articolo", "stato", "responsabile").all())


class ServizioReportTest(FaiBase):
    def test_ripetizione_dalla_chiusura_e_nessuna_se_in_corso(self):
        self.assertEqual(ripetizione_entro(self.scaduto.articolo, self.scaduto), aggiungi_mesi(self.scaduto.data_chiusura, 24))
        self.assertIsNone(ripetizione_entro(self.aperto.articolo, self.aperto))

    def test_il_cliente_puo_anticipare_la_ripetizione(self):
        articolo = self.lontano.articolo
        articolo.scadenza_cliente = self.oggi + dt.timedelta(days=5)
        articolo.save()
        self.assertEqual(ripetizione_entro(articolo, self.lontano), articolo.scadenza_cliente)

    def test_scadenze_prende_scaduti_e_vicini_non_i_lontani(self):
        nomi = [r["articolo"].part_number for r in rep.scadenze(self._righe())]
        self.assertEqual(nomi, ["PN-OLD", "PN-NEAR"])

    def test_per_cliente_torna_col_totale(self):
        righe = self._righe()
        riepilogo = rep.per_cliente(righe)
        self.assertEqual([r["cliente"] for r in riepilogo], ["Cliente Alfa", "Cliente Beta"])
        self.assertEqual(sum(r["totale"] for r in riepilogo), len(righe))

    def test_per_anno_esclude_chiusure_prima_dell_invio_dalla_media(self):
        sbagliato = self._fai("Cliente Gamma", "PN-BAD")
        sbagliato.data_invio = dt.date(2019, 6, 10)
        sbagliato.data_chiusura = dt.date(2019, 6, 1)
        sbagliato.save()
        riga = next(r for r in rep.per_anno(FaiRecord.objects.all()) if r["anno"] == 2019)
        self.assertEqual((riga["inviati"], riga["chiusi"], riga["giorni"]), (1, 1, None))


class PaginaReportTest(FaiBase):
    def test_conteggi_uguali_al_registro(self):
        pagina = self.client.get(reverse("tasks:fai_report"))
        self.assertEqual(pagina.status_code, 200)
        registro = self.client.get(reverse("tasks:fai_registro"))
        conti = {v["codice"]: v["conta"] for v in registro.context["viste"]}
        for vista in pagina.context["viste"]:
            if vista["codice"] in conti:
                self.assertEqual(vista["conta"], conti[vista["codice"]], vista["codice"])

    def test_filtro_cliente_vale_per_pagina_e_file(self):
        pagina = self.client.get(reverse("tasks:fai_report"), {"cliente": "Cliente Beta"})
        self.assertEqual(pagina.context["viste"][0]["conta"], 2)
        risposta = self.client.get(
            reverse("tasks:fai_report_scarica"), {"report": "situazione", "formato": "xlsx", "cliente": "Cliente Beta"}
        )
        testo = " ".join(
            str(c) for riga in openpyxl.load_workbook(BytesIO(risposta.content)).active.iter_rows(values_only=True) for c in riga if c
        )
        self.assertIn("PN-OK", testo)
        self.assertNotIn("PN-OLD", testo)

    def test_tutti_i_report_si_scaricano(self):
        for voce in rep.REPORT:
            for formato in ("xlsx", "pdf") if voce.pdf else ("xlsx",):
                risposta = self.client.get(reverse("tasks:fai_report_scarica"), {"report": voce.chiave, "formato": formato})
                self.assertEqual(risposta.status_code, 200, (voce.chiave, formato))
                self.assertIn(f"report_fai_{voce.chiave}", risposta["Content-Disposition"])

    def test_richieste_non_valide(self):
        url = reverse("tasks:fai_report_scarica")
        self.assertEqual(self.client.get(url, {"report": "altro"}).status_code, 404)
        self.assertEqual(self.client.get(url, {"report": "tutti", "formato": "pdf"}).status_code, 404)

    def test_chi_non_ha_la_gestione_non_vede_i_fai_fuori_ambito(self):
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view"])
        self.client.force_login(_create_user_with_legacy(username="rep-est", legacy_user_id=662, role_id=2, role_name="tasks"))
        pagina = self.client.get(reverse("tasks:fai_report"))
        self.assertEqual(pagina.context["viste"][0]["conta"], 0)
        risposta = self.client.get(reverse("tasks:fai_report_scarica"), {"report": "situazione", "formato": "pdf"})
        self.assertEqual(risposta.status_code, 200)


class SchedeTest(FaiBase):
    def test_scheda_fai_mostra_situazione_e_ripetizione(self):
        pagina = self.client.get(reverse("tasks:fai_scheda", args=[self.vicino.pk]))
        self.assertContains(pagina, "Ripetizione entro")
        self.assertEqual(pagina.context["situazione"].codice, "da_verificare")
        self.assertFalse(pagina.context["ha_versione"])
        for nome in ("part_number", "op", "doc_sdc", "cross_correlation", "ultima_produzione", "note"):
            self.assertContains(pagina, f'name="{nome}"')

    def test_il_blocco_versione_si_apre_se_ha_dati(self):
        self.vicino.codice_dip = "DIP-1"
        self.vicino.save()
        self.assertTrue(self.client.get(reverse("tasks:fai_scheda", args=[self.vicino.pk])).context["ha_versione"])

    def test_scheda_attivita(self):
        project = make_project(name="Kickoff di prova", created_by=self.admin)
        task = Task.objects.create(title="Attività di prova", project=project, created_by=self.admin, status=TaskStatus.TODO)
        pagina = self.client.get(reverse("tasks:detail", args=[task.pk]))
        self.assertContains(pagina, 'value="IN_PROGRESS"')
        self.assertContains(pagina, "Sotto-attività")
        self.assertContains(pagina, "Storico")
        self.assertNotContains(pagina, "Overdue")
        self.assertNotContains(pagina, "Subscribers")
        risposta = self.client.post(reverse("tasks:change_status", args=[task.pk]), {"status": "IN_PROGRESS"})
        self.assertEqual(risposta.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, "IN_PROGRESS")
