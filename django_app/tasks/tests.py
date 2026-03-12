from __future__ import annotations

from datetime import datetime, timedelta
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Ruolo, UtenteLegacy
from core.models import Notifica, Profile

from .models import Project, ProjectComment, SubTask, Task, TaskAttachment, TaskComment, TaskEvent, TaskEventType, TaskPriority, TaskStatus
from .views import _task_date_absence_conflicts

User = get_user_model()

TASK_ACTIONS = ("tasks_view", "tasks_create", "tasks_edit", "tasks_comment", "tasks_admin")


def _ensure_legacy_acl_tables() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ruoli (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS utenti (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(200) NOT NULL,
                    email VARCHAR(200) NULL,
                    password VARCHAR(500) NOT NULL,
                    ruolo VARCHAR(100) NULL,
                    attivo INTEGER NOT NULL DEFAULT 1,
                    deve_cambiare_password INTEGER NOT NULL DEFAULT 0,
                    ruolo_id INTEGER NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permessi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    modulo VARCHAR(100) NOT NULL,
                    azione VARCHAR(100) NOT NULL,
                    ruolo_id INTEGER NOT NULL,
                    consentito INTEGER NULL,
                    can_view INTEGER NULL,
                    can_edit INTEGER NULL,
                    can_delete INTEGER NULL,
                    can_approve INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('ruoli', 'U') IS NULL
                CREATE TABLE ruoli (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('utenti', 'U') IS NULL
                CREATE TABLE utenti (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(200) NOT NULL,
                    email NVARCHAR(200) NULL,
                    password NVARCHAR(500) NOT NULL,
                    ruolo NVARCHAR(100) NULL,
                    attivo BIT NOT NULL DEFAULT 1,
                    deve_cambiare_password BIT NOT NULL DEFAULT 0,
                    ruolo_id INT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('permessi', 'U') IS NULL
                CREATE TABLE permessi (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    modulo NVARCHAR(100) NOT NULL,
                    azione NVARCHAR(100) NOT NULL,
                    ruolo_id INT NOT NULL,
                    consentito INT NULL,
                    can_view INT NULL,
                    can_edit INT NULL,
                    can_delete INT NULL,
                    can_approve INT NULL
                )
                """
            )


def _clear_legacy_acl_tables() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM permessi")
        cursor.execute("DELETE FROM utenti")
        cursor.execute("DELETE FROM ruoli")


def _ensure_assenze_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assenze (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    copia_nome VARCHAR(200) NULL,
                    email_esterna VARCHAR(200) NULL,
                    data_inizio DATETIME NULL,
                    data_fine DATETIME NULL,
                    tipo_assenza VARCHAR(100) NULL,
                    moderation_status INTEGER NULL,
                    consenso VARCHAR(100) NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('assenze', 'U') IS NULL
                CREATE TABLE assenze (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    copia_nome NVARCHAR(200) NULL,
                    email_esterna NVARCHAR(200) NULL,
                    data_inizio DATETIME NULL,
                    data_fine DATETIME NULL,
                    tipo_assenza NVARCHAR(100) NULL,
                    moderation_status INT NULL,
                    consenso NVARCHAR(100) NULL
                )
                """
            )


def _clear_assenze_table() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM assenze")


def _ensure_role(role_id: int, name: str) -> None:
    Ruolo.objects.update_or_create(
        id=role_id,
        defaults={"nome": name},
    )


def _grant_role_actions(role_id: int, actions: list[str]) -> None:
    for action in actions:
        Permesso.objects.update_or_create(
            ruolo_id=role_id,
            modulo="tasks",
            azione=action,
            defaults={
                "can_view": 1,
                "consentito": 1,
                "can_edit": 1,
                "can_delete": 1,
                "can_approve": 1,
            },
        )


def _create_user_with_legacy(*, username: str, legacy_user_id: int, role_id: int, role_name: str):
    user = User.objects.create_user(username=username, password="pass12345")
    Profile.objects.create(
        user=user,
        legacy_user_id=legacy_user_id,
        legacy_ruolo_id=role_id,
        legacy_ruolo=role_name,
    )
    UtenteLegacy.objects.create(
        id=legacy_user_id,
        nome=username,
        email=f"{username}@example.local",
        password="x",
        ruolo=role_name,
        attivo=True,
        deve_cambiare_password=False,
        ruolo_id=role_id,
    )
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TasksBaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()

    def _refresh_acl_cache(self):
        cache.clear()
        bump_legacy_cache_version()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskPermissionsScopeTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _ensure_role(3, "manager")
        _ensure_role(4, "ospite")

        _grant_role_actions(2, ["tasks_view"])
        _grant_role_actions(3, ["tasks_view", "tasks_admin"])
        self._refresh_acl_cache()

        self.owner = _create_user_with_legacy(username="owner", legacy_user_id=1001, role_id=2, role_name="utente")
        self.assignee = _create_user_with_legacy(
            username="assignee", legacy_user_id=1002, role_id=2, role_name="utente"
        )
        self.subscriber = _create_user_with_legacy(
            username="subscriber", legacy_user_id=1003, role_id=2, role_name="utente"
        )
        self.outsider = _create_user_with_legacy(
            username="outsider", legacy_user_id=1004, role_id=2, role_name="utente"
        )
        self.scope_admin = _create_user_with_legacy(
            username="scopeadmin", legacy_user_id=1005, role_id=3, role_name="manager"
        )
        self.blocked = _create_user_with_legacy(
            username="blocked", legacy_user_id=1006, role_id=4, role_name="ospite"
        )

        self.task_created = Task.objects.create(
            title="Created by owner",
            created_by=self.owner,
            assigned_to=self.outsider,
        )
        self.task_assigned = Task.objects.create(
            title="Assigned to owner",
            created_by=self.assignee,
            assigned_to=self.owner,
        )
        self.task_subscribed = Task.objects.create(
            title="Subscribed by owner",
            created_by=self.assignee,
            assigned_to=self.outsider,
        )
        self.task_subscribed.subscribers.add(self.owner)
        self.task_other = Task.objects.create(
            title="Other task",
            created_by=self.assignee,
            assigned_to=self.outsider,
        )

    def test_non_admin_scope_sees_only_related_tasks(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("tasks:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.task_created.title)
        self.assertContains(response, self.task_assigned.title)
        self.assertContains(response, self.task_subscribed.title)
        self.assertNotContains(response, self.task_other.title)

    def test_tasks_admin_scope_can_see_all(self):
        self.client.force_login(self.scope_admin)
        response = self.client.get(reverse("tasks:list"), {"mine": "0"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.task_created.title)
        self.assertContains(response, self.task_assigned.title)
        self.assertContains(response, self.task_subscribed.title)
        self.assertContains(response, self.task_other.title)

    def test_user_without_tasks_view_gets_forbidden(self):
        self.client.force_login(self.blocked)
        response = self.client.get(reverse("tasks:list"))
        self.assertEqual(response.status_code, 403)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskAntiIDORTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_edit", "tasks_comment"])
        self._refresh_acl_cache()

        self.user_a = _create_user_with_legacy(username="idora", legacy_user_id=2001, role_id=2, role_name="utente")
        self.user_b = _create_user_with_legacy(username="idorb", legacy_user_id=2002, role_id=2, role_name="utente")
        self.task_a = Task.objects.create(title="Task A", created_by=self.user_a)
        self.task_b = Task.objects.create(title="Task B", created_by=self.user_b)

    def test_detail_out_of_scope_returns_404(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("tasks:detail", args=[self.task_b.id]))
        self.assertEqual(response.status_code, 404)

    def test_edit_out_of_scope_returns_404(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse("tasks:edit", args=[self.task_b.id]))
        self.assertEqual(response.status_code, 404)

    def test_status_change_out_of_scope_returns_404(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("tasks:change_status", args=[self.task_b.id]),
            {"status": TaskStatus.DONE},
        )
        self.assertEqual(response.status_code, 404)

    def test_attachment_upload_out_of_scope_returns_404(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse("tasks:add_attachment", args=[self.task_b.id]),
            {"attach_to": "task"},
        )
        self.assertEqual(response.status_code, 404)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskAuditTrailTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_edit", "tasks_comment"])
        self._refresh_acl_cache()

        self.user = _create_user_with_legacy(username="audituser", legacy_user_id=3001, role_id=2, role_name="utente")
        self.task = Task.objects.create(title="Audit task", created_by=self.user, status=TaskStatus.TODO)

    def test_status_change_creates_audit_event(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("tasks:change_status", args=[self.task.id]),
            {"status": TaskStatus.IN_PROGRESS},
        )
        self.assertEqual(response.status_code, 302)
        event = TaskEvent.objects.filter(task=self.task, type=TaskEventType.STATUS_CHANGE).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.payload.get("from"), TaskStatus.TODO)
        self.assertEqual(event.payload.get("to"), TaskStatus.IN_PROGRESS)

    def test_add_comment_creates_audit_event(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("tasks:add_comment", args=[self.task.id]),
            {"body": "Commento di test"},
        )
        self.assertEqual(response.status_code, 302)
        comment = TaskComment.objects.filter(task=self.task).first()
        self.assertIsNotNone(comment)
        event = TaskEvent.objects.filter(task=self.task, type=TaskEventType.COMMENT_ADDED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.payload.get("comment_id"), comment.id)

    def test_subtask_events_are_created(self):
        self.client.force_login(self.user)
        response_add = self.client.post(
            reverse("tasks:add_subtask", args=[self.task.id]),
            {"title": "Sub 1", "order_index": 1},
        )
        self.assertEqual(response_add.status_code, 302)
        subtask = SubTask.objects.get(task=self.task, title="Sub 1")

        response_status = self.client.post(
            reverse("tasks:edit_subtask_status", args=[self.task.id, subtask.id]),
            {"status": TaskStatus.DONE},
        )
        self.assertEqual(response_status.status_code, 302)

        add_event = TaskEvent.objects.filter(task=self.task, type=TaskEventType.SUBTASK_ADDED).first()
        status_event = TaskEvent.objects.filter(task=self.task, type=TaskEventType.SUBTASK_STATUS_CHANGE).first()
        self.assertIsNotNone(add_event)
        self.assertIsNotNone(status_event)
        self.assertEqual(add_event.payload.get("subtask_id"), subtask.id)
        self.assertEqual(status_event.payload.get("subtask_id"), subtask.id)
        self.assertEqual(status_event.payload.get("from"), TaskStatus.TODO)
        self.assertEqual(status_event.payload.get("to"), TaskStatus.DONE)

    def test_subtask_rollup_updates_parent_task_status(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("tasks:add_subtask", args=[self.task.id]),
            {"title": "Sub rollup", "order_index": 1},
        )
        subtask = SubTask.objects.get(task=self.task, title="Sub rollup")
        response = self.client.post(
            reverse("tasks:edit_subtask_status", args=[self.task.id, subtask.id]),
            {"status": TaskStatus.DONE},
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.DONE)
        rollup_events = TaskEvent.objects.filter(task=self.task, type=TaskEventType.STATUS_CHANGE)
        self.assertTrue(any((event.payload or {}).get("source") == "subtask_rollup" for event in rollup_events))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskListFiltersTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _ensure_role(3, "manager")
        _grant_role_actions(2, ["tasks_view"])
        _grant_role_actions(3, ["tasks_view", "tasks_admin"])
        self._refresh_acl_cache()

        self.user = _create_user_with_legacy(username="filteruser", legacy_user_id=4001, role_id=2, role_name="utente")
        self.manager = _create_user_with_legacy(username="manager", legacy_user_id=4002, role_id=3, role_name="manager")
        self.other = _create_user_with_legacy(username="other", legacy_user_id=4003, role_id=2, role_name="utente")
        self.project_alpha = Project.objects.create(name="Project Alpha", created_by=self.manager)
        self.project_beta = Project.objects.create(name="Project Beta", created_by=self.manager)

        today = timezone.localdate()
        self.t_overdue = Task.objects.create(
            title="Overdue TODO",
            created_by=self.other,
            assigned_to=self.user,
            project=self.project_alpha,
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            due_date=today - timedelta(days=2),
            tags="produzione, urgente",
        )
        self.t_done_past = Task.objects.create(
            title="Done old",
            created_by=self.other,
            assigned_to=self.user,
            status=TaskStatus.DONE,
            priority=TaskPriority.HIGH,
            due_date=today - timedelta(days=1),
        )
        self.t_future_medium = Task.objects.create(
            title="Future medium",
            created_by=self.other,
            assigned_to=self.other,
            project=self.project_beta,
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.MEDIUM,
            due_date=today + timedelta(days=4),
            tags="it, inventory",
        )
        self.t_future_low = Task.objects.create(
            title="Future low",
            created_by=self.other,
            assigned_to=self.user,
            status=TaskStatus.TODO,
            priority=TaskPriority.LOW,
            due_date=today + timedelta(days=10),
            tags="planning",
        )
        self.t_unassigned = Task.objects.create(
            title="Unassigned task",
            created_by=self.other,
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            due_date=today + timedelta(days=2),
        )
        self.t_without_due = Task.objects.create(
            title="Task without due date",
            created_by=self.other,
            assigned_to=self.user,
            project=self.project_alpha,
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            due_date=None,
        )

    def test_filter_overdue(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("tasks:list"), {"mine": "0", "overdue": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_overdue.title)
        self.assertNotContains(response, self.t_done_past.title)
        self.assertNotContains(response, self.t_future_medium.title)

    def test_filter_status_priority_and_assigned_to(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tasks:list"),
            {
                "mine": "0",
                "status": TaskStatus.TODO,
                "priority": TaskPriority.LOW,
                "assigned_to": str(self.user.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_future_low.title)
        self.assertNotContains(response, self.t_overdue.title)
        self.assertNotContains(response, self.t_future_medium.title)

    def test_filter_due_date_range(self):
        self.client.force_login(self.manager)
        today = timezone.localdate()
        response = self.client.get(
            reverse("tasks:list"),
            {
                "mine": "0",
                "due_from": (today + timedelta(days=1)).isoformat(),
                "due_to": (today + timedelta(days=6)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_future_medium.title)
        self.assertNotContains(response, self.t_future_low.title)

    def test_filter_by_tag(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tasks:list"),
            {
                "mine": "0",
                "tag": "urgente",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_overdue.title)
        self.assertNotContains(response, self.t_future_medium.title)

    def test_filter_by_project(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tasks:list"),
            {
                "mine": "0",
                "project": str(self.project_alpha.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_overdue.title)
        self.assertNotContains(response, self.t_future_medium.title)

    def test_filter_unassigned(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tasks:list"),
            {
                "mine": "0",
                "unassigned": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_unassigned.title)
        self.assertNotContains(response, self.t_overdue.title)

    def test_filter_without_due_date(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tasks:list"),
            {
                "mine": "0",
                "without_due_date": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_without_due.title)
        self.assertNotContains(response, self.t_future_low.title)

    def test_filter_without_project(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tasks:list"),
            {
                "mine": "0",
                "without_project": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.t_future_low.title)
        self.assertContains(response, self.t_unassigned.title)
        self.assertNotContains(response, self.t_overdue.title)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskProjectsAndAttachmentsTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit"])
        self._refresh_acl_cache()

        self.user = _create_user_with_legacy(username="projectuser", legacy_user_id=5001, role_id=2, role_name="utente")

        self._media_root = tempfile.mkdtemp(prefix="tasks_test_media_")
        self._media_override = override_settings(MEDIA_ROOT=self._media_root)
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)
        self.addCleanup(shutil.rmtree, self._media_root, True)

    def _base_task_payload(self, title: str) -> dict:
        return {
            "title": title,
            "description": "Descrizione test",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.MEDIUM,
            "task_scope": "single",
        }

    def test_create_single_task_without_project(self):
        self.client.force_login(self.user)
        payload = self._base_task_payload("Task singola")
        response = self.client.post(reverse("tasks:create"), payload)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Task singola")
        self.assertIsNone(task.project_id)

    def test_create_task_with_new_project(self):
        self.client.force_login(self.user)
        payload = self._base_task_payload("Task con nuovo progetto")
        payload.update(
            {
                "task_scope": "project",
                "project_new_name": "Progetto Nuovo A",
                "project_new_description": "Descrizione progetto A",
            }
        )
        response = self.client.post(reverse("tasks:create"), payload)
        self.assertEqual(response.status_code, 302)

        task = Task.objects.get(title="Task con nuovo progetto")
        self.assertIsNotNone(task.project_id)
        self.assertEqual(task.project.name, "Progetto Nuovo A")
        self.assertEqual(task.project.created_by_id, self.user.id)

    def test_create_task_with_new_project_metadata(self):
        self.client.force_login(self.user)
        project_manager = User.objects.create_user(username="pm_user", password="pass12345")
        capo_commessa = User.objects.create_user(username="capo_user", password="pass12345")
        programmatore = User.objects.create_user(username="prog_user", password="pass12345")
        similar_project = Project.objects.create(name="Commessa simile", created_by=self.user)

        payload = self._base_task_payload("Task con metadati progetto")
        payload.update(
            {
                "task_scope": "project",
                "project_new_name": "Commessa completa",
                "project_new_description": "Descrizione completa",
                "project_new_client": "Cliente Alfa",
                "project_new_manager": str(project_manager.id),
                "project_new_capo_commessa": str(capo_commessa.id),
                "project_new_programmer": str(programmatore.id),
                "project_new_control_method": "Checklist e test collaudo",
                "project_new_part_number": "PN-001",
                "project_similar_choice": str(similar_project.id),
            }
        )
        response = self.client.post(reverse("tasks:create"), payload)
        self.assertEqual(response.status_code, 302)

        task = Task.objects.get(title="Task con metadati progetto")
        self.assertIsNotNone(task.project_id)
        project = task.project
        self.assertEqual(project.client_name, "Cliente Alfa")
        self.assertEqual(project.project_manager_id, project_manager.id)
        self.assertEqual(project.capo_commessa_id, capo_commessa.id)
        self.assertEqual(project.programmer_id, programmatore.id)
        self.assertEqual(project.control_method, "Checklist e test collaudo")
        self.assertEqual(project.part_number, "PN-001")
        self.assertEqual(project.similar_project_id, similar_project.id)

    def test_create_task_with_existing_project(self):
        self.client.force_login(self.user)
        project = Project.objects.create(name="Progetto Esistente", created_by=self.user)
        payload = self._base_task_payload("Task su progetto esistente")
        payload.update(
            {
                "task_scope": "project",
                "project_choice": str(project.id),
            }
        )
        response = self.client.post(reverse("tasks:create"), payload)
        self.assertEqual(response.status_code, 302)

        task = Task.objects.get(title="Task su progetto esistente")
        self.assertEqual(task.project_id, project.id)
        self.assertEqual(Project.objects.filter(name="Progetto Esistente").count(), 1)

    def test_assignment_conflict_alert_on_create_with_keep_priority(self):
        self.client.force_login(self.user)
        assignee = User.objects.create_user(username="planner_keep", password="pass12345")
        today = timezone.localdate()
        Task.objects.create(
            title="Impegno esistente",
            created_by=self.user,
            assigned_to=assignee,
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.MEDIUM,
            next_step_due=today + timedelta(days=2),
            due_date=today + timedelta(days=5),
        )

        payload = self._base_task_payload("Task nuova con conflitto")
        payload.update(
            {
                "assigned_to": str(assignee.id),
                "priority": TaskPriority.LOW,
                "next_step_due": (today + timedelta(days=3)).isoformat(),
                "due_date": (today + timedelta(days=6)).isoformat(),
                "assignment_conflict_action": "keep_priority",
            }
        )
        response = self.client.post(reverse("tasks:create"), payload, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Impegni sovrapposti")
        task = Task.objects.get(title="Task nuova con conflitto")
        self.assertEqual(task.priority, TaskPriority.LOW)

    def test_assignment_conflict_can_raise_priority_to_high(self):
        self.client.force_login(self.user)
        assignee = User.objects.create_user(username="planner_raise", password="pass12345")
        today = timezone.localdate()
        Task.objects.create(
            title="Impegno esistente raise",
            created_by=self.user,
            assigned_to=assignee,
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            next_step_due=today + timedelta(days=1),
            due_date=today + timedelta(days=4),
        )

        payload = self._base_task_payload("Task nuova con priorita auto")
        payload.update(
            {
                "assigned_to": str(assignee.id),
                "priority": TaskPriority.LOW,
                "next_step_due": (today + timedelta(days=2)).isoformat(),
                "due_date": (today + timedelta(days=5)).isoformat(),
                "assignment_conflict_action": "raise_to_high",
            }
        )
        response = self.client.post(reverse("tasks:create"), payload, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Priorita aggiornata automaticamente a High")
        task = Task.objects.get(title="Task nuova con priorita auto")
        self.assertEqual(task.priority, TaskPriority.HIGH)

    def test_upload_attachment_to_task_creates_event(self):
        self.client.force_login(self.user)
        task = Task.objects.create(title="Task allegato", created_by=self.user)
        file_obj = SimpleUploadedFile("task-note.txt", b"contenuto allegato task", content_type="text/plain")
        response = self.client.post(
            reverse("tasks:add_attachment", args=[task.id]),
            {"attach_to": "task", "file": file_obj},
        )
        self.assertEqual(response.status_code, 302)

        attachment = TaskAttachment.objects.get(task=task)
        self.assertEqual(attachment.original_name, "task-note.txt")
        event = TaskEvent.objects.filter(task=task, type=TaskEventType.ATTACHMENT_ADDED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.payload.get("target"), "task")
        self.assertEqual(event.payload.get("attachment_id"), attachment.id)

    def test_upload_attachment_to_project_creates_event(self):
        self.client.force_login(self.user)
        project = Project.objects.create(name="Project Attach", created_by=self.user)
        task = Task.objects.create(title="Task con progetto allegato", created_by=self.user, project=project)
        file_obj = SimpleUploadedFile("project-note.txt", b"contenuto allegato progetto", content_type="text/plain")
        response = self.client.post(
            reverse("tasks:add_attachment", args=[task.id]),
            {"attach_to": "project", "file": file_obj},
        )
        self.assertEqual(response.status_code, 302)

        attachment = TaskAttachment.objects.get(project=project, task__isnull=True)
        self.assertEqual(attachment.original_name, "project-note.txt")
        event = TaskEvent.objects.filter(task=task, type=TaskEventType.ATTACHMENT_ADDED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.payload.get("target"), "project")
        self.assertEqual(event.payload.get("project_id"), project.id)


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

        self.project = Project.objects.create(name="Gantt Project", created_by=self.owner)
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
            tipo="generico",
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
            tipo="generico",
            messaggio__icontains="Gantt Project",
        ).first()
        self.assertIsNotNone(notification)
        self.assertIn("Gantt Project", notification.messaggio)

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
        self.assertContains(response, "Range non valido (fine <= inizio)")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskAbsenceConflictTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()

        _ensure_assenze_table()
        _clear_assenze_table()

        self.owner = _create_user_with_legacy(username="absence_owner", legacy_user_id=6501, role_id=2, role_name="utente")
        self.assignee = _create_user_with_legacy(
            username="absence_assignee",
            legacy_user_id=6502,
            role_id=2,
            role_name="utente",
        )

    def _insert_absence(
        self,
        *,
        person_name: str,
        person_email: str,
        date_value,
        tipo: str = "Ferie",
        moderation_status: int = 0,
    ) -> None:
        start_dt = datetime.combine(date_value, datetime.min.time())
        end_dt = datetime.combine(date_value, datetime.max.time())
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO assenze (
                    copia_nome,
                    email_esterna,
                    data_inizio,
                    data_fine,
                    tipo_assenza,
                    moderation_status,
                    consenso
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [person_name, person_email, start_dt, end_dt, tipo, moderation_status, "Approvato"],
            )

    def test_absence_conflicts_detected_on_task_dates(self):
        target_day = timezone.localdate() + timedelta(days=3)
        self._insert_absence(
            person_name=self.assignee.username,
            person_email=self.assignee.email,
            date_value=target_day,
        )
        task = Task.objects.create(
            title="Task con assenza",
            created_by=self.owner,
            assigned_to=self.assignee,
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            due_date=target_day,
            next_step_due=target_day,
        )
        conflicts = _task_date_absence_conflicts(task)
        self.assertIn("due_date", conflicts)
        self.assertIn("next_step_due", conflicts)

    def test_project_gantt_marks_absence_cells(self):
        self.client.force_login(self.owner)
        target_day = timezone.localdate() + timedelta(days=2)
        self._insert_absence(
            person_name=self.assignee.username,
            person_email=self.assignee.email,
            date_value=target_day,
        )
        project = Project.objects.create(name="Project assenze", created_by=self.owner)
        Task.objects.create(
            title="Task conflitto gantt",
            created_by=self.owner,
            assigned_to=self.assignee,
            project=project,
            status=TaskStatus.IN_PROGRESS,
            next_step_due=target_day - timedelta(days=1),
            due_date=target_day + timedelta(days=1),
        )
        response = self.client.get(reverse("tasks:project_gantt", args=[project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is-absence")
        self.assertContains(response, "absence-x")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskEditAndDueDatePermissionsTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _ensure_role(3, "manager")
        _grant_role_actions(2, ["tasks_view"])
        _grant_role_actions(3, ["tasks_view", "tasks_admin"])
        self._refresh_acl_cache()

        self.project_lead = _create_user_with_legacy(
            username="lead_user", legacy_user_id=7001, role_id=2, role_name="utente"
        )
        self.assignee = _create_user_with_legacy(
            username="op_user", legacy_user_id=7002, role_id=2, role_name="utente"
        )
        self.viewer = _create_user_with_legacy(
            username="viewer_user", legacy_user_id=7003, role_id=2, role_name="utente"
        )
        self.scope_admin = _create_user_with_legacy(
            username="admin_user", legacy_user_id=7004, role_id=3, role_name="manager"
        )

        self.project = Project.objects.create(name="Project Lead Edit", created_by=self.project_lead)
        self.task = Task.objects.create(
            title="Task permessi edit",
            created_by=self.project_lead,
            assigned_to=self.assignee,
            project=self.project,
            due_date=timezone.localdate() + timedelta(days=5),
        )
        self.task.subscribers.add(self.viewer)

    def test_project_lead_can_open_and_submit_task_edit(self):
        self.client.force_login(self.project_lead)
        response_get = self.client.get(reverse("tasks:edit", args=[self.task.id]))
        self.assertEqual(response_get.status_code, 200)

        payload = {
            "title": "Task aggiornata da lead",
            "description": "Desc aggiornata",
            "tags": "lead-edit",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.HIGH,
            "due_date": (timezone.localdate() + timedelta(days=9)).isoformat(),
            "next_step_text": "Nuovo step",
            "next_step_due": (timezone.localdate() + timedelta(days=7)).isoformat(),
            "assigned_to": str(self.assignee.id),
            "subscribers": [str(self.viewer.id)],
            "task_scope": "project",
            "project_choice": str(self.project.id),
            "project_new_name": "",
            "project_new_description": "",
        }
        response_post = self.client.post(reverse("tasks:edit", args=[self.task.id]), payload)
        self.assertEqual(response_post.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Task aggiornata da lead")
        self.assertEqual(self.task.priority, TaskPriority.HIGH)

    def test_assignee_without_manage_permission_cannot_open_task_edit(self):
        self.client.force_login(self.assignee)
        response = self.client.get(reverse("tasks:edit", args=[self.task.id]))
        self.assertEqual(response.status_code, 403)

    def test_assignee_can_update_due_date(self):
        self.client.force_login(self.assignee)
        target_due = timezone.localdate() + timedelta(days=14)
        response = self.client.post(
            reverse("tasks:update_due_date", args=[self.task.id]),
            {"due_date": target_due.isoformat()},
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, target_due)
        edit_events = TaskEvent.objects.filter(task=self.task, type=TaskEventType.EDIT)
        self.assertTrue(any("due_date" in (event.payload or {}).get("changes", {}) for event in edit_events))

    def test_viewer_in_scope_cannot_update_due_date(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse("tasks:update_due_date", args=[self.task.id]),
            {"due_date": (timezone.localdate() + timedelta(days=20)).isoformat()},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_due_date(self):
        self.client.force_login(self.scope_admin)
        target_due = timezone.localdate() + timedelta(days=30)
        response = self.client.post(
            reverse("tasks:update_due_date", args=[self.task.id]),
            {"due_date": target_due.isoformat()},
        )
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, target_due)
