"""Piano di ripristino e prova di ripristino automatica (BUILD_SPEC R2/R3)."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core.backup_engine import config as cfgmod
from core.backup_engine import doctor, drill, engine
from core.backup_engine.restore_plan import PlanError, build_plan
from core.backup_engine.sqlserver import SqlServer

SEP = "\x1f"


def _write_set(root: Path, set_id: str, data: dict) -> None:
    d = root / set_id
    d.mkdir(parents=True)
    base = {"schema_version": 1, "set_id": set_id, "type": set_id.rsplit("_", 1)[1], "env": "prova",
            "status": "ok", "app": {"version": "1.6.2", "commit": "abc", "migrations": {"core": "0090_x"}},
            "keys": {"document_encryption_key_sha256": "k" * 64, "secret_key_sha256": "s" * 64},
            "artifacts": [], "warnings": [], "duration_s": 1}
    base.update(data)
    (d / "manifest.json").write_text(json.dumps(base), encoding="utf-8")


def _full(root, sid, last_lsn=100):
    _write_set(root, sid, {"artifacts": [{"path": "db/DB_FULL.bak", "sha256": "a" * 64, "size": 10, "kind": "full",
                                          "database": "DB", "verify_status": "ok", "lsn": {"first": 50, "last": last_lsn}}],
                           "row_counts": {"utenti": 10}, "databases": [{"name": "DB", "allocated_mb": 500}]})


def _log(root, sid, full_sid, first, last):
    _write_set(root, sid, {"artifacts": [{"path": "db/DB_LOG.trn", "sha256": "b" * 64, "size": 1, "kind": "log",
                                          "database": "DB", "verify_status": "ok"}],
                           "chain": {"full_set_id": full_sid,
                                     "databases": {"DB": {"first_lsn": str(first), "last_lsn": str(last)}}}})


class RestorePlanTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        _full(self.root, "20261016_020000_full", last_lsn=100)
        _log(self.root, "20261016_090500_log", "20261016_020000_full", 90, 200)
        _log(self.root, "20261016_100500_log", "20261016_020000_full", 200, 300)
        _log(self.root, "20261016_110500_log", "20261016_020000_full", 300, 400)
        _write_set(self.root, "20261016_023000_files", {})
        _write_set(self.root, "20261016_030000_host", {"release_ref": "_releases/portale-novicrom-v1.6.2-x.zip"})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_stopat_fra_due_log(self):
        plan = build_plan(self.root, datetime(2026, 10, 16, 10, 30))
        self.assertEqual(plan["full_set_id"], "20261016_020000_full")
        self.assertEqual([l["set_id"] for l in plan["databases"]["DB"]["logs"]],
                         ["20261016_090500_log", "20261016_100500_log", "20261016_110500_log"])
        self.assertEqual(plan["stopat"], "2026-10-16T10:30:00")
        self.assertEqual(plan["release"]["zip"], "_releases/portale-novicrom-v1.6.2-x.zip")
        self.assertEqual(plan["expected_keys"]["document_encryption_key_sha256"], "k" * 64)
        self.assertEqual(plan["files_set_id"], "20261016_023000_files")

    def test_punto_piu_recente(self):
        plan = build_plan(self.root)
        self.assertIsNone(plan["stopat"])
        self.assertEqual(plan["last_log_set_id"], "20261016_110500_log")

    def test_buco_nella_catena(self):
        _log(self.root, "20261016_120500_log", "20261016_020000_full", 450, 500)
        with self.assertRaises(PlanError):
            build_plan(self.root)

    def test_primo_log_non_copre_il_full(self):
        shutil.rmtree(self.root / "20261016_090500_log")
        with self.assertRaises(PlanError):
            build_plan(self.root, datetime(2026, 10, 16, 10, 30))

    def test_nessun_full_prima_del_punto(self):
        with self.assertRaises(PlanError):
            build_plan(self.root, datetime(2026, 10, 15, 12, 0))

    def test_oltre_l_ultimo_log_avvisa(self):
        plan = build_plan(self.root, datetime(2026, 10, 16, 18, 0))
        self.assertIsNone(plan["stopat"])
        self.assertTrue(any("oltre l'ultimo log" in w for w in plan["warnings"]))


def _proc(stdout="", rc=0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr="")


class _Runner:
    def __init__(self, fail_on=None):
        self.sql = []
        self.fail_on = fail_on

    def __call__(self, args, timeout, env):
        q = args[-1]
        self.sql.append(q)
        if self.fail_on and self.fail_on in q:
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Msg 8939, Level 16\nerrore simulato")
        if "FILELISTONLY" in q:
            return _proc(SEP.join(["LogicalName", "PhysicalName", "Type", "Size"]) + "\n----\n"
                         + SEP.join(["DB", r"C:\x\DB.mdf", "D", "1"]) + "\n" + SEP.join(["DB_log", r"C:\x\DB.ldf", "L", "1"]) + "\n")
        if "django_migrations" in q:
            return _proc("core\x1f0090_x\n")
        if "dm_db_partition_stats" in q:
            return _proc("utenti\x1f10\n")
        return _proc("")


class DrillSqlServerSimulatoTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        target = self.tmp / "target"
        root = target / "prova"
        _full(root, "20261016_020000_full")
        _log(root, "20261016_090500_log", "20261016_020000_full", 90, 200)
        for sid, name in (("20261016_020000_full", "DB_FULL.bak"), ("20261016_090500_log", "DB_LOG.trn")):
            p = root / sid / "db" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        self.ovr = override_settings(BACKUP_TARGET=str(target), BACKUP_STAGING_DIR=str(self.tmp / "staging"),
                                     BACKUP_ENV_NAME="prova", LOG_DIR=self.tmp)
        self.ovr.enable()
        self.cfg = cfgmod.load_config()
        self.conn = mock.MagicMock(vendor="microsoft", settings_dict={"NAME": "DB"})

    def tearDown(self):
        self.ovr.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, runner):
        with mock.patch.object(drill, "connection", self.conn), \
                mock.patch.object(drill, "copy_verified", lambda src, dst, expected_sha256=None: shutil.copy(src, dst)):
            return drill.run_drill(self.cfg, sql=SqlServer(host="h", runner=runner), samples=0, record=True)

    def test_sequenza_restore_e_drop(self):
        from monitoring.models import RestoreDrill

        r = _Runner()
        res = self._run(r)
        self.assertEqual(res["status"], "warning", res)       # nessun backup file → avviso
        joined = "\n".join(r.sql)
        self.assertIn("RESTORE DATABASE [DB_drill]", joined)
        self.assertIn("NORECOVERY, CHECKSUM", joined)
        self.assertIn("RESTORE LOG [DB_drill]", joined)
        self.assertIn("RESTORE DATABASE [DB_drill] WITH RECOVERY", joined)
        self.assertIn("DBCC CHECKDB ([DB_drill])", joined)
        self.assertNotIn("REPLACE", joined)
        self.assertIn("DROP DATABASE [DB_drill]", r.sql[-1])
        self.assertEqual(res["checks"]["migrations"]["status"], "ok")
        self.assertEqual(res["checks"]["row_counts"]["status"], "ok")
        self.assertTrue(RestoreDrill.objects.filter(full_set_id="20261016_020000_full").exists())

    def test_keep_lascia_la_copia_per_il_recupero_selettivo(self):
        r = _Runner()
        with mock.patch.object(drill, "connection", self.conn), \
                mock.patch.object(drill, "copy_verified", lambda src, dst, expected_sha256=None: shutil.copy(src, dst)):
            res = drill.run_drill(self.cfg, sql=SqlServer(host="h", runner=r), samples=0, record=False, keep=True)
        self.assertEqual(res["kept_databases"], ["DB_drill"])
        self.assertFalse(any("DROP DATABASE" in q for q in r.sql))

    def test_drop_anche_su_errore(self):
        r = _Runner(fail_on="DBCC CHECKDB")
        res = self._run(r)
        self.assertEqual(res["status"], "failed")
        self.assertIn("DROP DATABASE [DB_drill]", r.sql[-1])

    def test_spazio_insufficiente_non_parte(self):
        r = _Runner()
        with mock.patch.object(drill, "_free_mb", return_value=1):
            res = self._run(r)
        self.assertEqual(res["status"], "warning")
        self.assertIn("Spazio insufficiente", res["error"])
        self.assertFalse(any("RESTORE" in q for q in r.sql))

    def test_nome_senza_suffisso_rifiutato(self):
        with mock.patch.object(drill, "SUFFIX", "_drill"):
            self.assertTrue(drill.drill_name("X").endswith("_drill"))


class DrillSqliteEndToEndTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.key = Fernet.generate_key().decode()
        self.priv = self.tmp / "priv"
        self.priv.mkdir()
        self.media = self.tmp / "media"
        self.media.mkdir()
        self.ovr = override_settings(
            BACKUP_TARGET=str(self.tmp / "target"), BACKUP_STAGING_DIR=str(self.tmp / "staging"), BACKUP_ENV_NAME="prova",
            LOG_DIR=self.tmp, MEDIA_ROOT=self.media, DOCUMENT_ENCRYPTION_KEY=self.key, BACKUP_ENV_DIR="",
            BACKUP_DRILL_TABLES=["django_migrations"],
            TIMBRI_PRIVATE_ROOT=self.priv, TICKETS_PRIVATE_ROOT=self.priv, ASSETS_PRIVATE_ROOT=self.priv,
            DIARIO_PREPOSTO_PRIVATE_ROOT=self.priv, ANAGRAFICA_PRIVATE_ROOT=self.priv, HUB_BACHECA_PRIVATE_ROOT=self.priv,
            PRIVATE_ATTACHMENTS_ROOT=self.priv, GESTIONE_SPECIFICHE_PRIVATE_ROOT=self.priv,
            SCHEDE_SICUREZZA_PRIVATE_ROOT=self.priv, TASKS_PRIVATE_ROOT=self.priv,
        )
        self.ovr.enable()
        from core import encrypted_storage

        encrypted_storage._get_fernet.cache_clear() if hasattr(encrypted_storage._get_fernet, "cache_clear") else None
        (self.priv / "referto.enc").write_bytes(encrypted_storage.encrypt_bytes(b"referto sintetico"))
        self.cfg = cfgmod.load_config()

    def tearDown(self):
        self.ovr.disable()
        from core import encrypted_storage

        encrypted_storage._get_fernet.cache_clear() if hasattr(encrypted_storage._get_fernet, "cache_clear") else None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_drill_completo(self):
        self.assertEqual(engine.run_full(self.cfg).status, "ok")
        self.assertEqual(engine.run_files(self.cfg).status, "ok")
        res = drill.run_drill(self.cfg, samples=5, seed=1)
        self.assertEqual(res["checks"]["checkdb"]["status"], "ok")
        self.assertEqual(res["checks"]["migrations"]["status"], "ok", res["checks"]["migrations"])
        self.assertEqual(res["checks"]["row_counts"]["status"], "ok", res["checks"]["row_counts"])
        roots = res["checks"]["decrypt"]["roots"]
        self.assertEqual(sum(r["decrypted"] for r in roots.values()), 1)
        self.assertEqual(res["checks"]["decrypt"]["status"], "ok")
        self.assertIsNotNone(res["rto_seconds"])
        self.assertFalse((self.cfg.staging / "prova" / "drill").exists())
        self.assertEqual(doctor.drill_check()["level"], "ok")

    def test_chiave_sbagliata_rilevata(self):
        engine.run_full(self.cfg)
        engine.run_files(self.cfg)
        from core import encrypted_storage

        with override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            encrypted_storage._get_fernet.cache_clear() if hasattr(encrypted_storage._get_fernet, "cache_clear") else None
            res = drill.run_drill(self.cfg, samples=5, seed=1, record=False)
        self.assertEqual(res["checks"]["decrypt"]["status"], "failed")
        self.assertEqual(res["status"], "failed")


class HealthChecksTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ovr = override_settings(BACKUP_TARGET=str(self.tmp / "t"), BACKUP_ENV_NAME="prova", LOG_DIR=self.tmp,
                                     BASE_DIR=self.tmp / "app")
        self.ovr.enable()
        (self.tmp / "app").mkdir()
        self.cfg = cfgmod.load_config()

    def tearDown(self):
        self.ovr.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_soglie_drill(self):
        from monitoring.models import RestoreDrill

        self.assertEqual(doctor.drill_check()["level"], "warning")
        now = timezone.now()
        d = RestoreDrill.objects.create(env="prova", status="ok", started_at=now - timedelta(days=3), rto_seconds=60)
        self.assertEqual(doctor.drill_check(now)["level"], "ok")
        self.assertEqual(doctor.drill_check(now + timedelta(days=10))["level"], "warning")
        self.assertEqual(doctor.drill_check(now + timedelta(days=40))["level"], "critical")
        RestoreDrill.objects.create(env="prova", status="failed", started_at=now, error="boom")
        self.assertEqual(doctor.drill_check(now)["level"], "warning")
        self.assertTrue(d.pk)

    def test_recovery_kit(self):
        from core.backup_engine import manifest as mf

        self.assertEqual(doctor.recovery_kit_check(self.cfg)["level"], "warning")
        keys = mf.keys_section()
        (self.tmp / "app" / ".env").write_text("A=1\n", encoding="utf-8")
        state = {"exported_at": timezone.now().isoformat(), "env_sha256": doctor.env_file_sha256(), **{
            k: keys[k] for k in ("document_encryption_key_sha256", "secret_key_sha256")}}
        (self.tmp / doctor.RECOVERY_KIT_STATUS).write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(doctor.recovery_kit_check(self.cfg)["level"], "ok")
        (self.tmp / "app" / ".env").write_text("A=2\n", encoding="utf-8")
        c = doctor.recovery_kit_check(self.cfg)
        self.assertEqual(c["level"], "warning")
        self.assertIn(".env", c["message"])
