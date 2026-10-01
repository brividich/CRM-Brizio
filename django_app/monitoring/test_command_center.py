"""Comando `command_center` usato dal Server Dashboard del Setup Wizard."""
from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from django_q.models import Task

from monitoring.management.commands import command_center as cc


def _status(*args) -> dict:
    out = StringIO()
    call_command("command_center", "status", *args, stdout=out)
    line = next(ln for ln in out.getvalue().splitlines() if ln.startswith(cc.JSON_MARKER))
    return json.loads(line[len(cc.JSON_MARKER):])


class CommandCenterStatusTests(TestCase):
    def test_status_ha_tutte_le_sezioni(self):
        data = _status("--skip=readyz")
        for key in ("build", "migrations", "qcluster", "schedules", "failures", "automations"):
            self.assertIn(key, data)
            self.assertNotIn("error", data[key], key)
        self.assertNotIn("readyz", data)
        self.assertEqual(data["migrations"]["count"], 0)
        names = {r["name"] for r in data["schedules"]["rows"]}
        self.assertIn("import_cedolini_sharepoint", names)

    def test_qcluster_e_errori_recenti(self):
        now = timezone.now()
        Task.objects.create(id="a" * 32, name="ok", func="x.ok", started=now - timedelta(minutes=3),
                            stopped=now - timedelta(minutes=2), success=True)
        Task.objects.create(id="b" * 32, name="ko", func="x.ko", started=now - timedelta(minutes=6),
                            stopped=now - timedelta(minutes=5), success=False, result="Boom sintetico")
        data = _status("--skip=readyz")
        self.assertEqual(data["qcluster"]["ok_24h"], 1)
        self.assertEqual(data["qcluster"]["failed_24h"], 1)
        self.assertEqual(data["qcluster"]["last_ok"]["func"], "x.ok")
        self.assertEqual(data["failures"]["rows"][0]["result"], "Boom sintetico")

    def test_sezione_rotta_non_oscura_le_altre(self):
        with mock.patch.dict(cc.SECTIONS, {"migrations": mock.Mock(side_effect=RuntimeError("db giù"))}):
            data = _status("--skip=readyz")
        self.assertEqual(data["migrations"]["error"], "RuntimeError: db giù")
        self.assertNotIn("error", data["schedules"])


class CommandCenterRunTests(TestCase):
    def test_run_schedule_sconosciuto(self):
        with self.assertRaises(CommandError):
            call_command("command_center", "run", "non_esiste", stdout=StringIO())

    def test_run_senza_nome(self):
        with self.assertRaises(CommandError):
            call_command("command_center", "run", stdout=StringIO())

    def test_run_esegue_la_funzione_dello_schedule(self):
        out = StringIO()
        call_command("command_center", "run", "import_cedolini_sharepoint", stdout=out)
        self.assertIn("non configurato", out.getvalue())
        self.assertIn("completato", out.getvalue())

    def test_run_ok_false_e_un_errore(self):
        with mock.patch("anagrafica.tasks.run_import_cedolini_sharepoint", return_value={"ok": False}):
            with self.assertRaises(CommandError):
                call_command("command_center", "run", "import_cedolini_sharepoint", stdout=StringIO())


class CommandCenterPostDeployTests(TestCase):
    def _fake_readyz(self, status="ok", critical=False):
        return {"status": status, "checks": [
            {"name": "db_default", "status": status, "latency_ms": 1, "critical": critical, "message": ""},
        ]}

    def test_post_deploy_ok_registra_gli_schedule(self):
        out = StringIO()
        with mock.patch.object(cc, "section_readyz", return_value=self._fake_readyz()), \
                mock.patch.object(cc, "call_command", wraps=call_command) as cmd:
            call_command("command_center", "post-deploy", stdout=out)
        chiamati = [c.args[0] for c in cmd.call_args_list]
        self.assertIn("setup_q_schedules", chiamati)
        self.assertIn("Verifica post-deploy OK", out.getvalue())

    def test_post_deploy_fallisce_con_migrazioni_pendenti(self):
        with mock.patch.object(cc, "section_readyz", return_value=self._fake_readyz()), \
                mock.patch.object(cc, "section_migrations", return_value={"pending": ["x.0001"], "count": 1}):
            with self.assertRaisesMessage(CommandError, "migrazioni non applicate"):
                call_command("command_center", "post-deploy", stdout=StringIO())

    def test_post_deploy_fallisce_con_check_critico_ko(self):
        with mock.patch.object(cc, "section_readyz", return_value=self._fake_readyz("fail", critical=True)):
            with self.assertRaisesMessage(CommandError, "readyz db_default"):
                call_command("command_center", "post-deploy", stdout=StringIO())
