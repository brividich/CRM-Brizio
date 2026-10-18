"""Pagina «Backup e ripristino», check di salute, alert e ripristino in-app disattivato (BUILD_SPEC R2)."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.backup_engine import config as cfgmod
from core.backup_engine import engine
from monitoring import health


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "media").mkdir()
        self.ovr = override_settings(BACKUP_TARGET=str(self.tmp / "target"), BACKUP_STAGING_DIR=str(self.tmp / "staging"),
                                     BACKUP_ENV_NAME="prova", LOG_DIR=self.tmp, MEDIA_ROOT=self.tmp / "media",
                                     BACKUP_ENV_DIR="", READYZ_TTL_SECONDS=0)
        self.ovr.enable()
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="bk_admin", email="bk@example.test", password="x")
        self.user = User.objects.create_user(username="bk_user", email="bku@example.test", password="x")

    def tearDown(self):
        self.ovr.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)


class BackupPageTests(_Base):
    def test_acl_anonimo_utente_admin(self):
        url = reverse("monitoring_admin:backup_status")
        resp = Client().get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
        c = Client()
        c.force_login(self.user)
        denied = c.get(url)
        # utente senza ruolo admin: negato (403 dal decoratore o redirect del middleware ACL), mai la pagina
        self.assertIn(denied.status_code, (302, 403), denied.get("Location"))
        self.assertNotContains(denied, "RPO attuale", status_code=denied.status_code)
        if denied.status_code == 302:
            self.assertNotIn("/backup/", denied["Location"])
        c.force_login(self.admin)
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "RPO attuale")
        self.assertContains(resp, "Recovery Kit")
        self.assertNotContains(resp, "Ripristina</button>")

    def test_con_backup_mostra_set_e_dettaglio(self):
        cfg = cfgmod.load_config()
        res = engine.run_full(cfg)
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("monitoring_admin:backup_status"))
        self.assertContains(resp, res.set_id)
        resp = c.get(reverse("monitoring_admin:backup_set_detail", args=[res.set_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "SHA-256")
        self.assertEqual(c.get(reverse("monitoring_admin:backup_set_detail", args=["nonvalido"])).status_code, 404)

    def test_verifica_accodata(self):
        c = Client()
        c.force_login(self.admin)
        with mock.patch("django_q.tasks.async_task") as task:
            resp = c.post(reverse("monitoring_admin:backup_verify"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(task.call_args.args[0], "core.backup_engine.tasks.verify_task")

    def test_piano_di_ripristino_scaricabile(self):
        engine.run_full(cfgmod.load_config())
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("monitoring_admin:backup_restore_plan"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        plan = json.loads(resp.content)
        self.assertIn("full_set_id", plan)
        self.assertNotIn(str(self.tmp), resp.content.decode())    # solo percorsi relativi


class HealthBackupTests(_Base):
    def test_check_registrati_e_mai_critical(self):
        for name in ("backup_full", "backup_log", "restore_drill", "recovery_kit", "db_capacity"):
            self.assertIn(name, health.available_checks())
        results = {c.name: c for c in health.run_backup_checks()}
        self.assertEqual(results["backup_full"].status, health.STATUS_FAIL)   # nessun backup
        self.assertFalse(any(c.critical for c in results.values()))
        engine.run_full(cfgmod.load_config())
        self.assertEqual(health.check_backup_full().status, health.STATUS_OK)

    def test_payload_pubblico_senza_percorsi(self):
        report = health.run_readyz_checks()
        text = json.dumps(report.to_public_payload())
        self.assertNotIn(str(self.tmp), text)
        self.assertNotIn("message", text)
        self.assertIn("backup_full", text)

    def test_alert_email_solo_per_i_critici(self):
        from monitoring.models import Issue

        with mock.patch.object(health, "emit_monitoring_alert", return_value=True) as emit:
            payload = health.run_backup_health_alert()
        self.assertTrue(payload["emailed"])
        self.assertIn("backup_full", emit.call_args.kwargs["subject"])
        self.assertTrue(Issue.objects.filter(title__startswith="Backup · backup_full").exists())
        engine.run_full(cfgmod.load_config())
        with mock.patch.object(health, "emit_monitoring_alert") as emit, \
                mock.patch.object(health, "check_restore_drill",
                                  return_value=health.CheckResult("restore_drill", health.STATUS_WARN, 0)), \
                mock.patch.object(health, "check_recovery_kit",
                                  return_value=health.CheckResult("recovery_kit", health.STATUS_WARN, 0)):
            payload = health.run_backup_health_alert()
        emit.assert_not_called()

    def test_alert_ai_non_include_i_check_di_backup(self):
        with mock.patch.object(health, "run_ai_checks", return_value=[]), \
                mock.patch.object(health, "emit_monitoring_alert", return_value=False), \
                mock.patch.object(health, "_sync_check_issues"):
            payload = health.run_ai_readiness_alert(include_services=True)
        names = {c["name"] for c in payload["checks"]}
        self.assertFalse(names & health.BACKUP_CHECK_NAMES)
