"""Ciclo del SOC diviso: caselle mail in un lavoro a sé, letture esterne con tempo massimo."""
from __future__ import annotations

from unittest import mock

from django.test import TestCase

from automazioni.schedules import spec_by_name
from security import tasks


class CicloDivisoTests(TestCase):
    def test_caselle_hanno_il_loro_schedule(self):
        spec = spec_by_name("security_caselle")
        self.assertEqual(spec["func"], "security.tasks.run_security_caselle_task")
        self.assertEqual(spec["kwargs"]["q_options"]["timeout"], 300)
        with mock.patch("security.services.letture.esegui", return_value={"ok": True}) as esegui:
            tasks.run_security_caselle_task()
        esegui.assert_called_once_with("caselle")

    def test_il_ciclo_non_legge_piu_le_caselle(self):
        with mock.patch("security.services.letture.esegui", return_value={"ok": True}) as esegui:
            esito = tasks.run_security_cycle_task()
        letture = [c.args[0] for c in esegui.call_args_list]
        self.assertNotIn("caselle", letture)
        self.assertIn("defender_alert", letture)
        self.assertNotIn("mailboxes", esito)
        self.assertIn("kpis", esito)

    def test_letture_rimandate_oltre_il_tempo_ma_passi_interni_sempre(self):
        orologio = iter([0.0] + [1000.0] * 200)
        with mock.patch("security.services.letture.esegui", return_value={"ok": True}) as esegui, \
                mock.patch("time.monotonic", side_effect=lambda: next(orologio)):
            esito = tasks.run_security_cycle_task()
        esegui.assert_not_called()
        for nome in tasks.LETTURE_DEL_CICLO:
            self.assertIn("rimandata al prossimo giro", esito[nome])
        self.assertNotIn("rimandata", str(esito["rules"]))
        self.assertIn("kpis", esito)
        self.assertIn("avvisi", esito)
