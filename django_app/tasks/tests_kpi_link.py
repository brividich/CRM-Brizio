"""Tessere KPI cliccabili del KICK-OFF: ogni tessera apre l'elenco che conta lo stesso numero."""
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .action_register import build_project_actions, filter_action_rows
from .models import MeetingIssue, MeetingIssueStatus, Task, TaskStatus
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskKpiLinkTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(7, "tasks")
        _grant_role_actions(7, ["tasks_view", "tasks_create", "tasks_edit", "tasks_admin"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="kpi-admin", legacy_user_id=9701, role_id=7, role_name="tasks")
        self.client.force_login(self.user)
        oggi = timezone.localdate()
        self.project = make_project(name="KPI kickoff", client_name="Cliente KPI", created_by=self.user)
        altro = make_project(name="Altro kickoff", client_name="Cliente B", created_by=self.user)
        Task.objects.create(title="Da fare scaduta", project=self.project, status=TaskStatus.TODO,
                            due_date=oggi - timedelta(days=2), created_by=self.user)
        Task.objects.create(title="In corso a breve", project=self.project, status=TaskStatus.IN_PROGRESS,
                            due_date=oggi + timedelta(days=3), created_by=self.user, assigned_to=self.user)
        Task.objects.create(title="Chiusa a breve", project=self.project, status=TaskStatus.DONE,
                            due_date=oggi + timedelta(days=2), created_by=self.user)
        Task.objects.create(title="Annullata", project=self.project, status=TaskStatus.CANCELED, created_by=self.user)
        Task.objects.create(title="Fuori kickoff", project=altro, status=TaskStatus.TODO, created_by=self.user)

    def _conta(self, query: str) -> int:
        r = self.client.get(reverse("tasks:list") + query)
        self.assertEqual(r.status_code, 200)
        return len(r.context["tasks"])

    def test_tessere_elenco_aprono_lo_stesso_numero(self):
        r = self.client.get(reverse("tasks:list"))
        stats = r.context["dashboard_stats"]
        u = reverse("tasks:list")
        self.assertContains(r, f'href="{u}?mine=0&amp;status=TODO"')
        self.assertContains(r, f'href="{u}?mine=0&amp;overdue=on"')
        self.assertEqual(self._conta("?mine=0"), stats["total"])
        self.assertEqual(self._conta("?mine=0&status=TODO"), stats["todo"])
        self.assertEqual(self._conta("?mine=0&status=IN_PROGRESS"), stats["in_progress"])
        self.assertEqual(self._conta("?mine=0&status=DONE"), stats["done"])
        self.assertEqual(self._conta("?mine=0&status=CANCELED"), stats["canceled"])
        self.assertEqual(self._conta("?mine=0&overdue=on"), stats["overdue"])

    def test_kpi_del_kickoff_non_dipendono_dagli_altri_filtri(self):
        base = f"?mine=0&project={self.project.pk}"
        r = self.client.get(reverse("tasks:list") + base + "&status=DONE")
        stats = r.context["dashboard_stats"]
        # Con il filtro «Completate» attivo le tessere restano quelle del kickoff.
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["todo"], 1)
        self.assertEqual(self._conta(base + "&status=TODO"), stats["todo"])
        self.assertEqual(self._conta(base), stats["total"])

    def test_gantt_tessere(self):
        r = self.client.get(reverse("tasks:project_gantt", args=[self.project.pk]))
        self.assertEqual(r.status_code, 200)
        s = r.context["project_summary"]
        base = f"?mine=0&project={self.project.pk}"
        finestra = (f"&open=on&due_from={s['due_window_from']:%Y-%m-%d}&due_to={s['due_window_to']:%Y-%m-%d}")
        self.assertContains(r, "kpi-link")
        self.assertEqual(self._conta(base), s["total_tasks"])
        self.assertEqual(self._conta(base + "&overdue=on"), s["overdue_tasks"])
        self.assertEqual(self._conta(base + finestra), s["due_next_7d_tasks"])
        self.assertEqual(self._conta(base + "&unassigned=on"), s["unassigned_tasks"])
        self.assertEqual(self._conta(base + "&status=DONE"), s["done_tasks"])

    def test_impostazioni_riepilogo(self):
        self.user.is_superuser = True
        self.user.save()
        r = self.client.get(reverse("tasks:impostazioni") + "?tab=riepilogo")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'href="{reverse("tasks:project_list")}"')
        self.assertEqual(self._conta("?mine=0"), r.context["total_tasks"])
        self.assertEqual(self._conta("?mine=0&status=IN_PROGRESS"), r.context["in_progress_count"])
        self.assertEqual(self._conta("?mine=0&overdue=on"), r.context["tasks_overdue"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RegistroAzioniKpiTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(8, "tasks")
        _grant_role_actions(8, ["tasks_view", "tasks_admin"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="kpi-reg", legacy_user_id=9702, role_id=8, role_name="tasks")
        self.client.force_login(self.user)
        oggi = timezone.localdate()
        self.project = make_project(name="Registro KPI", client_name="Cliente R", created_by=self.user)
        Task.objects.create(title="Aperta senza resp", project=self.project, status=TaskStatus.TODO, created_by=self.user)
        Task.objects.create(title="Scaduta", project=self.project, status=TaskStatus.TODO,
                            due_date=oggi - timedelta(days=1), assigned_to=self.user, created_by=self.user)
        Task.objects.create(title="Chiusa", project=self.project, status=TaskStatus.DONE, created_by=self.user)
        MeetingIssue.objects.create(project=self.project, title="Problema chiuso", status=MeetingIssueStatus.RESOLVED)

    def test_tessere_e_filtri_usano_la_stessa_funzione(self):
        url = reverse("tasks:project_actions", args=[self.project.pk])
        r = self.client.get(url + "?closed=1")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="' + url + '?closed=1&amp;stato=chiuse"')
        tutte = build_project_actions(self.project, include_closed=True)
        for query, chiave in (
            ("?stato=aperte", "open_count"),
            ("?scadenza=scadute", "overdue_count"),
            ("?stato=aperte&responsabile=nessuno", "unassigned_count"),
            ("?scadenza=senza", "no_due_count"),
            ("?closed=1&stato=chiuse", "closed_count"),
        ):
            filtrata = self.client.get(url + query)
            self.assertEqual(len(filtrata.context["actions"]), r.context[chiave], query)
        self.assertEqual(len(filter_action_rows(tutte, stato="chiuse")), 2)
