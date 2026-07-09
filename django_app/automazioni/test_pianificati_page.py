"""Pagina 'Task pianificati' nell'area automazioni: riflette gli schedule django-q
con on/off durevole (ScheduleControl) ed 'esegui ora'.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from automazioni.schedules import SCHEDULES, describe_cadence, schedule_rows
from monitoring.models import ScheduleControl

User = get_user_model()


class SchedulePresentationTests(TestCase):
    def test_describe_cadence(self):
        self.assertIn("07:45", describe_cadence({"schedule_type": "C", "cron": "45 7 * * *"}))
        self.assertEqual(describe_cadence({"schedule_type": "I", "minutes": 1}), "ogni minuto")
        self.assertEqual(describe_cadence({"schedule_type": "I", "minutes": 5}), "ogni 5 minuti")

    def test_schedule_rows_copre_ogni_schedule(self):
        rows = schedule_rows()
        self.assertEqual(len(rows), len(SCHEDULES))
        names = {r["name"] for r in rows}
        for spec in SCHEDULES:
            self.assertIn(spec["name"], names)
        # descrizione presente per le voci commentate
        with_desc = [r for r in rows if r["description"]]
        self.assertTrue(with_desc)


class PianificatiPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("pian_admin", "pian@x.local", "x")
        self.client.force_login(self.admin)

    def test_pagina_elenca_i_task(self):
        r = self.client.get(reverse("admin_portale:automazioni_pianificati"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "visite_expiry_reminders")
        self.assertContains(r, "Task pianificati")

    def test_toggle_disattiva_durevole(self):
        name = SCHEDULES[0]["name"]
        r = self.client.post(
            reverse("admin_portale:automazioni_pianificati_action"),
            {"name": name, "action": "toggle"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ScheduleControl.objects.get(name=name).enabled)
        # secondo toggle → riattiva
        self.client.post(
            reverse("admin_portale:automazioni_pianificati_action"),
            {"name": name, "action": "toggle"},
        )
        self.assertTrue(ScheduleControl.objects.get(name=name).enabled)

    def test_toggle_nome_sconosciuto(self):
        r = self.client.post(
            reverse("admin_portale:automazioni_pianificati_action"),
            {"name": "non-esiste", "action": "toggle"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ScheduleControl.objects.filter(name="non-esiste").exists())
