"""Test di incontri e calendario incontri."""
from __future__ import annotations


from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone


from .models import (
    KickoffMeeting,
    MeetingIssue,
    MeetingIssueStatus,
    MeetingStatus,
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
class MeetingIssueWorkflowTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="meeting-owner",
            legacy_user_id=201,
            role_id=2,
            role_name="tasks",
        )
        self.project = make_project(name="Kickoff test", created_by=self.user)

    def test_minutes_create_managed_issue_and_carry_it_to_next_agenda(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("tasks:project_meeting_create", args=[self.project.id]),
            {
                "titolo": "Incontro 1",
                "data": "2026-04-29",
                "ora": "09:00",
                "luogo": "Sala test",
                "stato": MeetingStatus.PIANIFICATO,
                "agenda_items_raw": "[]",
            },
        )
        self.assertEqual(response.status_code, 302)
        meeting_1 = KickoffMeeting.objects.get(project=self.project, numero=1)
        self.assertEqual(meeting_1.stato, MeetingStatus.PIANIFICATO)

        # I problemi emergono durante l'incontro: si registrano nell'esito.
        response = self.client.post(
            reverse("tasks:project_meeting_minutes", args=[self.project.id, meeting_1.id]),
            {
                "note": "Discusso lo stato avanzamento",
                "problemi_aperti": "",
                "next_steps": "",
                "new_issue_title": ["Materiale mancante"],
                "new_issue_description": ["Serve conferma dal fornitore"],
                "new_issue_assigned_to": [str(self.user.id)],
                "new_issue_due_date": ["2026-05-02"],
                "new_issue_task": [""],
            },
        )

        self.assertEqual(response.status_code, 302)
        meeting_1.refresh_from_db()
        self.assertEqual(meeting_1.stato, MeetingStatus.SVOLTO)
        self.assertIsNotNone(meeting_1.svolto_at)
        issue = MeetingIssue.objects.get(project=self.project)
        self.assertEqual(issue.status, MeetingIssueStatus.OPEN)
        self.assertEqual(issue.source_meeting, meeting_1)
        self.assertEqual(issue.assigned_to, self.user)

        response = self.client.get(reverse("tasks:project_meeting_create", args=[self.project.id]))
        self.assertContains(response, "Materiale mancante")
        self.assertContains(response, "Problema aperto")

    def test_minutes_can_resolve_existing_issue_and_status_endpoint_can_reopen(self):
        self.client.force_login(self.user)
        meeting_1 = KickoffMeeting.objects.create(
            project=self.project,
            titolo="Incontro 1",
            data=timezone.localdate(),
            created_by=self.user,
        )
        issue = MeetingIssue.objects.create(
            project=self.project,
            source_meeting=meeting_1,
            title="Quote non allineate",
            created_by=self.user,
        )
        meeting_2 = KickoffMeeting.objects.create(
            project=self.project,
            titolo="Incontro 2",
            data=timezone.localdate(),
            created_by=self.user,
        )

        response = self.client.post(
            reverse("tasks:project_meeting_minutes", args=[self.project.id, meeting_2.id]),
            {
                "note": "",
                "problemi_aperti": "",
                "next_steps": "",
                "meeting_issue_ids": [str(issue.id)],
                "resolved_issue_ids": [str(issue.id)],
                f"issue_resolution_{issue.id}": "Allineate in riunione",
            },
        )

        self.assertEqual(response.status_code, 302)
        issue.refresh_from_db()
        self.assertEqual(issue.status, MeetingIssueStatus.RESOLVED)
        self.assertEqual(issue.resolution_meeting, meeting_2)
        self.assertEqual(issue.resolution_note, "Allineate in riunione")

        detail_response = self.client.get(reverse("tasks:project_meeting_detail", args=[self.project.id, meeting_2.id]))
        self.assertContains(detail_response, "Quote non allineate")
        self.assertContains(detail_response, "Allineate in riunione")

        response = self.client.post(
            reverse("tasks:project_meeting_issue_status", args=[self.project.id, meeting_2.id, issue.id]),
            {"action": "reopen"},
        )

        self.assertEqual(response.status_code, 302)
        issue.refresh_from_db()
        self.assertEqual(issue.status, MeetingIssueStatus.OPEN)
        self.assertIsNone(issue.resolution_meeting)


class MeetingsCalendarTests(TestCase):
    """Calendario incontri — griglia mensile pura."""

    def test_grid_and_placement(self):
        import types
        from datetime import date
        from tasks.calendario import build_meetings_calendar

        m = types.SimpleNamespace(data=date(2026, 7, 15))
        cal = build_meetings_calendar([m], 2026, 7, today=date(2026, 7, 6))
        assert cal["month_label"] == "Luglio 2026"
        assert cal["prev"] == "2026-06" and cal["next"] == "2026-08"
        assert all(len(w) == 7 for w in cal["weeks"])
        placed = [d for w in cal["weeks"] for d in w if d["date"] == date(2026, 7, 15)]
        assert placed and placed[0]["meetings"] == [m]
        todays = [d for w in cal["weeks"] for d in w if d["is_today"]]
        assert len(todays) == 1 and todays[0]["date"] == date(2026, 7, 6)

    def test_year_boundary(self):
        from tasks.calendario import build_meetings_calendar

        assert build_meetings_calendar([], 2026, 1)["prev"] == "2025-12"
        assert build_meetings_calendar([], 2026, 12)["next"] == "2027-01"


class MeetingsCalendarRenderTests(TestCase):
    """Calendario incontri — render pagina."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="cal_admin", email="c@x.local", password="x"
        )

    def setUp(self):
        from tasks.models import KickoffMeeting

        self.client.force_login(self.admin)
        p = make_project(name="P", created_by=self.admin)
        self.meeting = KickoffMeeting.objects.create(
            project=p, numero=1, titolo="Inc", data=timezone.localdate(), created_by=self.admin
        )

    def test_calendar_renders_current_month_with_meeting(self):
        r = self.client.get(reverse("tasks:incontri_calendario"))
        assert r.status_code == 200
        assert b"cal-grid" in r.content
        detail_url = reverse(
            "tasks:project_meeting_detail", args=[self.meeting.project_id, self.meeting.id]
        )
        assert detail_url.encode() in r.content

    def test_month_param_navigates(self):
        r = self.client.get(reverse("tasks:incontri_calendario") + "?m=2026-01")
        assert r.status_code == 200
        assert b"Gennaio 2026" in r.content


class MeetingsCalendarNavAclTests(TestCase):
    def test_subnav_seeded(self):
        from core.models import NavigationItem

        item = NavigationItem.objects.get(code="tasks-sub-calendario")
        assert item.section == "subnav" and item.parent_code == "tasks"
        assert item.route_name == "tasks:incontri_calendario"

    def test_route_bound(self):
        from core.models import RoutePermissionBinding
        from tasks.acl_bootstrap import bootstrap_tasks_acl_endpoints

        bootstrap_tasks_acl_endpoints(force=True)
        assert RoutePermissionBinding.objects.filter(
            route_name="tasks:incontri_calendario", permission_id="tasks.kickoff.view", is_active=True
        ).exists()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingCreateTaskButtonTests(TasksBaseTestCase):
    """Dalla pagina dell'incontro si può creare/assegnare un'attività anche senza next steps."""

    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="mtg-manager", legacy_user_id=9801, role_id=2, role_name="tasks"
        )
        # created_by == user → can_manage True.
        self.project = make_project(name="Progetto incontro", created_by=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project, numero=1, data=timezone.localdate(), created_by=self.user
        )

    def test_meeting_without_next_steps_shows_create_task_trigger(self):
        # Incontro privo di next steps: il trigger deve comparire lo stesso.
        self.assertEqual(self.meeting.next_steps, "")
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("tasks:project_meeting_detail", args=[self.project.id, self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crea / assegna attività")
        self.assertContains(response, 'id="ctm-overlay"')
        self.assertContains(response, 'name="assigned_to"')
