"""Riquadri numerici della scheda dipendente: ogni numero apre l'elenco che conta le stesse righe."""
from __future__ import annotations

from datetime import timedelta

from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from dashboard import views as dashboard_views
from tasks.models import Task, TaskStatus
from tasks.tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions


class SchedaDipendenteKpiLinkTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="eb-kpi", legacy_user_id=761, role_id=2, role_name="tasks")
        self.altro = _create_user_with_legacy(username="eb-altro", legacy_user_id=762, role_id=2, role_name="tasks")
        oggi = timezone.localdate()
        Task.objects.create(title="Mia scaduta", created_by=self.altro, assigned_to=self.user,
                            status=TaskStatus.TODO, due_date=oggi - timedelta(days=1))
        Task.objects.create(title="Mia in corso", created_by=self.altro, assigned_to=self.user,
                            status=TaskStatus.IN_PROGRESS)
        Task.objects.create(title="Mia chiusa", created_by=self.altro, assigned_to=self.user, status=TaskStatus.DONE)
        # Creata da me ma assegnata ad altri: «le mie» la mostrerebbe, il riquadro no.
        Task.objects.create(title="Creata da me", created_by=self.user, assigned_to=self.altro, status=TaskStatus.TODO)
        self.client.force_login(self.user)

    def test_riquadri_attivita_e_elenco_contano_lo_stesso(self):
        dati = dashboard_views._board_data_tasks(761, {"max_items": 5})
        self.assertEqual(dati["user_id"], self.user.pk)
        html = render_to_string("dashboard/partials/widget_body.html",
                                {"w": {"id": "tasks_stats"}, "widget_data": {"tasks_stats": dati}})
        base = f"{reverse('tasks:list')}?mine=0&assigned_to={self.user.pk}"
        for filtro, chiave in (("&status=TODO", "todo"), ("&status=IN_PROGRESS", "in_progress"),
                               ("&status=DONE", "done"), ("&overdue=on", "overdue")):
            self.assertIn(f'href="{(base + filtro).replace("&", "&amp;")}"', html)
            elenco = self.client.get(base + filtro)
            self.assertEqual(elenco.status_code, 200)
            self.assertEqual(len(elenco.context["tasks"]), dati["stats"][chiave], filtro)

    def test_panoramica_task_aperti_apre_le_assegnate_aperte(self):
        dati = dashboard_views._board_data_module_overview(self.user, None, 761, {})
        card = next(c for c in dati["cards"] if c["label"] == "Task aperti")
        elenco = self.client.get(card["url"])
        self.assertEqual(len(elenco.context["tasks"]), card["value"])
        self.assertEqual(card["value"], 2)

    def test_riquadri_letture_portano_ai_filtri_di_le_mie_letture(self):
        html = render_to_string("dashboard/partials/widget_body.html", {
            "w": {"id": "procedure_da_leggere"},
            "widget_data": {"procedure_da_leggere": {"items": [], "stats": {"pending": 2, "overdue": 1, "confirmed": 3}}},
        })
        u = reverse("procedure_refresh:my_assignments")
        for stato in ("pending", "overdue", "read_confirmed"):
            self.assertIn(f'href="{u}?status={stato}"', html)
