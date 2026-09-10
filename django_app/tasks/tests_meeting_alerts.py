"""Segnalazioni incontri sulla dashboard KICK-OFF.

Copre le tre cose che erano rotte o assenti: la banda «prossimi / da gestire»,
lo scope personale del centro «Da gestire» (che con i ruoli M2M sollevava
FieldError e faceva sparire le sezioni) e la risoluzione namespaced di
/tasks/projects/, da cui dipende la subnav di modulo.
"""
from __future__ import annotations

import datetime as dt

from django.test import override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from tasks.models import KickoffMeeting, MeetingStatus, Project
from tasks.tests import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
)
from .tests_utils import make_project


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MeetingAlertsTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="alerts-pm",
            legacy_user_id=411,
            role_id=2,
            role_name="tasks",
        )
        self.project = make_project(
            name="", created_by=self.user, project_manager=self.user
        )
        self.today = timezone.localdate()
        self.client.force_login(self.user)

    def _meeting(self, *, offset_days: int, stato: str, titolo: str) -> KickoffMeeting:
        meeting = KickoffMeeting.objects.create(
            project=self.project,
            data=self.today + dt.timedelta(days=offset_days),
            titolo=titolo,
            stato=stato,
            created_by=self.user,
        )
        meeting.partecipanti_utenti.add(self.user)
        return meeting

    def test_prossimo_incontro_in_banda_segnalazioni(self):
        self._meeting(offset_days=3, stato=MeetingStatus.PIANIFICATO, titolo="Avanzamento 1")
        response = self.client.get(reverse("tasks:list"))
        self.assertEqual(response.status_code, 200)
        alerts = response.context["meeting_alerts"]
        self.assertEqual([row["label"] for row in alerts["prossimi"]], ["Avanzamento 1"])
        self.assertEqual(alerts["prossimi"][0]["quando"], "Tra 3 giorni")
        self.assertFalse(alerts["da_gestire"])

    def test_incontro_passato_senza_esito_va_in_da_gestire(self):
        self._meeting(offset_days=-4, stato=MeetingStatus.PIANIFICATO, titolo="Avanzamento 0")
        response = self.client.get(reverse("tasks:list"))
        alerts = response.context["meeting_alerts"]
        self.assertFalse(alerts["prossimi"])
        self.assertEqual(len(alerts["da_gestire"]), 1)
        row = alerts["da_gestire"][0]
        self.assertEqual(row["tone"], "danger")
        self.assertIn("Esito non registrato", row["motivo"])
        # Il PM gestisce la commessa: gli viene proposta l'azione diretta.
        self.assertEqual(row["action_label"], "Registra esito")

    def test_minuta_non_approvata_va_in_da_gestire(self):
        self._meeting(offset_days=-2, stato=MeetingStatus.SVOLTO, titolo="Avanzamento svolto")
        response = self.client.get(reverse("tasks:list"))
        alerts = response.context["meeting_alerts"]
        self.assertEqual([row["motivo"] for row in alerts["da_gestire"]], ["Minuta da approvare"])

    def test_incontri_fuori_scope_non_compaiono(self):
        altro_utente = _create_user_with_legacy(
            username="alerts-altro",
            legacy_user_id=412,
            role_id=2,
            role_name="tasks",
        )
        altro_progetto = make_project(
            name="", created_by=altro_utente, project_manager=altro_utente
        )
        KickoffMeeting.objects.create(
            project=altro_progetto,
            data=self.today + dt.timedelta(days=1),
            titolo="Non mio",
            stato=MeetingStatus.PIANIFICATO,
            created_by=altro_utente,
        )
        response = self.client.get(reverse("tasks:list"))
        alerts = response.context["meeting_alerts"]
        self.assertNotIn("Non mio", [row["label"] for row in alerts["prossimi"]])

    def test_da_gestire_scope_personale_non_solleva_field_error(self):
        """Lo scope «mine» filtrava su FK di team che non esistono piu' (M2M)."""
        from tasks.da_gestire import build_kickoff_da_gestire

        self._meeting(offset_days=-1, stato=MeetingStatus.PIANIFICATO, titolo="Avanzamento")
        response = self.client.get(reverse("tasks:da_gestire"), {"scope": "mine"})
        self.assertEqual(response.status_code, 200)
        data = build_kickoff_da_gestire(response.wsgi_request, "mine")
        # Quattro sezioni costruite: nessuna persa per eccezione inghiottita.
        self.assertEqual(len(data["sections"]), 4)


class ProjectListRoutingTests(TasksBaseTestCase):
    def test_projects_url_resolve_namespaced(self):
        """L'alias di compatibilita' non deve oscurare la rotta di modulo.

        Con app_name vuoto il context processor non trovava la subnav e il
        binding ACL «tasks:project_list» non veniva mai applicato.
        """
        match = resolve("/tasks/projects/")
        self.assertEqual(match.app_name, "tasks")
        self.assertEqual(match.view_name, "tasks:project_list")

    def test_alias_non_namespaced_resta_reversibile(self):
        self.assertEqual(reverse("project_list"), "/tasks/projects/")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ProjectStartDateTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="start-date",
            legacy_user_id=413,
            role_id=2,
            role_name="tasks",
        )
        self.project = make_project(
            name="", created_by=self.user, project_manager=self.user
        )
        self.client.force_login(self.user)

    def test_data_inizio_e_il_primo_incontro_non_annullato(self):
        KickoffMeeting.objects.create(
            project=self.project, data=dt.date(2026, 3, 2), stato=MeetingStatus.ANNULLATO, created_by=self.user
        )
        KickoffMeeting.objects.create(
            project=self.project, data=dt.date(2026, 4, 6), stato=MeetingStatus.SVOLTO, created_by=self.user
        )
        KickoffMeeting.objects.create(
            project=self.project, data=dt.date(2026, 5, 4), stato=MeetingStatus.PIANIFICATO, created_by=self.user
        )

        response = self.client.get(reverse("tasks:project_list"))
        projects = {p.id: p for p in response.context["projects"]}
        self.assertEqual(projects[self.project.id].data_inizio, dt.date(2026, 4, 6))

        response = self.client.get(reverse("tasks:project_overview", args=[self.project.id]))
        self.assertEqual(response.context["first_meeting_date"], dt.date(2026, 4, 6))

        response = self.client.get(reverse("tasks:project_meetings", args=[self.project.id]))
        self.assertEqual(response.context["first_meeting_date"], dt.date(2026, 4, 6))

    def test_senza_incontri_la_data_inizio_e_vuota(self):
        response = self.client.get(reverse("tasks:project_list"))
        projects = {p.id: p for p in response.context["projects"]}
        self.assertIsNone(projects[self.project.id].data_inizio)
        self.assertContains(response, "da pianificare")

    def test_project_list_non_duplica_i_kickoff(self):
        """L'annotazione data_inizio e' una sottoquery: niente righe sdoppiate."""
        for offset in range(3):
            KickoffMeeting.objects.create(
                project=self.project,
                data=dt.date(2026, 4, 6) + dt.timedelta(days=offset),
                stato=MeetingStatus.PIANIFICATO,
                created_by=self.user,
            )
        response = self.client.get(reverse("tasks:project_list"))
        ids = [p.id for p in response.context["projects"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(Project.objects.count(), len(ids))
