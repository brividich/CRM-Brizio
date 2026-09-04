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
    ("assets.tasks", "run_generate_maintenance_occurrences", "generate_maintenance_occurrences",
     "assets_generate_occurrences", "assets.tasks.run_generate_maintenance_occurrences"),
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


class IntakeScansioniScheduleTest(SimpleTestCase):
    """L'acquisizione dei fogli firme dev'essere agganciata allo scheduler.

    Senza registrazione in ``automazioni.schedules`` il meccanismo esisterebbe
    ma non girerebbe mai, e nessuno se ne accorgerebbe: la cartella resterebbe
    piena e il portale vuoto.
    """

    def test_lo_schedule_e_registrato(self):
        spec = spec_by_name("intake_scansioni_formazione")
        self.assertIsNotNone(spec, "schedule non registrata: setup_q_schedules non la attiverebbe")
        self.assertEqual(spec["func"], "anagrafica.tasks.run_intake_scansioni_formazione")

    def test_la_cadenza_e_in_minuti(self):
        """django-q2 non supporta i SECONDI: con "S" il cluster va in crash."""
        spec = spec_by_name("intake_scansioni_formazione")
        self.assertEqual(spec["schedule_type"], "I")
        self.assertEqual(spec["minutes"], 2)

    def test_il_wrapper_esiste_ed_e_fail_safe(self):
        from anagrafica import tasks

        with mock.patch("anagrafica.services.intake_scansioni.elabora_cartella",
                        side_effect=RuntimeError("share sparita")):
            esito = tasks.run_intake_scansioni_formazione()

        self.assertFalse(esito["ok"], "un guasto non deve propagarsi al cluster")


class RetiredSchedulesTests(SimpleTestCase):
    """Uno schedule tolto dal codice sopravvive nel DB: va ritirato esplicitamente."""

    def test_il_generatore_di_odl_e_ritirato_non_solo_rimosso(self):
        from automazioni.schedules import RETIRED_SCHEDULE_NAMES

        self.assertIsNone(spec_by_name("assets_generate_workorders"))
        self.assertIn("assets_generate_workorders", RETIRED_SCHEDULE_NAMES)

    def test_nessun_nome_ritirato_e_anche_attivo(self):
        from automazioni.schedules import RETIRED_SCHEDULE_NAMES

        for name in RETIRED_SCHEDULE_NAMES:
            self.assertIsNone(spec_by_name(name), f"{name} e' insieme attivo e ritirato")
