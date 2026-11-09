"""Menu «⋯» delle azioni rapide sugli incarichi (10/11/2026)."""
from __future__ import annotations

from datetime import date

from django.urls import reverse

from .models import TaskComment, TaskPriority, TaskSpostamento, TaskStatus
from .tests_spostamenti import SpostamentiBase


class AzioniRapideTests(SpostamentiBase):
    def url(self):
        return reverse("tasks:task_azione_rapida", args=[self.task.pk])

    def test_permessi_capocommessa_e_incaricato(self):
        self.client.force_login(self.cc)
        p = self.client.get(self.url()).json()["permessi"]
        self.assertTrue(all([p["date"], p["date_subito"], p["responsabile"], p["priorita"], p["annulla"]]))
        self.client.force_login(self.inc)
        p = self.client.get(self.url()).json()["permessi"]
        self.assertTrue(p["date"])
        self.assertFalse(p["date_subito"] or p["responsabile"] or p["annulla"])

    def test_capocommessa_sposta_cambia_priorita_e_responsabile(self):
        self.client.force_login(self.cc)
        self.client.post(self.url(), {"azione": "date", "inizio": "2026-12-02", "fine": "2026-12-08"})
        self.client.post(self.url(), {"azione": "priorita", "priorita": TaskPriority.HIGH})
        self.client.post(self.url(), {"azione": "responsabile", "responsabile": str(self.altro.pk)})
        self.task.refresh_from_db()
        self.assertEqual((self.task.due_date, self.task.priority, self.task.assigned_to), (date(2026, 12, 8), TaskPriority.HIGH, self.altro))

    def test_incaricato_chiede_lo_spostamento(self):
        self.client.force_login(self.inc)
        risposta = self.client.post(self.url(), {"azione": "date", "inizio": "2026-12-01", "fine": "2026-12-15", "motivo": "Utensile in arrivo"}).json()
        self.assertIn("Richiesta", risposta["messaggio"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 12, 5))
        self.assertEqual(TaskSpostamento.objects.get().motivo, "Utensile in arrivo")

    def test_incaricato_non_annulla_ne_cambia_responsabile(self):
        self.client.force_login(self.inc)
        self.assertEqual(self.client.post(self.url(), {"azione": "annulla", "motivo": "x"}).status_code, 403)
        self.assertEqual(self.client.post(self.url(), {"azione": "responsabile", "responsabile": str(self.altro.pk)}).status_code, 403)

    def test_annulla_chiede_motivo_e_lo_registra(self):
        self.client.force_login(self.cc)
        self.assertEqual(self.client.post(self.url(), {"azione": "annulla"}).status_code, 400)
        self.client.post(self.url(), {"azione": "annulla", "motivo": "Cliente ha sospeso"})
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.CANCELED)
        self.assertTrue(TaskComment.objects.filter(task=self.task, body__contains="Cliente ha sospeso").exists())
        self.client.post(self.url(), {"azione": "riapri"})
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.TODO)

    def test_bottone_nelle_pagine(self):
        self.client.force_login(self.inc)
        self.assertContains(self.client.get(reverse("tasks:mie_azioni")), f'data-ar-task="{self.task.pk}"')

    def test_rotta_con_binding(self):
        from core.models import RoutePermissionBinding

        from .acl_bootstrap import bootstrap_tasks_acl_endpoints

        bootstrap_tasks_acl_endpoints(force=True)
        self.assertTrue(RoutePermissionBinding.objects.filter(route_name="tasks:task_azione_rapida").exists())
