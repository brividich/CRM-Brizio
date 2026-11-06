"""Registro FAI: calcoli, situazione dell'articolo, opzioni configurabili, permessi e allineamento."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import NavigationItem

from .fai_regole import aggiungi_mesi, prossimo_piano_interno, stato_decorrenza
from .models import (
    FaiArticolo,
    FaiFase,
    FaiGruppo,
    FaiOpzione,
    FaiRecord,
    FaiTipo,
    ProjectTechRef,
    TaskImpostazioni,
    TechRefKind,
    TechRefStatus,
)
from .services.fai import allinea_da_riga, esito_progetto, stato_articolo
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project

OGGI = date(2026, 11, 5)


def causale(etichetta):
    return FaiOpzione.objects.get(gruppo=FaiGruppo.CAUSALE, etichetta=etichetta)


def piano(etichetta):
    return FaiOpzione.objects.get(gruppo=FaiGruppo.PIANO, etichetta=etichetta)


def stato(etichetta):
    return FaiOpzione.objects.get(gruppo=FaiGruppo.STATO, etichetta=etichetta)


def crea_fai(art, stato_nome="Completo con esito positivo", **altri):
    return FaiRecord.objects.create(
        articolo=art, causale=causale("Articolo nuovo"), tipo=FaiTipo.COMPLETO, piano=piano("Interno"),
        stato=stato(stato_nome), **altri,
    )


class CalcoliTests(SimpleTestCase):
    def test_soglie_con_riferimenti_diversi(self):
        # Spedito da poco ma non prodotto da oltre 2 anni: conta la produzione.
        self.assertEqual(stato_decorrenza(OGGI, date(2024, 11, 4), date(2026, 1, 1)).codice, "da_ripetere")
        # Esattamente 2 anni non è «più di due anni».
        self.assertNotEqual(stato_decorrenza(OGGI, date(2024, 11, 5), None).codice, "da_ripetere")
        self.assertEqual(stato_decorrenza(OGGI, None, date(2025, 5, 4)).codice, "da_verificare")
        self.assertEqual(stato_decorrenza(OGGI, None, date(2025, 5, 5)).codice, "in_regola")
        self.assertEqual(stato_decorrenza(OGGI, None, None).codice, "date_mancanti")
        self.assertEqual(stato_decorrenza(OGGI, None, None, date(2026, 11, 4)).codice, "da_ripetere")

    def test_soglie_configurate(self):
        esito = stato_decorrenza(OGGI, None, date(2026, 1, 1), mesi_verifica=6)
        self.assertEqual((esito.codice, esito.etichetta), ("da_verificare", "Oltre 6 mesi"))

    def test_mesi_a_fine_mese(self):
        self.assertEqual(aggiungi_mesi(date(2024, 8, 31), 18), date(2026, 2, 28))

    def test_numero_piano_interno(self):
        self.assertEqual(prossimo_piano_interno("X-1", []), "PFCN_X-1_001_A")
        self.assertEqual(prossimo_piano_interno("X-1", ["PFCN_X-1_001_B", "PFCN_X-1_007_A", "altro"]), "PFCN_X-1_008_A")


class ValoriInizialiTests(TasksBaseTestCase):
    def test_causali_secondo_la_procedura(self):
        delta = FaiOpzione.objects.filter(gruppo=FaiGruppo.CAUSALE, tipo_proposto=FaiTipo.DELTA).count()
        completi = FaiOpzione.objects.filter(gruppo=FaiGruppo.CAUSALE, tipo_proposto=FaiTipo.COMPLETO)
        self.assertEqual(delta, 5)
        self.assertEqual(completi.count(), 3)
        self.assertTrue(all(c.motivo_se_delta for c in completi))
        self.assertTrue(piano("Interno").numerazione_auto)
        self.assertEqual(piano("Interno").stato_op, "INT")


class SituazioneTests(TasksBaseTestCase):
    def _art(self, **date_art):
        return FaiArticolo.objects.create(client_name="Cliente Prova", part_number="PN-1", **date_art)

    def test_fai_in_corso_non_segnala_scadenza(self):
        fai = crea_fai(self._art(ultima_produzione=date(2020, 1, 1)), "In valutazione dal cliente")
        self.assertEqual(stato_articolo(fai.articolo, fai, OGGI).codice, "in_corso")

    def test_fai_positivo_recente_riqualifica(self):
        fai = crea_fai(self._art(ultima_produzione=date(2020, 1, 1)), data_invio=date(2026, 10, 1))
        self.assertEqual(stato_articolo(fai.articolo, fai, OGGI).codice, "in_regola")

    def test_stato_rinominato_conta_il_significato(self):
        fai = crea_fai(self._art(ultima_produzione=date(2020, 1, 1)), "In valutazione dal cliente")
        FaiOpzione.objects.filter(pk=fai.stato_id).update(etichetta="Dal cliente")
        fai = FaiRecord.objects.get(pk=fai.pk)
        self.assertEqual(stato_articolo(fai.articolo, fai, OGGI).codice, "in_corso")

    def test_soglia_da_impostazioni(self):
        cfg = TaskImpostazioni.get_singleton()
        cfg.fai_mesi_ripetizione = 240
        cfg.save()
        fai = crea_fai(self._art(ultima_produzione=date(2020, 1, 1)))
        self.assertNotEqual(stato_articolo(fai.articolo, fai, OGGI).codice, "da_ripetere")

    def test_esito_commessa(self):
        autore = _create_user_with_legacy(username="fai-aut", legacy_user_id=621, role_id=2, role_name="tasks")
        project = make_project(name="Commessa", created_by=autore, client_name="Cliente Prova", part_number="pn-1")
        self.assertEqual(esito_progetto(project).causale, "a")
        crea_fai(self._art(ultima_produzione=date(2020, 1, 1)))
        esito = esito_progetto(project)  # maiuscole diverse: stesso articolo
        self.assertEqual((esito.titolo, esito.causale), ("FAI completo previsto", "f"))
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
            "project": self.project.pk, "part_number": "PN-9", "client_name": "Cliente Prova",
            "causale": causale("Articolo nuovo").pk, "tipo": FaiTipo.COMPLETO, "piano": piano("Interno").pk,
            "stato": stato("Da eseguire").pk, "responsabile": self.user.pk, **altri,
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
        risposta = self.client.post(reverse("tasks:fai_nuovo"), self._dati(path=r"Y:\\fai"))
        self.assertContains(risposta, "cambiano da PC a PC")

    def test_stato_e_riga_restano_allineati(self):
        self.client.post(reverse("tasks:fai_nuovo"), self._dati())
        fai = FaiRecord.objects.get()
        ref = fai.tech_ref
        ref.mark_done(user=self.user)
        ref.save()
        allinea_da_riga(ref)
        fai.refresh_from_db()
        self.assertEqual(fai.stato.fase, FaiFase.IN_CORSO)
        self.client.post(reverse("tasks:fai_scheda", args=[fai.pk]), self._dati(stato=stato("Non completo").pk))
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

    def test_riga_esistente_si_completa_senza_doppioni(self):
        ref = ProjectTechRef.objects.create(project=self.project, kind=TechRefKind.FAI, assigned_to=self.user)
        pagina = self.client.get(reverse("tasks:project_tech_refs", args=[self.project.pk]))
        self.assertContains(pagina, f"ref={ref.pk}")
        self.assertNotContains(pagina, "Apri un FAI")
        self.client.post(reverse("tasks:fai_nuovo"), self._dati(ref=ref.pk))
        self.assertEqual(ProjectTechRef.objects.filter(project=self.project).count(), 1)
        self.assertEqual(FaiRecord.objects.get().tech_ref, ref)

    def test_programmi_e_fai_stanno_separati(self):
        ProjectTechRef.objects.create(project=self.project, kind=TechRefKind.CAM, code="O1001")
        self.client.post(reverse("tasks:fai_nuovo"), self._dati())
        testo = self.client.get(reverse("tasks:project_tech_refs", args=[self.project.pk])).content.decode()
        self.assertLess(testo.index("O1001"), testo.index('<h3 class="tr-sezione">FAI</h3>'))
        self.assertGreater(testo.index("PFCN_PN-9_001_A"), testo.index('<h3 class="tr-sezione">FAI</h3>'))

    def test_elimina_toglie_anche_la_riga(self):
        self.client.post(reverse("tasks:fai_nuovo"), self._dati())
        fai = FaiRecord.objects.get()
        self.client.post(reverse("tasks:fai_scheda", args=[fai.pk]), {"azione": "elimina"})
        self.assertFalse(FaiRecord.objects.exists())
        self.assertFalse(ProjectTechRef.objects.filter(project=self.project).exists())
        self.assertFalse(FaiArticolo.objects.exists())

    def test_registro_csv_e_filtri(self):
        art = FaiArticolo.objects.create(
            client_name="Cliente Prova", part_number="PN-VECCHIO",
            ultima_spedizione=timezone.localdate() - timedelta(days=600),
        )
        crea_fai(art, project=self.project)
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
        fai = crea_fai(art, project=progetto_altrui)
        senza_progetto = crea_fai(FaiArticolo.objects.create(part_number="PN-STORICO"))
        estraneo = _create_user_with_legacy(username="fai-estr", legacy_user_id=624, role_id=2, role_name="tasks")
        self.client.force_login(estraneo)
        pagina = self.client.get(reverse("tasks:fai_registro"))
        self.assertNotContains(pagina, "PN-ALTRUI")
        self.assertNotContains(pagina, "PN-STORICO")
        self.assertEqual(self.client.get(reverse("tasks:fai_scheda", args=[fai.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("tasks:fai_scheda", args=[senza_progetto.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("tasks:fai_nuovo")).status_code, 403)
        self.assertEqual(self.client.post(reverse("tasks:fai_scheda", args=[fai.pk]), {"azione": "elimina"}).status_code, 404)

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


class ImpostazioniFaiTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        self.admin = _create_user_with_legacy(username="fai-adm", legacy_user_id=625, role_id=1, role_name="admin")
        self.admin.is_superuser = True
        self.admin.is_staff = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.url = reverse("tasks:impostazioni")

    def _post(self, **dati):
        return self.client.post(self.url, {"tab": "fai", **dati})

    def test_pagina(self):
        pagina = self.client.get(self.url, {"tab": "fai"})
        self.assertContains(pagina, "Perché serve il FAI")
        self.assertContains(pagina, "Tipi di piano FAI")
        self.assertContains(pagina, "Stati del FAI")

    def test_aggiungi_e_compare_nella_scheda(self):
        self._post(
            fai_action="crea", gruppo="CAUSALE", etichetta="Richiesta audit", descrizione="Dopo un audit",
            tipo_proposto=FaiTipo.DELTA,
        )
        nuova = causale("Richiesta audit")
        self.assertGreater(nuova.ordine, 0)
        self.assertContains(self.client.get(reverse("tasks:fai_nuovo")), "Richiesta audit")

    def test_disattivata_sparisce_ma_resta_sul_fai_che_la_usa(self):
        art = FaiArticolo.objects.create(part_number="PN-1")
        fai = crea_fai(art)
        opzione = causale("Articolo nuovo")
        self._post(fai_action="aggiorna", opzione_id=opzione.pk, etichetta=opzione.etichetta, tipo_proposto=FaiTipo.COMPLETO)
        opzione.refresh_from_db()
        self.assertFalse(opzione.attiva)
        voce = ">Articolo nuovo</option>"
        self.assertNotContains(self.client.get(reverse("tasks:fai_nuovo")), voce)
        self.assertContains(self.client.get(reverse("tasks:fai_scheda", args=[fai.pk])), voce)

    def test_usata_o_riconosciuta_non_si_elimina(self):
        crea_fai(FaiArticolo.objects.create(part_number="PN-1"))
        self._post(fai_action="elimina", opzione_id=stato("Completo con esito positivo").pk)
        self.assertTrue(FaiOpzione.objects.filter(etichetta="Completo con esito positivo").exists())
        self._post(fai_action="elimina", opzione_id=causale("Fermo da oltre 2 anni").pk)
        self.assertTrue(FaiOpzione.objects.filter(etichetta="Fermo da oltre 2 anni").exists())
        self._post(fai_action="elimina", opzione_id=causale("Cambio di sito").pk)
        self.assertFalse(FaiOpzione.objects.filter(etichetta="Cambio di sito").exists())

    def test_deve_restarne_una_attiva(self):
        FaiOpzione.objects.filter(gruppo=FaiGruppo.PIANO).exclude(etichetta="Interno").update(attiva=False)
        opzione = piano("Interno")
        self._post(fai_action="aggiorna", opzione_id=opzione.pk, etichetta="Interno")
        opzione.refresh_from_db()
        self.assertTrue(opzione.attiva)

    def test_soglie(self):
        self._post(fai_action="soglie", fai_mesi_verifica="12", fai_mesi_ripetizione="36")
        cfg = TaskImpostazioni.get_singleton()
        self.assertEqual((cfg.fai_mesi_verifica, cfg.fai_mesi_ripetizione), (12, 36))
