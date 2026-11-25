"""KICK-OFF 25/11/2026: PM e Capocommessa un ruolo solo, menu più corto, barre uniche, stato che porta alle scadute."""
from __future__ import annotations

import importlib
from datetime import timedelta

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Project, ProjectMember, Task, TaskImpostazioni, TaskStatus

User = get_user_model()


class RuoloUnicoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="g3_admin", email="g3@x.local", password="x")
        cls.anna = User.objects.create_user(username="g3_anna", password="x")
        cls.bruno = User.objects.create_user(username="g3_bruno", password="x")

    def test_pm_e_alias_del_capocommessa(self):
        p = Project.objects.create(name="Alias", created_by=self.admin)
        p.add_team_member("project_managers", self.anna)
        self.assertEqual(ProjectMember.objects.get(project=p).role_code, "CC")
        self.assertEqual(p.team_members("PM"), [self.anna])
        self.assertEqual(p.team_members("capi_commessa"), [self.anna])
        self.assertEqual([b["label"] for b in p.team_blocks], ["Capocommessa", "Programmatore", "Caporeparto"])

    def test_migrazione_unisce_pm_in_cc(self):
        p = Project.objects.create(name="Migra", created_by=self.admin)
        ProjectMember.objects.create(project=p, user=self.anna, role_code="PM")
        ProjectMember.objects.create(project=p, user=self.bruno, role_code="PM")
        ProjectMember.objects.create(project=p, user=self.bruno, role_code="CC")
        cfg = TaskImpostazioni.get_singleton()
        cfg.poteri_ruoli = "PM,CC,PRG"
        cfg.avvisi_destinatari = "INCARICATO,PM"
        cfg.save()
        mod = importlib.import_module("tasks.migrations.0075_capocommessa_unico")
        mod.unisci(django_apps, None)
        righe = sorted(ProjectMember.objects.filter(project=p).values_list("user__username", "role_code"))
        self.assertEqual(righe, [("g3_anna", "CC"), ("g3_bruno", "CC")])
        cfg.refresh_from_db()
        self.assertEqual(cfg.poteri_ruoli, "CC,PRG")
        self.assertEqual(cfg.avvisi_destinatari, "INCARICATO,CC")

    def test_form_kickoff_senza_project_manager(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("tasks:project_create")).content.decode()
        self.assertNotIn("Project manager", html)
        self.assertIn("Capocommessa", html)


class MenuEBarreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="g3_menu", email="m@x.local", password="x")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_menu_kickoff_piu_corto(self):
        from core.models import NavigationItem

        visibili = set(NavigationItem.objects.filter(parent_code="tasks", is_visible=True).values_list("code", flat=True))
        for code in ("tasks-sub-calendario", "tasks-sub-registro-fai", "tasks-sub-report-fai"):
            self.assertNotIn(code, visibili)
        self.assertEqual(NavigationItem.objects.get(code="tasks-sub-programmi").label, "Programmi e FAI")

    def test_schede_programmi_e_fai(self):
        for nome in ("tasks:programmi_registro", "tasks:fai_registro", "tasks:fai_report"):
            html = self.client.get(reverse(nome)).content.decode()
            self.assertIn("pfai-schede", html, nome)
        self.assertIn(reverse("tasks:incontri_calendario"), self.client.get(reverse("tasks:list")).content.decode())

    def test_portfolio_senza_ripetizioni_e_stato_che_porta_alle_scadute(self):
        p = Project.objects.create(name="In ritardo", created_by=self.admin, phase="EXEC")
        Task.objects.create(title="Scaduta", project=p, created_by=self.admin, status=TaskStatus.TODO,
                            due_date=timezone.localdate() - timedelta(days=2))
        html = self.client.get(reverse("tasks:project_list")).content.decode()
        self.assertNotIn("Dashboard attività", html)
        self.assertNotIn("ts-hero-pill", html)
        self.assertIn(reverse("tasks:project_actions", args=[p.pk]) + "?scadenza=scadute", html)
        board = self.client.get(reverse("tasks:project_list") + "?view=board").content.decode()
        self.assertIn("kel-menu", board)
        self.assertIn(reverse("tasks:project_actions", args=[p.pk]) + "?scadenza=scadute", board)

    def test_le_mie_commesse_barra_unica(self):
        Project.objects.create(name="Aperta uno", created_by=self.admin)
        Project.objects.create(name="Altra", created_by=self.admin)
        r = self.client.get(reverse("tasks:cruscotto_commesse") + "?tutte=1&q=uno")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["n_aperte"], 1)
        self.assertEqual(r.content.decode().count('name="q"'), 1)

    def test_da_gestire_filtro_sezione(self):
        Project.objects.create(name="Senza VRF", created_by=self.admin)
        r = self.client.get(reverse("tasks:da_gestire") + "?scope=portfolio&sezione=vrf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["key"] for s in r.context["da_gestire_data"]["sections"]], ["vrf"])
        self.assertTrue(any(f["key"] == "not_ready" for f in r.context["dg_filtri"]))
        r = self.client.get(reverse("tasks:da_gestire") + "?scope=portfolio&sezione=xyz")
        self.assertGreater(len(r.context["da_gestire_data"]["sections"]), 1)
