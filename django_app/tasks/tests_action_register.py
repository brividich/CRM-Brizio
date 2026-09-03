from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .action_register import build_project_actions
from .models import (
    KickoffMeeting,
    MeetingIssue,
    MeetingIssueStatus,
    Project,
    SubTask,
    Task,
    TaskStatus,
)
from .tests import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions
from .views_projects import project_actions

User = get_user_model()


class ActionRegisterTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="action-owner",
            first_name="Ada",
            last_name="Rossi",
        )
        self.project = Project.objects.create(name="", created_by=self.owner)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            numero=3,
            data=timezone.localdate(),
            created_by=self.owner,
        )

    def _task(self, title, *, due_date=None, status=TaskStatus.TODO):
        return Task.objects.create(
            title=title,
            project=self.project,
            created_by=self.owner,
            assigned_to=self.owner,
            due_date=due_date,
            status=status,
        )

    def test_all_origins_have_expected_labels_owners_and_urls(self):
        issue = MeetingIssue.objects.create(
            project=self.project,
            source_meeting=self.meeting,
            title="Verificare requisito",
            assigned_to=self.owner,
            created_by=self.owner,
        )
        task = self._task("Preparare campione")
        subtask = SubTask.objects.create(
            task=task,
            title="Confermare materiale",
            assigned_to=self.owner,
        )

        rows = build_project_actions(self.project)
        by_origin = {row.origin: row for row in rows}

        self.assertEqual(set(by_origin), {"issue", "task", "subtask"})
        self.assertEqual(by_origin["issue"].source_label, "Incontro 3")
        self.assertEqual(by_origin["issue"].owner_label, "Ada Rossi")
        self.assertEqual(
            by_origin["issue"].url,
            f"{reverse('tasks:project_meeting_detail', args=[self.project.pk, self.meeting.pk])}#issue-{issue.pk}",
        )
        self.assertEqual(by_origin["task"].source_label, "Attivita")
        self.assertEqual(by_origin["task"].url, reverse("tasks:detail", args=[task.pk]))
        self.assertEqual(
            by_origin["subtask"].source_label,
            "Sotto-attivita di «Preparare campione»",
        )
        self.assertEqual(by_origin["subtask"].obj_id, subtask.pk)
        self.assertEqual(by_origin["subtask"].url, reverse("tasks:detail", args=[task.pk]))

    def test_order_is_overdue_future_no_due_then_closed(self):
        today = timezone.localdate()
        self._task("Scaduta più recente", due_date=today - timedelta(days=1))
        self._task("Scaduta più vecchia", due_date=today - timedelta(days=5))
        self._task("Futura due", due_date=today + timedelta(days=7))
        self._task("Futura uno", due_date=today + timedelta(days=2))
        self._task("Zeta senza data")
        self._task("Alfa senza data")
        self._task("Chiusa", due_date=today - timedelta(days=20), status=TaskStatus.DONE)

        rows = build_project_actions(self.project, include_closed=True)

        self.assertEqual(
            [row.title for row in rows],
            [
                "Scaduta più vecchia",
                "Scaduta più recente",
                "Futura uno",
                "Futura due",
                "Alfa senza data",
                "Zeta senza data",
                "Chiusa",
            ],
        )

    def test_done_task_with_past_due_date_is_not_overdue(self):
        task = self._task(
            "Conclusa ieri",
            due_date=timezone.localdate() - timedelta(days=1),
            status=TaskStatus.DONE,
        )

        row = next(
            row
            for row in build_project_actions(self.project, include_closed=True)
            if row.origin == "task" and row.obj_id == task.pk
        )

        self.assertFalse(task.is_overdue)
        self.assertFalse(row.is_open)
        self.assertFalse(row.is_overdue)

    def test_issue_without_source_meeting_does_not_crash(self):
        issue = MeetingIssue.objects.create(
            project=self.project,
            source_meeting=None,
            title="Issue importata",
            created_by=self.owner,
        )

        row = next(row for row in build_project_actions(self.project) if row.obj_id == issue.pk)

        self.assertEqual(row.source_label, "Senza incontro")
        self.assertEqual(
            row.url,
            f"{reverse('tasks:project_meetings', args=[self.project.pk])}#issue-{issue.pk}",
        )

    def test_closed_rows_are_excluded_by_default(self):
        self._task("Da fare")
        self._task("Completata", status=TaskStatus.DONE)
        parent = self._task("Contenitore", status=TaskStatus.CANCELED)
        SubTask.objects.create(task=parent, title="Sotto-task chiusa", status=TaskStatus.DONE)
        MeetingIssue.objects.create(
            project=self.project,
            title="Issue risolta",
            status=MeetingIssueStatus.RESOLVED,
            created_by=self.owner,
        )

        titles = [row.title for row in build_project_actions(self.project)]

        self.assertEqual(titles, ["Da fare"])

    def test_builder_uses_one_query_per_source(self):
        self._task("Attività")
        MeetingIssue.objects.create(
            project=self.project,
            source_meeting=self.meeting,
            title="Issue",
            created_by=self.owner,
        )

        with self.assertNumQueries(3):
            rows = build_project_actions(self.project)

        self.assertEqual(len(rows), 2)

    def test_failure_of_one_source_keeps_other_sources(self):
        self._task("Attività superstite")

        with patch("tasks.action_register._collect_issues", side_effect=RuntimeError("test")):
            rows = build_project_actions(self.project)

        self.assertEqual([row.title for row in rows], ["Attività superstite"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ProjectActionsViewTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="actions-visible",
            legacy_user_id=9201,
            role_id=2,
            role_name="tasks",
        )
        self.outsider = _create_user_with_legacy(
            username="actions-outsider",
            legacy_user_id=9202,
            role_id=2,
            role_name="tasks",
        )
        self.project = Project.objects.create(name="", created_by=self.user)
        Task.objects.create(
            title="Azione aperta",
            project=self.project,
            created_by=self.user,
        )
        Task.objects.create(
            title="Azione chiusa",
            project=self.project,
            created_by=self.user,
            status=TaskStatus.DONE,
        )

    def test_view_renders_open_rows_and_closed_filter(self):
        self.client.force_login(self.user)

        open_response = self.client.get(reverse("tasks:project_actions", args=[self.project.pk]))
        closed_response = self.client.get(
            reverse("tasks:project_actions", args=[self.project.pk]),
            {"closed": "1"},
        )

        self.assertEqual(open_response.status_code, 200)
        self.assertContains(open_response, "1 aperte, 0 scadute")
        self.assertContains(open_response, "Azione aperta")
        self.assertNotContains(open_response, "Azione chiusa")
        self.assertContains(closed_response, "Azione chiusa")

    def test_view_returns_404_outside_project_scope(self):
        self.client.force_login(self.outsider)

        response = self.client.get(reverse("tasks:project_actions", args=[self.project.pk]))

        self.assertEqual(response.status_code, 404)

    def test_view_query_budget_is_four_queries(self):
        """Budget: progetto scoped (1) + issue, task e subtask (3)."""
        admin = User.objects.create_superuser(username="actions-admin", password="pass12345")
        request = RequestFactory().get(reverse("tasks:project_actions", args=[self.project.pk]))
        request.user = admin

        def render_without_template_queries(request, template_name, context):
            return HttpResponse(f"{template_name}:{context['open_count']}")

        with patch("tasks.views_projects.render", side_effect=render_without_template_queries):
            with self.assertNumQueries(4):
                response = project_actions(request, project_id=self.project.pk)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tasks/project_actions.html:1")

    def test_route_uses_existing_project_permission_binding(self):
        from core.models import RoutePermissionBinding
        from tasks.acl_bootstrap import bootstrap_tasks_acl_endpoints

        bootstrap_tasks_acl_endpoints(force=True)

        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="tasks:project_actions",
                permission_id="tasks.kickoff.projects",
                is_active=True,
            ).exists()
        )
