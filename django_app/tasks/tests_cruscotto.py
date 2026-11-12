"""Filtri del Percorso, cruscotto, confronto con il piano, durate reali dei modelli (11/11/2026)."""
from __future__ import annotations

from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from .models import GanttBaseline, ModelloCommessa, Task, TaskCategory, TaskEvent, TaskEventType, TaskStatus
from .services.filo import cruscotto, durate_reali
from .services.tappe import percorso
from .tests_programmi import ProgrammiBase


class CruscottoTests(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.project.add_team_member("CC", self.user)
        self.mat = TaskCategory.objects.get(tappa="MATERIALI")

    def test_pagina_e_voce_di_menu(self):
        from core.models import NavigationItem

        pagina = self.client.get(reverse("tasks:cruscotto_commesse"))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "Commessa")
        self.assertEqual(NavigationItem.objects.get(code="tasks-sub-cruscotto").route_name, "tasks:cruscotto_commesse")

    def test_righe_ordinate_per_problemi(self):
        from .tests_utils import make_project

        tranquilla = make_project(name="Tranquilla", created_by=self.user)
        tranquilla.add_team_member("CC", self.user)
        Task.objects.create(title="Arrivo", project=self.project, created_by=self.user, category=self.mat,
                            due_date=timezone.localdate() - timedelta(days=2))
        righe = cruscotto(None, [tranquilla, self.project])
        self.assertEqual(righe[0]["project"], self.project)
        self.assertEqual(righe[0]["ritardo"], 1)

    def test_piano_e_scostamento(self):
        t = Task.objects.create(title="Arrivo", project=self.project, created_by=self.user, category=self.mat,
                                due_date=date(2026, 12, 1))
        GanttBaseline.objects.create(project=self.project, snapshot={str(t.pk): {"start": None, "end": "2026-11-26"}})
        dati = percorso(self.project, utente=self.user)
        riga = next(r for r in dati["righe"] if r["key"] == "MATERIALI")
        self.assertEqual((riga["delta_piano"], dati["ritardo_piano"], dati["ha_piano"]), (5, 5, True))

    def test_fissa_il_piano_torna_alla_panoramica(self):
        url = reverse("tasks:project_gantt_fix_baseline", args=[self.project.pk])
        nxt = reverse("tasks:project_overview", args=[self.project.pk])
        risposta = self.client.post(url, {"next": nxt})
        self.assertRedirects(risposta, nxt, fetch_redirect_response=False)
        self.assertTrue(GanttBaseline.objects.filter(project=self.project).exists())

    def test_filtri_le_mie(self):
        Task.objects.create(title="Arrivo", project=self.project, created_by=self.user, category=self.mat, assigned_to=self.user)
        riga = next(r for r in percorso(self.project, utente=self.user)["righe"] if r["key"] == "MATERIALI")
        self.assertTrue(riga["mie"])
        pagina = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))
        self.assertContains(pagina, 'data-tp-filtro="mie"')

    def test_durate_reali(self):
        m = ModelloCommessa.objects.create(nome="M", tappe=[{"tappa": "MATERIALI", "giorni": 30}])
        self.project.modello = m
        self.project.data_consegna = timezone.localdate() + timedelta(days=10)
        self.project.save()
        t = Task.objects.create(title="Arrivo", project=self.project, created_by=self.user, category=self.mat, status=TaskStatus.DONE)
        TaskEvent.objects.create(task=t, actor=self.user, type=TaskEventType.STATUS_CHANGE, payload={"from": "TODO", "to": "DONE"})
        self.assertEqual(durate_reali(m), {"MATERIALI": {"media": 10, "n": 1}})
        self.user.is_superuser = True
        self.user.save()
        self.client.post(reverse("tasks:impostazioni"), {"tab": "commesse", "modello_id": m.pk, "azione": "reali"})
        m.refresh_from_db()
        self.assertEqual(m.giorni_per("MATERIALI"), 10)
