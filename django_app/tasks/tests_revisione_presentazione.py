"""Revisione del modulo KICK-OFF del 09/11/2026 (secondo giro prima della presentazione).

Copre: date del form di modifica (prima vuote e cancellate al salvataggio),
scadenza delle card del portfolio senza le attivita' chiuse, percentuale di
avanzamento unica, pulsanti del responsabile nella scheda, notifica di
completamento a chi ha assegnato, riquadro «Le mie azioni» coerente con la
pagina, voce di menu.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from tasks.models import Task, TaskStatus
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RevisionePresentazioneTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="rp-pm", legacy_user_id=611, role_id=2, role_name="tasks")
        self.resp = _create_user_with_legacy(username="rp-resp", legacy_user_id=612, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa revisione", created_by=self.pm, project_manager=self.pm)
        self.oggi = timezone.localdate()

    def _task(self, **kwargs):
        dati = {"title": "Lavorazione", "project": self.project, "created_by": self.pm, "assigned_to": self.resp}
        dati.update(kwargs)
        return Task.objects.create(**dati)

    def test_form_modifica_mostra_le_date_in_formato_iso(self):
        task = self._task(next_step_due=self.oggi, due_date=self.oggi + timedelta(days=4))
        self.client.force_login(self.pm)
        html = self.client.get(reverse("tasks:edit", args=[task.pk])).content.decode()
        self.assertIn(f'value="{self.oggi:%Y-%m-%d}"', html)
        self.assertIn(f'value="{self.oggi + timedelta(days=4):%Y-%m-%d}"', html)

    def test_portfolio_non_conta_le_attivita_chiuse_come_scadute(self):
        self._task(title="Chiusa da tempo", status=TaskStatus.DONE, due_date=self.oggi - timedelta(days=15))
        self._task(title="Aperta", due_date=self.oggi + timedelta(days=5))
        self.client.force_login(self.pm)
        html = self.client.get(reverse("tasks:project_list")).content.decode()
        self.assertNotIn("In ritardo di 15gg", html)
        self.assertIn("Prossima scadenza tra 5gg", html)
        self.assertIn("50%", html)

    def test_avanzamento_uguale_su_portfolio_panoramica_e_gantt(self):
        self._task(status=TaskStatus.DONE)
        self._task()
        self._task(status=TaskStatus.CANCELED)
        self.client.force_login(self.pm)
        for nome in ("tasks:project_overview", "tasks:project_gantt"):
            html = self.client.get(reverse(nome, args=[self.project.id])).content.decode()
            self.assertIn("50%", html, nome)

    def test_il_responsabile_cambia_lo_stato_dalla_scheda(self):
        task = self._task()
        self.client.force_login(self.resp)
        html = self.client.get(reverse("tasks:detail", args=[task.pk])).content.decode()
        self.assertIn(reverse("tasks:mia_voce_stato", args=["attivita", task.pk]), html)
        risposta = self.client.post(
            reverse("tasks:mia_voce_stato", args=["attivita", task.pk]),
            {"action": "done", "next": reverse("tasks:detail", args=[task.pk])},
        )
        self.assertRedirects(risposta, reverse("tasks:detail", args=[task.pk]), fetch_redirect_response=False)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)

    def test_chi_ha_assegnato_sa_che_e_fatta(self):
        task = self._task()
        self.client.force_login(self.resp)
        with patch("tasks.services.meeting_tasks.notify_user") as notifica:
            self.client.post(reverse("tasks:mia_voce_stato", args=["attivita", task.pk]), {"action": "done"})
        notifica.assert_called_once()
        self.assertEqual(notifica.call_args.args[0], self.pm)
        self.assertIn("ha completato", notifica.call_args.args[1])

    def test_riquadro_le_mie_azioni_conta_anche_le_attivita(self):
        from tasks.meeting_alerts import _mie_voci
        from tasks.models import Project

        self._task(title="Mia attività", due_date=self.oggi - timedelta(days=1))
        righe = _mie_voci(self.resp, Project.objects.all(), self.oggi)
        self.assertEqual([r["title"] for r in righe], ["Mia attività"])
        self.assertTrue(righe[0]["scaduta"])

    def test_dashboard_mette_le_aperte_prima_delle_completate(self):
        self._task(title="Completata prima", status=TaskStatus.DONE, due_date=self.oggi - timedelta(days=9),
                   assigned_to=self.pm)
        self._task(title="Aperta dopo", due_date=self.oggi + timedelta(days=3), assigned_to=self.pm)
        self.client.force_login(self.pm)
        html = self.client.get(reverse("tasks:list")).content.decode()
        self.assertLess(html.index("Aperta dopo"), html.index("Completata prima"))
        self.assertNotIn("Control room", html)
        self.assertNotIn(">Overdue<", html)

    def test_voce_di_menu_le_mie_azioni(self):
        from core.models import NavigationItem

        voce = NavigationItem.objects.get(code="tasks-sub-mie-azioni")
        self.assertEqual(voce.route_name, "tasks:mie_azioni")
        self.assertEqual(voce.parent_code, "tasks")
