"""Test delle impostazioni/amministrazione e della shell KICK-OFF."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, Notifica

from .models import (
    Task,
    TaskImpostazioni,
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
class TaskAdminSettingsTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(1, "admin")
        self._refresh_acl_cache()
        self.admin_user = _create_user_with_legacy(
            username="taskadmin",
            legacy_user_id=9001,
            role_id=1,
            role_name="admin",
        )

    def test_legacy_gestione_route_redirects_to_settings_tab(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("tasks:gestione_admin"))
        self.assertRedirects(response, f"{reverse('tasks:impostazioni')}?tab=riepilogo")

    def test_every_settings_tab_renders(self):
        """Ogni tab ha il corpo in un include dedicato: verifica che risolvano tutti."""
        self.client.force_login(self.admin_user)
        for tab in ("config", "riepilogo", "record", "ruoli", "accessi", "promemoria", "tipi", "modelli", "log"):
            with self.subTest(tab=tab):
                response = self.client.get(reverse("tasks:impostazioni"), {"tab": tab})
                self.assertEqual(response.status_code, 200)

    def test_settings_config_tab_is_slimmer_with_compact_branding(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("tasks:impostazioni"), {"tab": "config"})
        self.assertEqual(response.status_code, 200)
        # Blocco ridondante rimosso (titolo + callout).
        self.assertNotContains(response, "Tutte le impostazioni modificabili")
        # Branding card in variante compatta (modificatore condiviso del Task 4).
        self.assertContains(response, "ms-card--compact")

    def test_settings_page_shows_and_saves_all_editable_fields(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("tasks:impostazioni"), {"tab": "config"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="responsabile_email"', html=False)
        self.assertContains(response, 'name="notifiche_scadenza_attive"', html=False)
        self.assertContains(response, 'name="giorni_preavviso"', html=False)
        self.assertContains(response, 'name="note_generali"', html=False)
        self.assertContains(response, 'name="vrf_reminder_days"', html=False)
        self.assertContains(response, 'name="vrf_blocking_days"', html=False)
        self.assertContains(response, 'name="branding_display_label"', html=False)

        post_response = self.client.post(
            f"{reverse('tasks:impostazioni')}?tab=config",
            {
                "responsabile_email": "kickoff@example.com",
                "notifiche_scadenza_attive": "on",
                "giorni_preavviso": "5",
                "note_generali": "Note test admin",
                "vrf_reminder_days": "11",
                "vrf_blocking_days": "40",
            },
        )
        self.assertRedirects(post_response, f"{reverse('tasks:impostazioni')}?tab=config")

        cfg = TaskImpostazioni.get_singleton()
        self.assertEqual(cfg.responsabile_email, "kickoff@example.com")
        self.assertTrue(cfg.notifiche_scadenza_attive)
        self.assertEqual(cfg.giorni_preavviso, 5)
        self.assertEqual(cfg.note_generali, "Note test admin")
        self.assertEqual(cfg.vrf_reminder_days, 11)
        self.assertEqual(cfg.vrf_blocking_days, 40)

    def test_record_elimina_kickoff_solo_con_motivazione(self):
        from tasks.models import Project, Task

        project = Project.objects.create(name="Da cancellare", created_by=self.admin_user)
        Task.objects.create(title="Attivita' figlia", project=project, created_by=self.admin_user)
        self.client.force_login(self.admin_user)

        # Senza motivazione non si cancella niente.
        senza = self.client.post(
            reverse("tasks:impostazioni_kickoff_delete", args=[project.pk]),
            {"motivo": "   "},
            follow=True,
        )
        self.assertContains(senza, "Serve la motivazione")
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())

        self.client.post(
            reverse("tasks:impostazioni_kickoff_delete", args=[project.pk]),
            {"motivo": "Commessa aperta per errore"},
        )
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())
        voce = AuditLog.objects.filter(azione="kickoff_project_delete").order_by("-id").first()
        self.assertIsNotNone(voce)
        self.assertIn("Commessa aperta per errore", str(voce.dettaglio))

    def test_record_elimina_attivita_solo_con_motivazione(self):
        from tasks.models import Project, Task

        project = Project.objects.create(name="Commessa viva", created_by=self.admin_user)
        task = Task.objects.create(title="Da cancellare", project=project, created_by=self.admin_user)
        self.client.force_login(self.admin_user)

        self.client.post(reverse("tasks:impostazioni_task_delete", args=[task.pk]), {"motivo": ""})
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())

        self.client.post(
            reverse("tasks:impostazioni_task_delete", args=[task.pk]),
            {"motivo": "Doppione"},
        )
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())

    def test_record_cancellazione_richiede_i_permessi_impostazioni(self):
        from tasks.models import Project

        project = Project.objects.create(name="Protetta", created_by=self.admin_user)
        estraneo = _create_user_with_legacy(
            username="record-estraneo", legacy_user_id=9102, role_id=2, role_name="tasks"
        )
        self.client.force_login(estraneo)
        self.client.post(
            reverse("tasks:impostazioni_kickoff_delete", args=[project.pk]),
            {"motivo": "provo comunque"},
        )
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())

    def test_cc_predefiniti_si_salvano_dalle_impostazioni(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("tasks:impostazioni"), {"tab": "config"})
        self.assertContains(response, 'name="cc_predefiniti_utenti"', html=False)
        self.assertContains(response, 'name="cc_predefinite_email"', html=False)

        self.client.post(
            f"{reverse('tasks:impostazioni')}?tab=config",
            {
                "responsabile_email": "",
                "giorni_preavviso": "3",
                "note_generali": "",
                "vrf_reminder_days": "7",
                "vrf_blocking_days": "30",
                "cc_predefiniti_utenti": [str(self.admin_user.pk)],
                "cc_predefinite_email": "direzione@example.com\nriga-non-valida\n",
            },
        )
        cfg = TaskImpostazioni.get_singleton()
        # Le righe senza @ non sono indirizzi: si scartano invece di finire in copia.
        self.assertEqual(cfg.cc_predefinite_email, "direzione@example.com")
        self.assertEqual(list(cfg.cc_predefiniti_utenti.values_list("pk", flat=True)), [self.admin_user.pk])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TaskReminderAdminTabTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(1, "admin")
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit"])
        self._refresh_acl_cache()
        self.admin = _create_user_with_legacy(
            username="remadmin", legacy_user_id=9401, role_id=1, role_name="admin",
        )
        self.user = _create_user_with_legacy(
            username="remuser", legacy_user_id=9501, role_id=2, role_name="utente",
        )
        self.project = make_project(name="KO rem", created_by=self.user)
        self.task = Task.objects.create(
            title="T rem", project=self.project, assigned_to=self.user,
            due_date=timezone.localdate() + timedelta(days=5),
            created_by=self.user, reminder_portal_enabled=True,
        )

    def test_postpone_shifts_fire_at(self):
        from .models import TaskReminder
        rem = TaskReminder.objects.create(
            task=self.task, legacy_user_id=9501,
            fire_at=timezone.localdate(),
        )
        original_fire = rem.fire_at
        self.client.force_login(self.admin)
        response = self.client.post(reverse("tasks:impostazioni"), {
            "tab": "promemoria",
            "reminder_action": "postpone",
            "reminder_id": [str(rem.id)],
            "postpone_days": "5",
        })
        self.assertEqual(response.status_code, 302)
        rem.refresh_from_db()
        self.assertEqual(rem.fire_at, original_fire + timedelta(days=5))

    def test_delete_removes_selected(self):
        from .models import TaskReminder
        rem = TaskReminder.objects.create(
            task=self.task, legacy_user_id=9501, fire_at=timezone.localdate(),
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("tasks:impostazioni"), {
            "tab": "promemoria",
            "reminder_action": "delete",
            "reminder_id": [str(rem.id)],
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TaskReminder.objects.filter(id=rem.id).exists())

    def test_fire_now_creates_notifica_and_marks_fired(self):
        from .models import TaskReminder
        rem = TaskReminder.objects.create(
            task=self.task, legacy_user_id=9501,
            fire_at=timezone.localdate() + timedelta(days=3),
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("tasks:impostazioni"), {
            "tab": "promemoria",
            "reminder_action": "fire_now",
            "reminder_id": [str(rem.id)],
        })
        self.assertEqual(response.status_code, 302)
        rem.refresh_from_db()
        self.assertTrue(rem.fired)
        self.assertEqual(Notifica.objects.filter(legacy_user_id=9501).count(), 1)


class TasksBaseTemplateTests(TestCase):
    """F1 Task 2 — base di modulo su core/base + componente tab commessa."""

    def test_base_extends_core(self):
        from django.template.loader import get_template

        src = Path(get_template("tasks/base.html").origin.name).read_text(encoding="utf-8")
        assert 'extends "core/base.html"' in src
        assert "core/components/page_header.html" in src

    def test_project_tabs_render_active(self):
        from django.template.loader import render_to_string

        html = render_to_string(
            "tasks/_project_tabs.html",
            {"project": type("P", (), {"id": 7})(), "active": "gantt"},
        )
        assert "/tasks/projects/7/gantt/" in html
        assert "tk-tab--active" in html


class TasksSubnavSeedTests(TestCase):
    """F1 Task 3 — subnav di modulo via NavigationItem (seed migrazione)."""

    def test_subnav_items_seeded(self):
        from core.models import NavigationItem

        items = NavigationItem.objects.filter(
            section="subnav", code__startswith="tasks-sub-"
        )
        codes = set(items.values_list("code", flat=True))
        assert {"tasks-sub-dashboard", "tasks-sub-kickoff", "tasks-sub-impostazioni"} <= codes
        # parent_code DEVE essere l'app_name 'tasks' (come lo calcola il context
        # processor), non il codice della NavigationItem topbar ('vrf-kick-off').
        assert set(items.values_list("parent_code", flat=True)) == {"tasks"}

    def test_impostazioni_is_admin_gated(self):
        from core.models import NavigationItem

        item = NavigationItem.objects.get(code="tasks-sub-impostazioni")
        assert item.required_permission_code == "tasks.kickoff.admin"
        assert item.route_name == "tasks:impostazioni"
