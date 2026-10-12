"""Test del Gantt di commessa e delle notifiche collegate."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Notifica

from .models import (
    ProjectComment,
    TaskAccessLevel,
    Task,
    TaskComment,
    TaskEvent,
    TaskEventType,
    TaskRoleAccessRule,
    TaskRoleType,
    TaskStatus,
)
from .tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskProjectGanttAndNotificationsTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_edit", "tasks_comment"])
        self._refresh_acl_cache()

        self.owner = _create_user_with_legacy(username="g_owner", legacy_user_id=6001, role_id=2, role_name="utente")
        self.assignee = _create_user_with_legacy(
            username="g_assignee", legacy_user_id=6002, role_id=2, role_name="utente"
        )
        self.viewer = _create_user_with_legacy(username="g_viewer", legacy_user_id=6003, role_id=2, role_name="utente")
        self.outsider = _create_user_with_legacy(
            username="g_outsider", legacy_user_id=6004, role_id=2, role_name="utente"
        )

        self.project = make_project(
            name="Gantt Project",
            created_by=self.owner,
            programmer=self.assignee,
        )
        TaskRoleAccessRule.objects.create(
            role_type=TaskRoleType.PROGRAMMER,
            access_level=TaskAccessLevel.EDIT_ASSIGNED,
        )
        self.task = Task.objects.create(
            title="Task Gantt",
            created_by=self.owner,
            assigned_to=self.assignee,
            project=self.project,
            status=TaskStatus.TODO,
            next_step_due=timezone.localdate() + timedelta(days=2),
            due_date=timezone.localdate() + timedelta(days=7),
        )
        self.task.subscribers.add(self.viewer)

    def test_project_gantt_view_in_scope(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.name)
        self.assertContains(response, self.task.title)

    def test_project_gantt_out_of_scope_returns_404(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertEqual(response.status_code, 404)

    def test_project_gantt_update_allowed_for_assignee(self):
        self.client.force_login(self.assignee)
        response = self.client.post(
            reverse("tasks:project_gantt_update_task", args=[self.project.id, self.task.id]),
            {
                "task_%s-next_step_due" % self.task.id: "2026-03-10",
                "task_%s-due_date" % self.task.id: "2026-03-15",
                "task_%s-status" % self.task.id: TaskStatus.IN_PROGRESS,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(str(self.task.next_step_due), "2026-03-10")
        self.assertEqual(str(self.task.due_date), "2026-03-15")

    def test_project_gantt_update_rejects_equal_start_end(self):
        self.client.force_login(self.assignee)
        old_next = self.task.next_step_due
        old_due = self.task.due_date
        response = self.client.post(
            reverse("tasks:project_gantt_update_task", args=[self.project.id, self.task.id]),
            {
                "task_%s-next_step_due" % self.task.id: "2026-03-10",
                "task_%s-due_date" % self.task.id: "2026-03-10",
                "task_%s-status" % self.task.id: TaskStatus.IN_PROGRESS,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.next_step_due, old_next)
        self.assertEqual(self.task.due_date, old_due)
        self.assertEqual(self.task.status, TaskStatus.TODO)

    def test_project_gantt_update_denied_for_non_assignee(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse("tasks:project_gantt_update_task", args=[self.project.id, self.task.id]),
            {
                "task_%s-next_step_due" % self.task.id: "2026-03-10",
                "task_%s-due_date" % self.task.id: "2026-03-12",
                "task_%s-status" % self.task.id: TaskStatus.IN_PROGRESS,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_project_gantt_shift_days_allowed_for_assignee_and_audited(self):
        self.client.force_login(self.assignee)
        old_next = self.task.next_step_due
        old_due = self.task.due_date
        response = self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.id, self.task.id]),
            {"shift_days": "3"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.next_step_due, old_next + timedelta(days=3))
        self.assertEqual(self.task.due_date, old_due + timedelta(days=3))
        edit_events = TaskEvent.objects.filter(task=self.task, type=TaskEventType.EDIT)
        self.assertTrue(any("due_date" in (event.payload or {}).get("changes", {}) for event in edit_events))

    def test_project_gantt_resize_end_extends_due_date_only(self):
        self.client.force_login(self.assignee)
        old_next = self.task.next_step_due
        old_due = self.task.due_date
        response = self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.id, self.task.id]),
            {"mode": "resize_end", "shift_days": "2", "cascade": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "resize_end")
        self.task.refresh_from_db()
        self.assertEqual(self.task.next_step_due, old_next)
        self.assertEqual(self.task.due_date, old_due + timedelta(days=2))

    def test_project_gantt_resize_start_moves_start_date_only(self):
        self.client.force_login(self.assignee)
        old_next = self.task.next_step_due
        old_due = self.task.due_date
        response = self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.id, self.task.id]),
            {"mode": "resize_start", "shift_days": "1", "cascade": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "resize_start")
        self.task.refresh_from_db()
        self.assertEqual(self.task.next_step_due, old_next + timedelta(days=1))
        self.assertEqual(self.task.due_date, old_due)

    def test_project_gantt_shift_days_denied_for_non_assignee(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.id, self.task.id]),
            {"shift_days": "2"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)

    def test_project_gantt_shift_days_out_of_scope_returns_404(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.id, self.task.id]),
            {"shift_days": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)

    def test_task_comment_target_user_creates_notification(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tasks:add_comment", args=[self.task.id]),
            {
                "body": "Controlla questa task",
                "target_user": str(self.assignee.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        comment = TaskComment.objects.filter(task=self.task).first()
        self.assertIsNotNone(comment)
        self.assertEqual(comment.target_user_id, self.assignee.id)
        notification = Notifica.objects.filter(
            legacy_user_id=6002,
            tipo="task",
            messaggio__icontains="Task Gantt",
        ).first()
        self.assertIsNotNone(notification)
        self.assertIn("Task Gantt", notification.messaggio)

    def test_project_comment_target_user_creates_notification(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tasks:add_project_comment", args=[self.project.id]),
            {
                "body": "Aggiorna la timeline progetto",
                "target_user": str(self.assignee.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        comment = ProjectComment.objects.filter(project=self.project).first()
        self.assertIsNotNone(comment)
        self.assertEqual(comment.target_user_id, self.assignee.id)
        notification = Notifica.objects.filter(
            legacy_user_id=6002,
            tipo="task",
            messaggio__icontains=self.project.name,
        ).first()
        self.assertIsNotNone(notification)
        self.assertIn(self.project.name, notification.messaggio)

    def test_project_gantt_marks_invalid_range_cells(self):
        self.client.force_login(self.owner)
        invalid_day = timezone.localdate() + timedelta(days=12)
        Task.objects.create(
            title="Task range invalido",
            created_by=self.owner,
            assigned_to=self.assignee,
            project=self.project,
            status=TaskStatus.IN_PROGRESS,
            next_step_due=invalid_day,
            due_date=invalid_day,
        )
        response = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is-invalid-range")
        self.assertContains(response, "Range non valido")
