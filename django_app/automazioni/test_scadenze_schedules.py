"""Aggancio allo scheduler (django-q) dei reminder/alert scadenze cross-modulo.

Copre i comandi di scadenza/alert/promemoria PRONTI di assets, dpi, rentri e
tickets: verifica che il wrapper task esista, sia fail-safe (chiama il management
command) e che lo schedule sia registrato in ``automazioni.schedules`` (così
``setup_q_schedules`` lo attiva e la Centrale di comando lo gestisce).
"""
from __future__ import annotations

import importlib
import unittest.mock as mock

from django.test import SimpleTestCase

from automazioni.schedules import spec_by_name

# (modulo tasks, nome wrapper, nome management command, nome schedule, func path)
_MATRIX = [
    ("assets.tasks", "run_generate_scheduled_workorders", "generate_scheduled_workorders",
     "assets_generate_workorders", "assets.tasks.run_generate_scheduled_workorders"),
    ("assets.tasks", "run_maintenance_reminders", "send_maintenance_reminders",
     "assets_maintenance_reminders", "assets.tasks.run_maintenance_reminders"),
    ("dpi.tasks", "run_dpi_expiry_reminders", "send_dpi_expiry_reminders",
     "dpi_expiry_reminders", "dpi.tasks.run_dpi_expiry_reminders"),
    ("rentri.tasks", "run_rentri_scadenze_check", "check_rentri_scadenze",
     "rentri_scadenze_check", "rentri.tasks.run_rentri_scadenze_check"),
    ("tickets.tasks", "run_sla_reminders", "send_sla_reminders",
     "tickets_sla_reminders", "tickets.tasks.run_sla_reminders"),
    ("tickets.tasks", "run_ticket_daily_digest", "send_ticket_daily_digest",
     "tickets_daily_digest", "tickets.tasks.run_ticket_daily_digest"),
    ("core.tasks", "run_caporeparto_morning_digest", "send_caporeparto_morning_digest",
     "caporeparto_morning_digest", "core.tasks.run_caporeparto_morning_digest"),
]


class ScadenzeTaskWrappersTests(SimpleTestCase):
    def test_i_wrapper_chiamano_il_management_command_e_sono_failsafe(self):
        for mod_name, wrapper_name, command_name, _sched, _func in _MATRIX:
            module = importlib.import_module(mod_name)
            wrapper = getattr(module, wrapper_name)
            with mock.patch("django.core.management.call_command") as cc:
                res = wrapper()
            cc.assert_called_once()
            self.assertEqual(cc.call_args.args[0], command_name, wrapper_name)
            self.assertTrue(res.get("ok"), wrapper_name)


class ScadenzeScheduleRegistrationTests(SimpleTestCase):
    def test_schedule_registrati_in_automazioni(self):
        for _mod, _wrapper, _cmd, sched_name, func in _MATRIX:
            spec = spec_by_name(sched_name)
            self.assertIsNotNone(spec, f"schedule mancante: {sched_name}")
            self.assertEqual(spec["func"], func, sched_name)
            self.assertIn(spec["schedule_type"], ("C", "I"), sched_name)
            self.assertEqual(spec.get("repeats", -1), -1, sched_name)
