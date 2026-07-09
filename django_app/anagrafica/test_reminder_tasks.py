"""Aggancio alle automazioni (django-q) dei reminder/digest anagrafica.

Verifica che i wrapper task esistano, siano fail-safe (chiamano il management
command) e che gli schedule siano registrati in ``automazioni.schedules`` (così
``setup_q_schedules`` li attiva al deploy e la Centrale di comando li gestisce).
"""
from __future__ import annotations

import unittest.mock as mock

from django.test import SimpleTestCase

from anagrafica import tasks as anag_tasks
from automazioni.schedules import spec_by_name

# (nome task wrapper, nome management command, nome schedule, func path)
_MATRIX = [
    ("run_visite_expiry_reminders", "send_visite_expiry_reminders",
     "visite_expiry_reminders", "anagrafica.tasks.run_visite_expiry_reminders"),
    ("run_contratti_expiry_reminders", "send_contratti_expiry_reminders",
     "contratti_expiry_reminders", "anagrafica.tasks.run_contratti_expiry_reminders"),
    ("run_formazione_audit_digest", "send_formazione_audit_digest",
     "formazione_audit_digest", "anagrafica.tasks.run_formazione_audit_digest"),
    ("run_visite_mediche_digest", "send_visite_mediche_digest",
     "visite_mediche_digest", "anagrafica.tasks.run_visite_mediche_digest"),
    ("run_training_expiry_reminders", "send_training_expiry_reminders",
     "training_expiry_reminders", "anagrafica.tasks.run_training_expiry_reminders"),
    ("run_elearning_reminders", "send_elearning_reminders",
     "elearning_reminders", "anagrafica.tasks.run_elearning_reminders"),
]


class ReminderTaskWrappersTests(SimpleTestCase):
    def test_i_wrapper_chiamano_il_management_command_e_sono_failsafe(self):
        for wrapper_name, command_name, _sched, _func in _MATRIX:
            wrapper = getattr(anag_tasks, wrapper_name)
            with mock.patch("django.core.management.call_command") as cc:
                res = wrapper()
            cc.assert_called_once()
            self.assertEqual(cc.call_args.args[0], command_name, wrapper_name)
            self.assertTrue(res.get("ok"), wrapper_name)


class ScheduleRegistrationTests(SimpleTestCase):
    def test_schedule_registrati_in_automazioni(self):
        for _wrapper, _cmd, sched_name, func in _MATRIX:
            spec = spec_by_name(sched_name)
            self.assertIsNotNone(spec, f"schedule mancante: {sched_name}")
            self.assertEqual(spec["func"], func, sched_name)
            self.assertIn(spec["schedule_type"], ("C", "I"), sched_name)
            # repeats infinito (job ricorrente)
            self.assertEqual(spec.get("repeats", -1), -1, sched_name)
