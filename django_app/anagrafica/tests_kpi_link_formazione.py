"""KPI cliccabili di formazione, scadenzari, qualifiche, conformità e skill matrix.

Per ogni pagina principale: la tessera porta alla lista filtrata e la lista
filtrata conta lo stesso numero della tessera (stessa funzione/condizione).
Dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import DipendenteQualifica, TipoQualifica
from .models_formazione import (
    TrainingCourse,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingPlan,
)
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()


def _persona(nome: str, cognome: str, reparto: str = "Officina") -> int:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO anagrafica_dipendenti (nome, cognome, reparto, attivo) VALUES (%s, %s, %s, 1)",
            [nome, cognome, reparto],
        )
        cur.execute("SELECT MAX(id) FROM anagrafica_dipendenti")
        return int(cur.fetchone()[0])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class _Base(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.oggi = timezone.localdate()
        self.su = User.objects.create_superuser("kpi-g1", "kpi-g1@example.com", "x")
        self.client.force_login(self.su)
        self.p1 = _persona("Anna", "Sintetica")
        self.p2 = _persona("Bruno", "Fittizio", "Magazzino")
        self.piano = TrainingPlan.objects.create(codice="P-KPI", nome="Piano KPI", stato="ATTIVO")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="C-KPI-1", titolo="Corso KPI uno", durata_ore_teorica=4, stato="ATTIVO",
        )
        self.corso2 = TrainingCourse.objects.create(
            piano=self.piano, codice="C-KPI-2", titolo="Corso KPI due", durata_ore_teorica=2, stato="ATTIVO",
        )

    def _deadline(self, corso, lid, stato, required=True, giorni=None):
        return TrainingDeadline.objects.create(
            corso=corso, legacy_anagrafica_id=lid, stato_scadenza=stato, is_required=required,
            data_scadenza=(self.oggi + timedelta(days=giorni)) if giorni is not None else None,
        )

    def _get(self, name, query="", **kwargs):
        url = reverse(f"anagrafica:{name}", kwargs=kwargs or None) + query
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, url)
        return resp


class FormazioneDashboardScadenzarioTests(_Base):
    def setUp(self):
        super().setUp()
        self._deadline(self.corso, self.p1, "SCADUTO", giorni=-5)
        self._deadline(self.corso, self.p2, "MAI_FREQUENTATO")
        self._deadline(self.corso2, self.p1, "MAI_FREQUENTATO", required=False)
        self._deadline(self.corso2, self.p2, "IN_SCADENZA_30", giorni=10)
        corso3 = TrainingCourse.objects.create(
            piano=self.piano, codice="C-KPI-3", titolo="Corso KPI tre", durata_ore_teorica=1, stato="ATTIVO",
        )
        self._deadline(corso3, self.p2, "SCADUTO", required=False, giorni=-1)

    def test_obbligatori_mancanti_conta_come_lo_scadenzario(self):
        dash = self._get("formazione_dashboard")
        self.assertEqual(dash.context["kpi_obbligatori_mancanti"], 2)
        href = reverse("anagrafica:formazione_scadenzario") + "?stato=MANCANTE&amp;obbligatori=1"
        self.assertContains(dash, href)
        lista = self._get("formazione_scadenzario", "?stato=MANCANTE&obbligatori=1")
        self.assertEqual(lista.context["totale"], dash.context["kpi_obbligatori_mancanti"])

    def test_scaduti_e_30gg_coerenti_con_la_lista(self):
        dash = self._get("formazione_dashboard")
        for stato, chiave in (("SCADUTO", "kpi_scaduti"), ("IN_SCADENZA_30", "kpi_in_scadenza_30")):
            lista = self._get("formazione_scadenzario", f"?stato={stato}")
            self.assertEqual(lista.context["totale"], dash.context[chiave], stato)

    def test_piani_e_corsi_attivi_escludono_i_disattivati(self):
        TrainingPlan.objects.create(codice="P-OFF", nome="Piano spento", stato="ATTIVO", is_active=False)
        TrainingCourse.objects.create(
            piano=self.piano, codice="C-OFF", titolo="Corso spento", durata_ore_teorica=1,
            stato="ATTIVO", is_active=False,
        )
        dash = self._get("formazione_dashboard")
        self.assertContains(dash, reverse("anagrafica:formazione_piani_list") + "?stato=ATTIVO&amp;attivi=1")
        self.assertContains(dash, reverse("anagrafica:formazione_corsi_list") + "?stato=ATTIVO&amp;attivi=1")
        piani = self._get("formazione_piani_list", "?stato=ATTIVO&attivi=1")
        self.assertEqual(len(piani.context["piani"]), dash.context["kpi_piani_attivi"])
        corsi = self._get("formazione_corsi_list", "?stato=ATTIVO&attivi=1")
        self.assertEqual(corsi.context["page_obj"].paginator.count, dash.context["kpi_corsi_attivi"])

    def test_tessere_scadenzario_rispettano_corso_e_mai_obbligatori(self):
        resp = self._get("formazione_scadenzario", f"?corso={self.corso.pk}")
        # Con il corso scelto le tessere contano solo quel corso, come la lista che aprono.
        self.assertEqual(resp.context["n_scaduti"], 1)
        self.assertEqual(resp.context["n_30gg"], 0)
        self.assertEqual(resp.context["n_mai"], 1)
        self.assertContains(resp, f"?stato=MAI_FREQUENTATO&amp;obbligatori=1&amp;corso={self.corso.pk}")
        mai = self._get("formazione_scadenzario", f"?stato=MAI_FREQUENTATO&obbligatori=1&corso={self.corso.pk}")
        self.assertEqual(mai.context["totale"], resp.context["n_mai"])

    def test_filtro_dipendente(self):
        resp = self._get("formazione_scadenzario", f"?dipendente={self.p2}")
        self.assertEqual(
            resp.context["totale"],
            TrainingDeadline.objects.filter(
                legacy_anagrafica_id=self.p2,
                stato_scadenza__in=["SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90", "MAI_FREQUENTATO"],
            ).count(),
        )
        self.assertEqual(resp.context["n_30gg"], 1)


class CoperturaCcnlTests(_Base):
    def test_copertura_tessere_contano_senza_il_filtro_stato(self):
        senza = self._get("formazione_copertura")
        con = self._get("formazione_copertura", "?stato=IN_SCADENZA_30")
        self.assertEqual(senza.context["n_scaduti"], con.context["n_scaduti"])
        self.assertEqual(senza.context["n_mai"], con.context["n_mai"])
        self.assertContains(senza, "#copertura-elenco")

    def test_ccnl_link_alle_liste_filtrate(self):
        resp = self._get("formazione_ccnl_dashboard", "?reparto=Officina")
        self.assertContains(resp, "?stato=COMPLETO&amp;reparto=Officina#ccnl-elenco")
        self.assertContains(resp, "?stato=DA_INIZIARE&amp;reparto=Officina#ccnl-elenco")
        da_iniziare = self._get("formazione_ccnl_dashboard", "?reparto=Officina&stato=DA_INIZIARE")
        self.assertEqual(da_iniziare.context["totale"], resp.context["n_da_iniziare"])


class EntiElearningTests(_Base):
    def test_enti_report_erogato(self):
        resp = self._get("formazione_enti_report")
        self.assertContains(resp, "?erogato=1#enti-elenco")
        filtrato = self._get("formazione_enti_report", "?erogato=1")
        self.assertEqual(len(filtrato.context["righe_elenco"]), resp.context["enti_attivi"])

    def test_elearning_hub_viste(self):
        TrainingCourse.objects.create(
            piano=self.piano, codice="EL-1", titolo="Micro corso", durata_ore_teorica=1,
            is_elearning=True, stato="ATTIVO",
        )
        hub = self._get("formazione_elearning_hub")
        tot = hub.context["tot"]
        self.assertEqual(len(self._get("formazione_elearning_hub", "?vista=pubblicati").context["rows"]),
                         tot["pubblicati"])
        self.assertEqual(len(self._get("formazione_elearning_hub", "?vista=problemi").context["rows"]),
                         tot["problemi"])
        self.assertContains(hub, "?vista=problemi#elearning-corsi")


class ScadenzarioGeneraleTests(_Base):
    def setUp(self):
        super().setUp()
        tipo = TipoQualifica.objects.create(nome="Patentino KPI sintetico", durata_mesi=12)
        for lid, giorni in ((self.p1, -3), (self.p2, 10), (self.p1, 45)):
            t = tipo if giorni != 45 else TipoQualifica.objects.create(nome="Altro patentino KPI", durata_mesi=12)
            DipendenteQualifica.objects.create(
                legacy_anagrafica_id=lid, tipo=t,
                data_conseguimento=self.oggi - timedelta(days=300),
                data_scadenza=self.oggi + timedelta(days=giorni),
            )

    def test_tessere_uguali_alle_liste(self):
        resp = self._get("scadenzario", "?tipo=qualifica")
        self.assertEqual((resp.context["n_scadute"], resp.context["n_30gg"], resp.context["n_60gg"]), (1, 1, 2))
        for stato, chiave in (("scaduta", "n_scadute"), ("30", "n_30gg"), ("60", "n_60gg")):
            lista = self._get("scadenzario", f"?tipo=qualifica&stato={stato}")
            self.assertEqual(lista.context["totale"], resp.context[chiave], stato)
            # Il filtro di stato non cambia le tessere.
            self.assertEqual(lista.context["n_60gg"], resp.context["n_60gg"])
        self.assertContains(resp, "?stato=scaduta&amp;tipo=qualifica#scad-elenco")


class QualificheConformitaTests(_Base):
    def test_da_verificare_porta_allo_scadenzario_filtrato(self):
        resp = self._get("qualifiche_dashboard")
        self.assertContains(resp, "verifica=da_fare")
        lista = self._get("qualifiche_scadenzario", "?stato=tutte&verifica=da_fare")
        self.assertEqual(lista.context["totale"], resp.context["n_da_verificare"])

    def test_conformita_tessere_ignorano_il_filtro_esito(self):
        senza = self._get("conformita_report", "?reparto=Officina")
        con = self._get("conformita_report", "?reparto=Officina&esito=ok")
        for k in ("n_ko", "n_warn", "n_ok", "n_na"):
            self.assertEqual(senza.context[k], con.context[k], k)
        self.assertEqual(con.context["totale"], senza.context["n_ok"])
        self.assertIn("reparto=Officina", senza.context["kpi_links"]["na"])
        self.assertIn("esito=na", senza.context["kpi_links"]["na"])

    def test_libretto_sanitario_link_conservano_i_filtri(self):
        resp = self._get("libretto_sanitario_generale", "?reparto=Officina")
        self.assertIn("reparto=Officina", resp.context["kpi_links"]["ko"])
        self.assertIn("vista=requisiti", resp.context["kpi_links"]["warn"])


class AttestatiSkillMatrixTests(_Base):
    def test_attestati_da_archiviare_contano_i_completamenti_senza_documento(self):
        TrainingEmployeeRecord.objects.create(
            corso=self.corso, legacy_anagrafica_id=self.p1, data_completamento=self.oggi,
        )
        resp = self._get("attestato_impostazioni")
        self.assertEqual(resp.context["n_mancanti"], 1)

    def test_skm_copertura_e_scadenzario_filtri(self):
        cop = self._get("skm_copertura", "?coperta=no")
        self.assertEqual(len(cop.context["righe"]), cop.context["kpi"]["scoperte"])
        sc = self._get("skm_scadenzario", "?campagna=aperta")
        self.assertEqual(sc.context["totale"], sc.context["kpi"]["campagne_aperte"])

    def test_skill_matrix_filtro_macchine(self):
        resp = self._get("skill_matrix_macchina", "?macchine=scoperte")
        self.assertEqual(resp.context["n_macchine"], resp.context["kpi"]["scoperte"])
