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


class DigestSospensioneTests(TestCase):
    """Raccoglitore «Digest e promemoria»: pausa a tempo, che finisce da sola."""

    def setUp(self):
        self.admin = User.objects.create_superuser("dig_admin", "dig@x.local", "x")
        self.client.force_login(self.admin)
        self.url = reverse("admin_portale:automazioni_pianificati_action")

    def test_catalogo_digest_esiste_negli_schedule(self):
        from automazioni.schedules import DIGEST_E_PROMEMORIA

        nomi = {s["name"] for s in SCHEDULES}
        self.assertEqual(set(DIGEST_E_PROMEMORIA) - nomi, set())

    def test_sospendi_e_riprendi_un_digest(self):
        from datetime import timedelta

        from django.utils import timezone

        fino = timezone.localdate() + timedelta(days=3)
        r = self.client.post(self.url, {"name": "system_digest", "action": "sospendi", "fino": fino.isoformat()})
        self.assertEqual(r.status_code, 302)
        ctrl = ScheduleControl.objects.get(name="system_digest")
        self.assertEqual(ctrl.sospeso_fino, fino)
        self.assertTrue(ctrl.enabled)
        row = next(x for x in schedule_rows() if x["name"] == "system_digest")
        self.assertEqual(row["sospeso_fino"], fino)
        self.client.post(self.url, {"name": "system_digest", "action": "riprendi"})
        self.assertIsNone(ScheduleControl.objects.get(name="system_digest").sospeso_fino)

    def test_non_digest_e_date_fuori_limite_rifiutati(self):
        from datetime import timedelta

        from django.utils import timezone

        oggi = timezone.localdate()
        self.client.post(self.url, {"name": "automation_queue", "action": "sospendi", "fino": oggi.isoformat()})
        self.assertFalse(ScheduleControl.objects.filter(name="automation_queue").exists())
        for fino in (oggi - timedelta(days=1), oggi + timedelta(days=61)):
            self.client.post(self.url, {"name": "system_digest", "action": "sospendi", "fino": fino.isoformat()})
        self.assertFalse(ScheduleControl.objects.filter(name="system_digest", sospeso_fino__isnull=False).exists())

    def test_sospendi_tutti(self):
        from datetime import timedelta

        from django.utils import timezone

        from automazioni.schedules import DIGEST_E_PROMEMORIA

        fino = timezone.localdate() + timedelta(days=1)
        self.client.post(self.url, {"action": "sospendi_tutti", "fino": fino.isoformat()})
        self.assertEqual(ScheduleControl.objects.filter(sospeso_fino=fino).count(), len(DIGEST_E_PROMEMORIA))
        r = self.client.get(reverse("admin_portale:automazioni_pianificati"))
        self.assertContains(r, "In pausa fino al")
        self.client.post(self.url, {"action": "riprendi_tutti"})
        self.assertFalse(ScheduleControl.objects.filter(sospeso_fino__isnull=False).exists())

    def test_flusso_sospeso_salta_il_giro_e_poi_riparte(self):
        from datetime import timedelta
        from unittest import mock

        from django.utils import timezone

        from automazioni import managed_flows

        oggi = timezone.localdate()
        ScheduleControl.objects.create(name="system_digest", sospeso_fino=oggi)
        esito = managed_flows.run_managed_flow("system_digest")
        self.assertEqual(esito["reason"], "sospeso")
        # Il giorno dopo la data la pausa è finita: si arriva al flusso (qui finto).
        ScheduleControl.objects.filter(name="system_digest").update(sospeso_fino=oggi - timedelta(days=1))
        with mock.patch.object(managed_flows.ManagedFlow.objects, "select_for_update",
                               side_effect=RuntimeError("raggiunto")):
            with self.assertRaisesMessage(RuntimeError, "raggiunto"):
                managed_flows.run_managed_flow("system_digest")
        # «Esegui ora» ignora la pausa.
        ScheduleControl.objects.filter(name="system_digest").update(sospeso_fino=oggi)
        with mock.patch.object(managed_flows.ManagedFlow.objects, "select_for_update",
                               side_effect=RuntimeError("raggiunto")):
            with self.assertRaisesMessage(RuntimeError, "raggiunto"):
                managed_flows.run_managed_flow("system_digest", ignora_sospensione=True)
