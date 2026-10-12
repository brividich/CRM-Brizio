"""Test di permessi, scope e anti-IDOR del modulo KICK-OFF."""
from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Profile

from .models import (
    KickoffMeeting,
    TaskAccessLevel,
    Task,
    TaskCategory,
    TaskEvent,
    TaskEventType,
    TaskPriority,
    TaskRoleAssignment,
    TaskRoleAccessRule,
    TaskRoleDefinition,
    TaskRoleType,
    TaskStatus,
    TaskUserAccessRule,
)
from .tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    _legacy_upsert_by_id,
    make_project,
)

User = get_user_model()


class TaskViewsImportHygieneTests(TestCase):
    def test_views_do_not_shadow_module_imports_with_local_imports(self):
        base = Path(__file__).parent
        paths = [base / "access.py", *sorted((base / "views").glob("*.py")), *sorted((base / "services").glob("*.py"))]
        offenders: list[str] = []
        for path in paths:
            offenders += [f"{path.name}:{o}" for o in self._shadowing_imports(path)]
        self.assertEqual(offenders, [])

    def _shadowing_imports(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                module_imports.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module_imports.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

        offenders: list[str] = []
        for fn in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(fn):
                imported_names: list[str] = []
                if isinstance(node, ast.Import):
                    imported_names = [alias.asname or alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported_names = [alias.asname or alias.name for alias in node.names if alias.name != "*"]
                for name in imported_names:
                    if name in module_imports:
                        offenders.append(f"{fn.name}:{node.lineno}:{name}")
        return offenders


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

    def test_json_endpoint_denied_answers_json_403(self):
        self.client.force_login(self.blocked)
        for url in (
            reverse("tasks:category_fields_json", args=[999]),
            reverse("tasks:asset_availability_json", args=[999]),
            reverse("tasks:project_info_json", args=[999]),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)
            self.assertEqual(response.json()["reason"], "forbidden")

    def test_json_endpoint_anonymous_answers_json_401(self):
        # Come il fetch del form attivita': senza sessione risponde JSON, non redirect.
        response = self.client.get(
            reverse("tasks:category_fields_json", args=[999]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["reason"], "unauthenticated")

    def test_module_gate_uses_shared_acl_evaluator(self):
        # Il gate passa dal valutatore comune (binding ACL v2 prima del legacy):
        # un divieto canonico prevale sul permesso del ruolo legacy.
        self.client.force_login(self.owner)
        with patch(
            "tasks.access.evaluate_modulo_action_access",
            return_value={"allowed": False},
        ) as evaluator:
            response = self.client.get(reverse("tasks:list"))
        self.assertEqual(response.status_code, 403)
        evaluator.assert_called()


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

        self.project = make_project(name="Project Lead Edit", created_by=self.project_lead)
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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskRoleAssignmentTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(1, "admin")
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.admin = _create_user_with_legacy(
            username="roleadmin", legacy_user_id=9101, role_id=1, role_name="admin",
        )
        self.alice = _create_user_with_legacy(
            username="alice", legacy_user_id=9201, role_id=2, role_name="utente",
        )
        self.alice.first_name = "Alice"; self.alice.save()
        self.bob = _create_user_with_legacy(
            username="bob", legacy_user_id=9202, role_id=2, role_name="utente",
        )
        self.bob.first_name = "Bob"; self.bob.save()

    def test_no_assignment_means_all_users_visible_in_form(self):
        from .forms import _users_for_role
        qs = _users_for_role(TaskRoleType.PROJECT_MANAGER)
        # fallback: nessuna assegnazione -> tutti gli utenti
        self.assertIn(self.alice, list(qs))
        self.assertIn(self.bob, list(qs))

    def test_with_assignment_filter_applies(self):
        from .forms import _users_for_role
        TaskRoleAssignment.objects.create(user=self.alice, role_type=TaskRoleType.PROJECT_MANAGER)
        qs = list(_users_for_role(TaskRoleType.PROJECT_MANAGER))
        self.assertIn(self.alice, qs)
        self.assertNotIn(self.bob, qs)
        # altri ruoli: ancora fallback
        qs_cc = list(_users_for_role(TaskRoleType.CAPO_COMMESSA))
        self.assertIn(self.alice, qs_cc)
        self.assertIn(self.bob, qs_cc)

    def test_post_ruoli_tab_adds_and_removes_assignments(self):
        # alice parte con PM attivo
        TaskRoleAssignment.objects.create(user=self.alice, role_type=TaskRoleType.PROJECT_MANAGER)
        self.client.force_login(self.admin)
        # Post: alice non piu' PM ma CC, bob diventa PRG
        payload = {
            "tab": "ruoli",
            "visible_user_id": [str(self.alice.id), str(self.bob.id)],
            f"role__CC__{self.alice.id}": "on",
            f"role__PRG__{self.bob.id}": "on",
        }
        response = self.client.post(reverse("tasks:impostazioni"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            TaskRoleAssignment.objects.filter(user=self.alice, role_type=TaskRoleType.PROJECT_MANAGER).exists()
        )
        self.assertTrue(
            TaskRoleAssignment.objects.filter(user=self.alice, role_type=TaskRoleType.CAPO_COMMESSA).exists()
        )
        self.assertTrue(
            TaskRoleAssignment.objects.filter(user=self.bob, role_type=TaskRoleType.PROGRAMMER).exists()
        )

    def test_ruoli_tab_search_matches_legacy_user_name(self):
        _legacy_upsert_by_id(
            "utenti",
            9201,
            {
                "nome": "Danesi Mario",
                "email": "m.danesi@example.local",
                "password": "x",
                "ruolo": "utente",
                "attivo": True,
                "deve_cambiare_password": False,
                "ruolo_id": 2,
            },
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("tasks:impostazioni"), {"tab": "ruoli", "q_user": "Danesi"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ALICE")
        self.assertNotContains(response, "BOB")

    def test_ruoli_tab_search_syncs_missing_active_legacy_user(self):
        _legacy_upsert_by_id(
            "utenti",
            9299,
            {
                "nome": "Danesi Simone",
                "email": "s.danesi@example.local",
                "password": "x",
                "ruolo": "utente",
                "attivo": True,
                "deve_cambiare_password": False,
                "ruolo_id": 2,
            },
        )
        self.assertFalse(Profile.objects.filter(legacy_user_id=9299).exists())

        self.client.force_login(self.admin)
        response = self.client.get(reverse("tasks:impostazioni"), {"tab": "ruoli", "q_user": "Danesi"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Danesi")
        self.assertTrue(Profile.objects.filter(legacy_user_id=9299).exists())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskScopedAccessRulesTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(1, "admin")
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit", "tasks_comment"])
        self._refresh_acl_cache()

        self.admin = _create_user_with_legacy(username="taskaccessadmin", legacy_user_id=9601, role_id=1, role_name="admin")
        self.owner = _create_user_with_legacy(username="ko_owner", legacy_user_id=9602, role_id=2, role_name="utente")
        self.capo = _create_user_with_legacy(username="ko_capo", legacy_user_id=9603, role_id=2, role_name="utente")
        self.programmer = _create_user_with_legacy(username="ko_prog", legacy_user_id=9604, role_id=2, role_name="utente")
        self.pm_user = _create_user_with_legacy(username="ko_pm", legacy_user_id=9605, role_id=2, role_name="utente")
        self.override_user = _create_user_with_legacy(username="ko_override", legacy_user_id=9606, role_id=2, role_name="utente")
        self.outsider = _create_user_with_legacy(username="ko_outsider", legacy_user_id=9607, role_id=2, role_name="utente")

        self.project = make_project(
            name="Kickoff accessi",
            created_by=self.owner,
            project_manager=self.pm_user,
            capo_commessa=self.capo,
            programmer=self.programmer,
        )
        self.task_prog = Task.objects.create(
            title="Task programmatore",
            created_by=self.owner,
            assigned_to=self.programmer,
            project=self.project,
            next_step_due=timezone.localdate() + timedelta(days=1),
            due_date=timezone.localdate() + timedelta(days=3),
        )
        self.task_other = Task.objects.create(
            title="Task altri",
            created_by=self.owner,
            assigned_to=self.owner,
            project=self.project,
            next_step_due=timezone.localdate() + timedelta(days=2),
            due_date=timezone.localdate() + timedelta(days=5),
        )

    def test_capo_commessa_edit_all_can_manage_entire_kickoff(self):
        TaskRoleAccessRule.objects.create(
            role_type=TaskRoleType.CAPO_COMMESSA,
            access_level=TaskAccessLevel.EDIT_ALL,
        )
        self.client.force_login(self.capo)

        response_projects = self.client.get(reverse("tasks:project_list"))
        self.assertEqual(response_projects.status_code, 200)
        self.assertContains(response_projects, self.project.name)

        response_edit = self.client.get(reverse("tasks:edit", args=[self.task_other.id]))
        self.assertEqual(response_edit.status_code, 200)

    def test_programmer_edit_assigned_can_only_edit_own_tasks(self):
        TaskRoleAccessRule.objects.create(
            role_type=TaskRoleType.PROGRAMMER,
            access_level=TaskAccessLevel.EDIT_ASSIGNED,
        )
        self.client.force_login(self.programmer)

        response_detail = self.client.get(reverse("tasks:detail", args=[self.task_other.id]))
        self.assertEqual(response_detail.status_code, 200)

        response_allowed = self.client.post(
            reverse("tasks:project_gantt_update_task", args=[self.project.id, self.task_prog.id]),
            {
                f"task_{self.task_prog.id}-next_step_due": "2026-03-10",
                f"task_{self.task_prog.id}-due_date": "2026-03-12",
                f"task_{self.task_prog.id}-status": TaskStatus.IN_PROGRESS,
            },
        )
        self.assertEqual(response_allowed.status_code, 302)

        response_denied = self.client.post(
            reverse("tasks:project_gantt_update_task", args=[self.project.id, self.task_other.id]),
            {
                f"task_{self.task_other.id}-next_step_due": "2026-03-10",
                f"task_{self.task_other.id}-due_date": "2026-03-12",
                f"task_{self.task_other.id}-status": TaskStatus.IN_PROGRESS,
            },
        )
        self.assertEqual(response_denied.status_code, 403)

    def test_project_manager_read_all_can_view_but_not_edit(self):
        TaskRoleAccessRule.objects.create(
            role_type=TaskRoleType.PROJECT_MANAGER,
            access_level=TaskAccessLevel.READ_ALL,
        )
        self.client.force_login(self.pm_user)

        response_detail = self.client.get(reverse("tasks:detail", args=[self.task_other.id]))
        self.assertEqual(response_detail.status_code, 200)

        response_edit = self.client.get(reverse("tasks:edit", args=[self.task_other.id]))
        self.assertEqual(response_edit.status_code, 403)

    def test_user_override_edit_all_grants_global_scope_and_manage(self):
        TaskUserAccessRule.objects.create(
            user=self.override_user,
            access_level=TaskAccessLevel.EDIT_ALL,
        )
        self.client.force_login(self.override_user)

        response_detail = self.client.get(reverse("tasks:detail", args=[self.task_other.id]))
        self.assertEqual(response_detail.status_code, 200)

        response_edit = self.client.get(reverse("tasks:edit", args=[self.task_other.id]))
        self.assertEqual(response_edit.status_code, 200)

    def test_settings_access_tab_persists_role_and_user_rules(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("tasks:impostazioni"),
            {
                "tab": "accessi",
                f"access_role__{TaskRoleType.CAPO_COMMESSA}": TaskAccessLevel.EDIT_ALL,
                f"access_role__{TaskRoleType.PROGRAMMER}": TaskAccessLevel.EDIT_ASSIGNED,
                f"access_role__{TaskRoleType.PROJECT_MANAGER}": TaskAccessLevel.READ_ALL,
                "visible_access_user_id": [str(self.override_user.id)],
                f"access_user__{self.override_user.id}": TaskAccessLevel.EDIT_ALL,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            TaskRoleAccessRule.objects.filter(
                role_type=TaskRoleType.CAPO_COMMESSA,
                access_level=TaskAccessLevel.EDIT_ALL,
            ).exists()
        )
        self.assertTrue(
            TaskRoleAccessRule.objects.filter(
                role_type=TaskRoleType.PROGRAMMER,
                access_level=TaskAccessLevel.EDIT_ASSIGNED,
            ).exists()
        )
        self.assertTrue(
            TaskUserAccessRule.objects.filter(
                user=self.override_user,
                access_level=TaskAccessLevel.EDIT_ALL,
            ).exists()
        )

    def test_custom_role_category_rule_grants_scope(self):
        role = TaskRoleDefinition.objects.create(
            code="COLLAUDATORE",
            name="Collaudatore",
            order_index=40,
        )
        category = TaskCategory.objects.create(
            name="Collaudo finale",
            slug="collaudo-finale",
            role_type=role.code,
        )
        task = Task.objects.create(
            title="Task collaudo",
            created_by=self.owner,
            assigned_to=self.owner,
            project=self.project,
            category=category,
            next_step_due=timezone.localdate() + timedelta(days=1),
            due_date=timezone.localdate() + timedelta(days=3),
        )
        TaskRoleAssignment.objects.create(user=self.outsider, role_type=role.code)
        TaskRoleAccessRule.objects.create(role_type=role.code, access_level=TaskAccessLevel.EDIT_ALL)
        self.client.force_login(self.outsider)

        response_detail = self.client.get(reverse("tasks:detail", args=[task.id]))
        self.assertEqual(response_detail.status_code, 200)

        response_edit = self.client.get(reverse("tasks:edit", args=[task.id]))
        self.assertEqual(response_edit.status_code, 200)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class KickoffMeetingProjectScopeTests(TasksBaseTestCase):
    """I kickoff programmati compaiono ai partecipanti anche senza task nel progetto."""

    def setUp(self):
        super().setUp()
        _ensure_role(1, "admin")
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit", "tasks_comment"])
        self._refresh_acl_cache()

        self.owner = _create_user_with_legacy(
            username="ko_scope_owner", legacy_user_id=9701, role_id=2, role_name="utente"
        )
        # Partecipante: NON admin, NON full-read, senza task nel progetto e non PM/capo/programmer.
        self.partecipante = _create_user_with_legacy(
            username="ko_scope_part", legacy_user_id=9702, role_id=2, role_name="utente"
        )

        # NB: Project.save() auto-genera "KICK-OFF N" se il nome è vuoto; passando
        # sia name che kickoff_number il nome custom viene preservato.
        self.project_kickoff = make_project(
            name="Commessa con kickoff ZZ1", kickoff_number=9101, created_by=self.owner
        )
        self.project_estraneo = make_project(
            name="Commessa estranea ZZ2", kickoff_number=9102, created_by=self.owner
        )

        meeting = KickoffMeeting.objects.create(
            project=self.project_kickoff, numero=1, data=timezone.localdate()
        )
        meeting.partecipanti_utenti.add(self.partecipante)

    def test_participant_sees_kickoff_project_in_list(self):
        self.client.force_login(self.partecipante)
        response = self.client.get(reverse("tasks:project_list"))
        self.assertEqual(response.status_code, 200)
        # Il progetto dell'incontro a cui partecipa deve comparire...
        self.assertContains(response, "Commessa con kickoff ZZ1")
        # ...mentre un progetto estraneo (nessun kickoff/task suoi) resta escluso.
        self.assertNotContains(response, "Commessa estranea ZZ2")

    def test_meeting_creator_sees_project_in_list(self):
        creatore = _create_user_with_legacy(
            username="ko_scope_creator", legacy_user_id=9703, role_id=2, role_name="utente"
        )
        KickoffMeeting.objects.create(
            project=self.project_estraneo, numero=1, data=timezone.localdate(), created_by=creatore
        )
        self.client.force_login(creatore)
        response = self.client.get(reverse("tasks:project_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Commessa estranea ZZ2")
