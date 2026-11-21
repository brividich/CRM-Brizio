"""Cambio di stato di un'attività: una regola sola per scheda, «Le mie attività», menu «⋯» e Gantt.

Prima l'incaricato poteva riaprire un'attività annullata da «Le mie attività»
(il menu «⋯» lo riservava al capocommessa) e dal Gantt salvava stato e
avanzamento insieme alla richiesta di spostamento delle date.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from tasks.models import Task, TaskImpostazioni, TaskStatus
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CambioStatoTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="st-pm", legacy_user_id=531, role_id=2, role_name="tasks")
        self.resp = _create_user_with_legacy(username="st-resp", legacy_user_id=532, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa stato", created_by=self.pm, project_manager=self.pm)

    def _task(self, **kwargs):
        dati = {"title": "Programmare la macchina", "project": self.project, "created_by": self.pm,
                "assigned_to": self.resp}
        dati.update(kwargs)
        return Task.objects.create(**dati)

    def _mia(self, task, azione):
        return self.client.post(reverse("tasks:mia_voce_stato", args=["attivita", task.pk]), {"action": azione})

    def test_l_incaricato_non_riapre_un_attivita_annullata(self):
        task = self._task(status=TaskStatus.CANCELED)
        self.client.force_login(self.resp)
        self._mia(task, "reopen")
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CANCELED)

    def test_l_incaricato_riapre_la_sua_attivita_completata(self):
        task = self._task(status=TaskStatus.DONE, progress=100)
        self.client.force_login(self.resp)
        self._mia(task, "reopen")
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertEqual(task.progress, 0)

    def test_il_capocommessa_riapre_un_attivita_annullata(self):
        task = self._task(status=TaskStatus.CANCELED)
        self.client.force_login(self.pm)
        self._mia(task, "reopen")
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)

    def test_la_scheda_dell_incaricato_non_propone_riapri_se_annullata(self):
        task = self._task(status=TaskStatus.CANCELED)
        self.client.force_login(self.resp)
        pagina = self.client.get(reverse("tasks:detail", args=[task.pk]))
        self.assertNotContains(pagina, 'value="reopen"')

    def test_dalla_scheda_riaprire_da_completata_azzera_l_avanzamento(self):
        task = self._task(status=TaskStatus.DONE, progress=100)
        self.client.force_login(self.pm)
        self.client.post(reverse("tasks:change_status", args=[task.pk]), {"status": TaskStatus.TODO})
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertEqual(task.progress, 0)

    def test_dal_gantt_l_incaricato_chiede_solo_le_date(self):
        impostazioni = TaskImpostazioni.get_singleton()
        impostazioni.spostamenti_con_approvazione = True
        impostazioni.save()
        oggi = timezone.localdate()
        task = self._task(next_step_due=oggi, due_date=oggi + timedelta(days=5), progress=10)
        self.client.force_login(self.resp)
        prefisso = f"task_{task.pk}"
        risposta = self.client.post(
            reverse("tasks:project_gantt_update_task", args=[self.project.pk, task.pk]),
            {
                f"{prefisso}-next_step_due": oggi.isoformat(),
                f"{prefisso}-due_date": (oggi + timedelta(days=9)).isoformat(),
                f"{prefisso}-status": TaskStatus.DONE,
                f"{prefisso}-progress": "100",
                f"{prefisso}-priority": "HIGH",
            },
        )
        self.assertEqual(risposta.status_code, 302)
        task.refresh_from_db()
        # Stato, avanzamento e priorità restano quelli di prima; le date aspettano il capocommessa.
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertEqual(task.progress, 10)
        self.assertEqual(task.priority, "MEDIUM")
        self.assertEqual(task.due_date, oggi + timedelta(days=5))
        self.assertEqual(task.spostamenti.filter(stato="IN_ATTESA").count(), 1)
