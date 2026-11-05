"""Registro FAI: regole della MT CN 15, situazione dell'articolo, permessi e allineamento."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import NavigationItem

from .fai_regole import (
    COMPLETO,
    DELTA,
    aggiungi_mesi,
    prossimo_piano_interno,
    serve_motivo,
    stato_decorrenza,
    tipo_proposto,
)
from .models import FaiArticolo, FaiPiano, FaiRecord, FaiStato, FaiTipo, ProjectTechRef, TechRefKind, TechRefStatus
from .services.fai import allinea_da_riga, esito_progetto, stato_articolo
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project

OGGI = date(2026, 11, 5)


class RegoleTests(SimpleTestCase):
    def test_tipo_proposto_segue_la_procedura(self):
        for causale in "bcdeh":
            self.assertEqual(tipo_proposto(causale), DELTA)
        for causale in "afg":
            self.assertEqual(tipo_proposto(causale), COMPLETO)

    def test_motivo_solo_se_ci_si_discosta(self):
        self.assertTrue(serve_motivo("a", DELTA))
        self.assertTrue(serve_motivo("f", DELTA))
        self.assertFalse(serve_motivo("c", DELTA))
        self.assertFalse(serve_motivo("c", COMPLETO))
        self.assertFalse(serve_motivo("a", COMPLETO))

    def test_soglie_con_riferimenti_diversi(self):
        # Spedito da poco ma non prodotto da oltre 2 anni: conta la produzione.
        stato = stato_decorrenza(OGGI, date(2024, 11, 4), date(2026, 1, 1))
        self.assertEqual(stato.codice, "da_ripetere")
        # Esattamente 2 anni non è «più di due anni».
        self.assertNotEqual(stato_decorrenza(OGGI, date(2024, 11, 5), None).codice, "da_ripetere")
        self.assertEqual(stato_decorrenza(OGGI, None, date(2025, 5, 4)).codice, "da_verificare")
        self.assertEqual(stato_decorrenza(OGGI, None, date(2025, 5, 5)).codice, "in_regola")
        self.assertEqual(stato_decorrenza(OGGI, None, None).codice, "date_mancanti")
        self.assertEqual(stato_decorrenza(OGGI, None, None, date(2026, 11, 4)).codice, "da_ripetere")

    def test_mesi_a_fine_mese(self):
        self.assertEqual(aggiungi_mesi(date(2024, 8, 31), 18), date(2026, 2, 28))

    def test_numero_piano_interno(self):
        self.assertEqual(prossimo_piano_interno("X-1", []), "PFCN_X-1_001_A")
        self.assertEqual(prossimo_piano_interno("X-1", ["PFCN_X-1_001_B", "PFCN_X-1_007_A", "altro"]), "PFCN_X-1_008_A")


class SituazioneTests(TasksBaseTestCase):
    def _fai(self, stato, invio=None, **articolo):
        art = FaiArticolo.objects.create(client_name="Cliente Prova", part_number="PN-1", **articolo)
        return FaiRecord.objects.create(
            articolo=art, causale="a", tipo=FaiTipo.COMPLETO, stato=stato, data_invio=invio
        )

    def test_fai_in_corso_non_segnala_scadenza(self):
        fai = self._fai(FaiStato.IN_VALUTAZIONE, ultima_produzione=date(2020, 1, 1))
        self.assertEqual(stato_articolo(fai.articolo, fai, OGGI).codice, "in_corso")

    def test_fai_positivo_recente_riqualifica(self):
        fai = self._fai(FaiStato.POSITIVO, invio=date(2026, 10, 1), ultima_produzione=date(2020, 1, 1))
        self.assertEqual(stato_articolo(fai.articolo, fai, OGGI).codice, "in_regola")

    def test_esito_commessa(self):
        autore = _create_user_with_legacy(username="fai-aut", legacy_user_id=621, role_id=2, role_name="tasks")
        project = make_project(name="Commessa", created_by=autore, client_name="Cliente Prova", part_number="pn-1")
        self.assertEqual(esito_progetto(project).causale, "a")
        self._fai(FaiStato.POSITIVO, ultima_produzione=date(2020, 1, 1))
        esito = esito_progetto(project)  # maiuscole diverse: stesso articolo
        self.assertEqual((esito.titolo, esito.causale), ("FAI completo", "f"))
        project.part_number = ""
        self.assertIsNone(esito_progetto(project))


class VisteTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="fai-pm", legacy_user_id=622, role_id=2, role_name="tasks")
        self.client.force_login(self.user)
        self.project = make_project(
            name="Commessa", created_by=self.user, client_name="Cliente Prova", part_number="PN-9"
        )

    def _dati(self, **altri):
        return {
            "project": self.project.pk, "part_number": "PN-9", "client_name": "Cliente Prova", "causale": "a",
            "tipo": FaiTipo.COMPLETO, "piano_tipo": FaiPiano.INTERNO, "stato": FaiStato.DA_ESEGUIRE,
            "responsabile": self.user.pk, **altri,
        }

    def test_salvataggio_crea_riga_e_numero(self):
        risposta = self.client.post(reverse("tasks:fai_nuovo"), self._dati())
        self.assertEqual(risposta.status_code, 302)
        fai = FaiRecord.objects.get()
        self.assertEqual(fai.piano_numero, "PFCN_PN-9_001_A")
        self.assertEqual(fai.tech_ref.kind, TechRefKind.FAI)
        self.assertEqual(fai.tech_ref.assigned_to, self.user)
        self.assertEqual(fai.tech_ref.status, TechRefStatus.OPEN)

    def test_delta_su_completo_chiede_il_motivo_e_non_perde_i_dati(self):
        dati = self._dati(tipo=FaiTipo.DELTA, ultima_produzione="2026-01-15")
        risposta = self.client.post(reverse("tasks:fai_nuovo"), dati)
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "scrivi perché basta un Delta FAI")
        self.assertContains(risposta, 'value="2026-01-15"')
        self.assertFalse(FaiRecord.objects.exists())
        self.client.post(reverse("tasks:fai_nuovo"), {**dati, "motivo": "Stesso processo di un articolo coperto"})
        self.assertEqual(FaiRecord.objects.get().tipo, FaiTipo.DELTA)

    def test_percorso_non_valido(self):
        risposta = self.client.post(reverse("tasks:fai_nuovo"), self._dati(path=r"Y:\fai"))
        self.assertContains(risposta, "cambiano da PC a PC")

    def test_stato_e_riga_restano_allineati(self):
        self.client.post(reverse("tasks:fai_nuovo"), self._dati())
        fai = FaiRecord.objects.get()
        ref = fai.tech_ref
        ref.mark_done(user=self.user)
        ref.save()
        allinea_da_riga(ref)
        fai.refresh_from_db()
        self.assertEqual(fai.stato, FaiStato.ESEGUITO)
        self.client.post(reverse("tasks:fai_scheda", args=[fai.pk]), self._dati(stato=FaiStato.NON_COMPLETO))
        ref.refresh_from_db()
        self.assertEqual(ref.status, TechRefStatus.OPEN)

    def test_riga_collegata_resta_fai(self):
        self.client.post(reverse("tasks:fai_nuovo"), self._dati())
        fai = FaiRecord.objects.get()
        risposta = self.client.post(
            reverse("tasks:tech_ref_save", args=[self.project.pk]),
            {"ref_id": fai.tech_ref_id, "kind": TechRefKind.CAM, "code": "X"},
        )
        self.assertEqual(risposta.status_code, 400)

    def test_riga_esistente_si_collega_senza_doppioni(self):
        ref = ProjectTechRef.objects.create(project=self.project, kind=TechRefKind.FAI, assigned_to=self.user)
        self.client.post(reverse("tasks:fai_nuovo"), self._dati(ref=ref.pk))
        self.assertEqual(ProjectTechRef.objects.filter(project=self.project).count(), 1)
        self.assertEqual(FaiRecord.objects.get().tech_ref, ref)

    def test_registro_csv_e_filtri(self):
        art = FaiArticolo.objects.create(
            client_name="Cliente Prova", part_number="PN-VECCHIO",
            ultima_spedizione=timezone.localdate() - timedelta(days=600),
        )
        FaiRecord.objects.create(
            articolo=art, project=self.project, causale="a", tipo=FaiTipo.COMPLETO, stato=FaiStato.POSITIVO,
        )
        pagina = self.client.get(reverse("tasks:fai_registro"), {"vista": "da_verificare"})
        self.assertContains(pagina, "PN-VECCHIO")
        self.assertContains(pagina, "Controllo trimestrale")
        vuota = self.client.get(reverse("tasks:fai_registro"), {"vista": "da_ripetere"})
        self.assertNotContains(vuota, "PN-VECCHIO")
        csv = self.client.get(reverse("tasks:fai_registro"), {"formato": "csv"})
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("PN-VECCHIO", csv.content.decode("utf-8"))

    def test_fuori_ambito_non_vede(self):
        art = FaiArticolo.objects.create(client_name="Altro", part_number="PN-ALTRUI")
        altro_utente = _create_user_with_legacy(username="fai-altro", legacy_user_id=623, role_id=2, role_name="tasks")
        progetto_altrui = make_project(name="Altrui", created_by=altro_utente)
        fai = FaiRecord.objects.create(articolo=art, project=progetto_altrui, causale="a", tipo=FaiTipo.COMPLETO)
        senza_progetto = FaiRecord.objects.create(
            articolo=FaiArticolo.objects.create(part_number="PN-STORICO"), causale="a", tipo=FaiTipo.COMPLETO
        )
        estraneo = _create_user_with_legacy(username="fai-estr", legacy_user_id=624, role_id=2, role_name="tasks")
        self.client.force_login(estraneo)
        pagina = self.client.get(reverse("tasks:fai_registro"))
        self.assertNotContains(pagina, "PN-ALTRUI")
        self.assertNotContains(pagina, "PN-STORICO")
        self.assertEqual(self.client.get(reverse("tasks:fai_scheda", args=[fai.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("tasks:fai_scheda", args=[senza_progetto.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("tasks:fai_nuovo")).status_code, 403)

    def test_blocco_regola_in_programmi(self):
        pagina = self.client.get(reverse("tasks:project_tech_refs", args=[self.project.pk]))
        self.assertContains(pagina, "Il P/N non è nel registro")
        self.assertContains(pagina, "causale=a")

    def test_voce_di_menu_e_permessi(self):
        from .acl_bootstrap import _ROUTE_BINDINGS

        voce = NavigationItem.objects.get(code="tasks-sub-registro-fai")
        self.assertEqual(voce.route_name, "tasks:fai_registro")
        for nome in ("tasks:fai_registro", "tasks:fai_nuovo", "tasks:fai_scheda"):
            self.assertEqual(_ROUTE_BINDINGS[nome], "tasks.kickoff.projects")
