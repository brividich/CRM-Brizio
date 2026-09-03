from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import RoutePermissionBinding

from .action_register import count_project_open_actions
from .acl_bootstrap import bootstrap_tasks_acl_endpoints
from .models import (
    KickoffMeeting,
    MeetingIssue,
    MeetingStatus,
    Project,
    ProjectPhase,
    SubTask,
    Task,
    TaskStatus,
    VRFDocStatus,
)
from .tests import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ProjectOverviewTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.owner = _create_user_with_legacy(
            username="overview-owner",
            legacy_user_id=9301,
            role_id=2,
            role_name="tasks",
        )
        self.reader = _create_user_with_legacy(
            username="overview-reader",
            legacy_user_id=9302,
            role_id=2,
            role_name="tasks",
        )
        self.outsider = _create_user_with_legacy(
            username="overview-outsider",
            legacy_user_id=9303,
            role_id=2,
            role_name="tasks",
        )
        today = timezone.localdate()
        self.project = Project.objects.create(
            name="",
            client_name="Cliente Demo",
            part_number="PN-OVERVIEW",
            revisione="C",
            project_manager=self.owner,
            capo_commessa=self.owner,
            programmer=self.owner,
            phase=ProjectPhase.EXEC,
            vrf_status=VRFDocStatus.NOT_REQUIRED,
            created_by=self.owner,
        )
        self.completed_meeting = KickoffMeeting.objects.create(
            project=self.project,
            numero=1,
            titolo="Avvio",
            stato=MeetingStatus.SVOLTO,
            data=today - timedelta(days=2),
            created_by=self.owner,
        )
        self.next_meeting = KickoffMeeting.objects.create(
            project=self.project,
            numero=2,
            titolo="Allineamento",
            stato=MeetingStatus.PIANIFICATO,
            data=today + timedelta(days=4),
            created_by=self.owner,
        )
        self.open_task = Task.objects.create(
            title="Preparare attrezzatura",
            project=self.project,
            created_by=self.owner,
            assigned_to=self.reader,
            due_date=today + timedelta(days=7),
        )
        Task.objects.create(
            title="Attività completata",
            project=self.project,
            created_by=self.owner,
            due_date=today - timedelta(days=1),
            status=TaskStatus.DONE,
        )
        self.subtask = SubTask.objects.create(
            task=self.open_task,
            title="Confermare disponibilità",
        )
        self.issue = MeetingIssue.objects.create(
            project=self.project,
            source_meeting=self.completed_meeting,
            title="Chiudere requisito aperto",
            due_date=today - timedelta(days=1),
            created_by=self.owner,
        )

    def test_overview_renders_for_in_scope_user_and_404_outside_scope(self):
        self.client.force_login(self.reader)

        visible_response = self.client.get(
            reverse("tasks:project_overview", args=[self.project.pk])
        )
        self.client.force_login(self.outsider)
        hidden_response = self.client.get(
            reverse("tasks:project_overview", args=[self.project.pk])
        )

        self.assertEqual(visible_response.status_code, 200)
        self.assertEqual(hidden_response.status_code, 404)

    def test_overview_metrics_match_fixture(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["action_open_count"], 3)
        self.assertEqual(response.context["next_meeting"], self.next_meeting)
        self.assertEqual(response.context["planned_task_count"], 2)
        self.assertEqual(response.context["total_task_count"], 2)
        self.assertEqual(response.context["readiness"].met, 4)
        self.assertEqual(
            [row.title for row in response.context["top_actions"]],
            [
                "Chiudere requisito aperto",
                "Preparare attrezzatura",
                "Confermare disponibilità",
            ],
        )
        self.assertEqual(
            [meeting.pk for meeting in response.context["recent_meetings"]],
            [self.next_meeting.pk, self.completed_meeting.pk],
        )
        self.assertContains(response, "2/2")
        self.assertContains(response, "Pronto 4/4")

    def test_tab_action_counter_uses_three_count_queries(self):
        with self.assertNumQueries(3):
            action_count = count_project_open_actions(self.project)

        self.assertEqual(action_count, 3)

    def test_all_five_tabs_render_with_the_correct_active_item(self):
        self.client.force_login(self.owner)
        routes = (
            ("tasks:project_overview", "Panoramica"),
            ("tasks:project_actions", "Azioni (3)"),
            ("tasks:project_meetings", "Incontri"),
            ("tasks:project_gantt", "Piano"),
            ("tasks:project_vrf_upload", "VRF"),
        )

        for active_route, active_label in routes:
            with self.subTest(active_route=active_route):
                response = self.client.get(reverse(active_route, args=[self.project.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, ">Panoramica</a>")
                self.assertContains(response, ">Azioni (3)</a>")
                self.assertContains(response, ">Incontri</a>")
                self.assertContains(response, ">Piano</a>")
                self.assertContains(response, ">VRF</a>")
                active_url = reverse(active_route, args=[self.project.pk])
                self.assertContains(
                    response,
                    f'<a class="tk-tab tk-tab--active" href="{active_url}">{active_label}</a>',
                    html=True,
                )

    def test_read_only_user_does_not_see_modification_calls_to_action(self):
        Project.objects.filter(pk=self.project.pk).update(vrf_status=VRFDocStatus.PENDING)
        self.client.force_login(self.reader)

        response = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_manage"])
        self.assertNotContains(response, "Gestisci VRF")
        self.assertNotContains(response, "Nuovo incontro")
        self.assertNotContains(response, "+ Nuova attività")
        self.assertNotContains(response, ">Sistema</a>")

    def test_manager_sees_modification_calls_to_action(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))

        self.assertTrue(response.context["can_manage"])
        self.assertContains(response, "Gestisci VRF")
        self.assertContains(response, "Nuovo incontro")
        self.assertContains(response, "+ Nuova attività")

    def test_portfolio_name_opens_overview_while_gantt_button_stays_on_plan(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("tasks:project_list"))

        self.assertContains(
            response,
            f'class="pf-card-name" href="{reverse("tasks:project_overview", args=[self.project.pk])}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("tasks:project_gantt", args=[self.project.pk])}">Gantt</a>',
        )

    def test_overview_route_uses_existing_project_permission_binding(self):
        bootstrap_tasks_acl_endpoints(force=True)

        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="tasks:project_overview",
                permission_id="tasks.kickoff.projects",
                is_active=True,
            ).exists()
        )

    def test_literal_project_routes_remain_ahead_of_overview_route(self):
        self.assertEqual(reverse("tasks:project_create"), "/tasks/projects/new/")
        self.assertEqual(
            reverse("tasks:identity_suggest"),
            "/tasks/projects/identity-suggest/",
        )
        self.assertEqual(
            reverse("tasks:project_overview", args=[self.project.pk]),
            f"/tasks/projects/{self.project.pk}/",
        )
