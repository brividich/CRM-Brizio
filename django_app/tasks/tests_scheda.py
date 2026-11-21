"""Scheda dell'attività: stato in un controllo, cronologia unica, nota, collegamenti, «Sposta la scadenza»."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import override_settings
from django.urls import reverse

from tasks.models import (
    SpostamentoStato,
    Task,
    TaskComment,
    TaskDependency,
    TaskEvent,
    TaskEventType,
    TaskSpostamento,
    TaskStatus,
)
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SchedaAttivitaTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_comment"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="sc-pm", legacy_user_id=561, role_id=2, role_name="tasks")
        self.pm.is_superuser = True
        self.pm.save(update_fields=["is_superuser"])
        self.resp = _create_user_with_legacy(username="sc-resp", legacy_user_id=562, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa scheda", created_by=self.pm, project_manager=self.pm)
        self.project.add_team_member("programmers", self.resp)
        oggi = date(2026, 11, 20)
        self.task = Task.objects.create(
            title="Programma CAM", project=self.project, created_by=self.pm, assigned_to=self.resp,
            next_step_due=oggi, due_date=oggi + timedelta(days=10),
            description="Dall'incontro #2 (18/11/2026)\nUsare il grezzo nuovo.",
        )
        self.prima = Task.objects.create(
            title="Ordine materiale", project=self.project, created_by=self.pm, assigned_to=self.pm,
            due_date=oggi + timedelta(days=2),
        )
        self.url = reverse("tasks:detail", args=[self.task.pk])

    def test_chi_gestisce_vede_un_solo_controllo_di_stato_e_segna_completata(self):
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, 'id="ka-stato-attivita"', count=1)
        self.assertContains(pagina, reverse("tasks:change_status", args=[self.task.pk]))
        self.assertContains(pagina, "Segna completata")
        self.assertNotContains(pagina, "td-stato-btn")

    def test_l_incaricato_cambia_stato_dallo_stesso_controllo_con_le_sue_regole(self):
        self.client.force_login(self.resp)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, 'id="ka-stato-attivita"', count=1)
        self.assertContains(pagina, reverse("tasks:mia_voce_stato", args=["attivita", self.task.pk]))
        self.assertNotContains(pagina, reverse("tasks:change_status", args=[self.task.pk]))
        self.client.post(
            reverse("tasks:mia_voce_stato", args=["attivita", self.task.pk]), {"action": "done", "next": self.url},
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.DONE)

    def test_cronologia_unisce_commenti_stati_e_spostamenti(self):
        TaskComment.objects.create(task=self.task, author=self.pm, body="Grezzo arrivato in magazzino")
        TaskEvent.objects.create(task=self.task, actor=self.pm, type=TaskEventType.COMMENT_ADDED, payload={})
        TaskEvent.objects.create(
            task=self.task, actor=self.pm, type=TaskEventType.STATUS_CHANGE, payload={"from": "TODO", "to": "IN_PROGRESS"},
        )
        TaskEvent.objects.create(task=self.task, actor=self.resp, type=TaskEventType.DATE_REQUEST, payload={
            "azione": "richiesta", "inizio": "2026-11-20", "fine": "2026-12-05", "motivo": "Macchina ferma",
        })
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        cronologia = pagina.context["cronologia"]
        self.assertEqual([v["tipo"] for v in cronologia].count("commento"), 1)
        self.assertEqual(len(cronologia), 3)  # il «commento aggiunto» non si ripete
        self.assertContains(pagina, "Cronologia")
        self.assertContains(pagina, "Grezzo arrivato in magazzino")
        self.assertContains(pagina, "Macchina ferma")
        self.assertNotContains(pagina, ">Storico<")
        self.assertNotContains(pagina, ">Commenti<")

    def test_la_striscia_evidenzia_l_attivita(self):
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        righe = pagina.context["striscia"]["righe"]
        self.assertEqual([r["evidenziata"] for r in righe if r["task"].pk == self.task.pk], [True])
        self.assertContains(pagina, "is-evidenziata", count=1)

    def test_nota_senza_firma_e_la_firma_resta_al_salvataggio(self):
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        self.assertEqual(pagina.context["nota"], "Usare il grezzo nuovo.")
        self.client.post(reverse("tasks:task_nota", args=[self.task.pk]), {"nota": "Grezzo dal fornitore B."})
        self.task.refresh_from_db()
        self.assertEqual(self.task.description, "Dall'incontro #2 (18/11/2026)\nGrezzo dal fornitore B.")
        self.assertTrue(self.task.events.filter(type=TaskEventType.EDIT).exists())

    def test_l_incaricato_non_modifica_la_nota(self):
        self.client.force_login(self.resp)
        pagina = self.client.get(self.url)
        self.assertNotContains(pagina, reverse("tasks:task_nota", args=[self.task.pk]))
        risposta = self.client.post(reverse("tasks:task_nota", args=[self.task.pk]), {"nota": "altro"})
        self.assertIn(risposta.status_code, (302, 403))
        self.task.refresh_from_db()
        self.assertIn("Usare il grezzo nuovo.", self.task.description)

    def test_sposta_scadenza_incaricato_diventa_richiesta_col_motivo(self):
        self.client.force_login(self.resp)
        pagina = self.client.get(self.url)
        # Nella scheda il motivo è richiesto all'incaricato (campo obbligatorio del form).
        self.assertTrue(pagina.context["motivo_obbligatorio"])
        self.assertContains(pagina, 'name="motivo" maxlength="500" required')
        url = reverse("tasks:task_azione_rapida", args=[self.task.pk])
        dati = {"azione": "date", "inizio": "2026-11-20", "fine": "2026-12-10"}
        con = self.client.post(url, {**dati, "motivo": "Macchina in manutenzione"})
        self.assertEqual(con.status_code, 200)
        sp = TaskSpostamento.objects.get(task=self.task)
        self.assertEqual((sp.stato, sp.motivo), (SpostamentoStato.IN_ATTESA, "Macchina in manutenzione"))
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 11, 30))

    def test_sposta_scadenza_pieni_poteri_motivo_facoltativo(self):
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        self.assertFalse(pagina.context["motivo_obbligatorio"])
        risposta = self.client.post(
            reverse("tasks:task_azione_rapida", args=[self.task.pk]),
            {"azione": "date", "inizio": "2026-11-20", "fine": "2026-12-10"},
        )
        self.assertEqual(risposta.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 12, 10))

    def test_collegamenti_visibili_e_modificabili_da_chi_gestisce(self):
        TaskDependency.objects.create(predecessor=self.prima, successor=self.task)
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        self.assertEqual([d.predecessor_id for d in pagina.context["collegamenti_prima"]], [self.prima.pk])
        self.assertContains(pagina, "data-ka-scollega-dep")
        # Già collegata: non si ripropone fra quelle da collegare.
        self.assertEqual(pagina.context["altre_attivita"], [])
        terza = Task.objects.create(title="Collaudo", project=self.project, created_by=self.pm)
        pagina = self.client.get(self.url)
        self.assertEqual([t.pk for t in pagina.context["altre_attivita"]], [terza.pk])
        self.assertContains(pagina, 'data-ka-verso="dopo"')

    def test_l_incaricato_vede_i_collegamenti_ma_non_li_cambia(self):
        TaskDependency.objects.create(predecessor=self.prima, successor=self.task)
        self.client.force_login(self.resp)
        pagina = self.client.get(self.url)
        self.assertContains(pagina, "Ordine materiale")
        self.assertNotContains(pagina, "data-ka-scollega-dep")
        self.assertNotContains(pagina, "data-ka-colleg ")

    def test_dal_registro_la_richiesta_parte_anche_senza_motivo(self):
        """Nel registro attività il motivo è facoltativo: non blocca la richiesta."""
        self.client.force_login(self.resp)
        risposta = self.client.post(
            reverse("tasks:task_azione_rapida", args=[self.task.pk]),
            {"azione": "date", "inizio": "2026-11-20", "fine": "2026-12-10"},
        )
        self.assertEqual(risposta.status_code, 200)
        sp = TaskSpostamento.objects.get(task=self.task)
        self.assertEqual((sp.stato, sp.motivo), (SpostamentoStato.IN_ATTESA, ""))

    def test_modifica_si_apre_nel_pannello_laterale(self):
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        edit = reverse("tasks:edit", args=[self.task.pk])
        self.assertContains(pagina, f'data-preview="{edit}"')
        frammento = self.client.get(edit, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(frammento.status_code, 200)
        self.assertContains(frammento, "data-drawer-form")
        self.assertContains(frammento, 'name="next_step_due"')
