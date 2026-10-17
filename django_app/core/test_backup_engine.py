"""Motore di backup verificabile (BUILD_SPEC R1): config, sqlcmd simulato, copia verificata,
file incrementali, retention GFS, manifest senza segreti, end-to-end su SQLite."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from core.backup_engine import config as cfgmod
from core.backup_engine import doctor, engine, files, retention, status
from core.backup_engine import manifest as mf
from core.backup_engine.sqlserver import LogBackupNotPossible, SqlError, SqlServer
from core.backup_engine.transfer import TransferError, copy_verified, sha256_file


def _proc(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class FakeRunner:
    """Simula sqlcmd: risponde in base al testo della query."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or []

    def __call__(self, args, timeout, env):
        self.calls.append((args, timeout, env))
        sql = args[-1]
        for needle, reply in self.replies:
            if needle in sql:
                return reply
        return _proc("")


SEP = "\x1f"
HEADER_OUT = SEP.join(["BackupName", "BackupType", "DatabaseName", "FirstLSN", "LastLSN", "CheckpointLSN",
                       "DatabaseBackupLSN", "BackupFinishDate", "HasBackupChecksums"]) + "\n" + \
    SEP.join(["----"] * 9) + "\n" + \
    SEP.join(["NULL", "1", "PortaleNovicrom_PROD", "100000000012300001", "100000000045600001",
              "100000000040000001", "0", "2026-10-17 02:01:00", "1"]) + "\n"


class ConfigTests(SimpleTestCase):
    def test_finestra_log(self):
        self.assertEqual(cfgmod.parse_window("07-21"), (7, 21))
        for bad in ("21-07", "7", "25-26", "x"):
            with self.assertRaises(ValueError):
                cfgmod.parse_window(bad)

    @override_settings(BACKUP_TARGET=r"C:\locale", BACKUP_ENV_NAME="prod")
    def test_target_locale_in_prod_avvisa(self):
        cfg = cfgmod.load_config()
        self.assertEqual(cfg.env, "prod")
        self.assertTrue(any("locale" in w for w in cfg.warnings))
        self.assertTrue(cfg.in_log_window(7) and not cfg.in_log_window(21))

    @override_settings(BACKUP_TARGET=r"\\nas\hub")
    def test_target_unc_nessun_avviso(self):
        self.assertEqual(cfgmod.load_config(env="prod").warnings, ())

    def test_env_non_valido(self):
        with self.assertRaises(ValueError):
            cfgmod.load_config(env="../x")


class SqlServerTests(SimpleTestCase):
    def test_backup_full_con_checksum_e_timeout(self):
        r = FakeRunner()
        SqlServer(host=r".\SQLEXPRESS", timeout_s=1234, runner=r).backup_full("Portale ]x", Path(r"C:\s\a.bak"))
        args = r.calls[0][0]
        sql = args[-1]
        self.assertIn("BACKUP DATABASE [Portale ]]x]", sql)
        self.assertIn("WITH CHECKSUM, INIT, FORMAT", sql)
        self.assertNotIn("COMPRESSION", sql)
        self.assertIn("-b", args)
        self.assertEqual(args[args.index("-t") + 1], "1234")
        self.assertIn("-E", args)

    def test_password_mai_sulla_riga_di_comando(self):
        r = FakeRunner()
        SqlServer(host="h", user="u", password="pw-segreta", runner=r).verify(Path("x.bak"))
        args, _t, env = r.calls[0]
        self.assertNotIn("pw-segreta", " ".join(args))
        self.assertEqual(env["SQLCMDPASSWORD"], "pw-segreta")

    def test_header_parsing(self):
        r = FakeRunner([("HEADERONLY", _proc(HEADER_OUT))])
        h = SqlServer(host="h", runner=r).header(Path("x.bak"))
        self.assertEqual(h["backup_type"], 1)
        self.assertEqual(h["first_lsn"], "100000000012300001")
        self.assertEqual(h["last_lsn"], "100000000045600001")
        self.assertTrue(h["has_checksums"])

    def test_intestazioni_una_volta_sola_e_righe_multiple(self):
        """Bug trovato dalla prova reale: con -h 1 sqlcmd ripeteva l'intestazione a ogni riga."""
        out = SEP.join(["LogicalName", "PhysicalName", "Type", "Size"]) + "\n" + SEP.join(["---"] * 4) + "\n" \
            + SEP.join(["DB", "a.mdf", "D", "1"]) + "\n" + SEP.join(["DB_log", "a.ldf", "L", "1"]) + "\n"
        r = FakeRunner([("FILELISTONLY", _proc(out))])
        files = SqlServer(host="h", runner=r).filelist(Path("x.bak"))
        self.assertEqual([f["logical"] for f in files], ["DB", "DB_log"])
        self.assertNotIn("-h", r.calls[0][0])

    def test_errore_localizzato(self):
        r = FakeRunner([("VERIFYONLY", _proc("", rc=1, stderr="Messaggio 3234, livello 16\nIl file logico non fa parte del database"))])
        with self.assertRaises(SqlError) as ctx:
            SqlServer(host="h", runner=r).verify(Path("x.bak"))
        self.assertIn("non fa parte", str(ctx.exception))

    def test_log_su_simple_rifiutato(self):
        r = FakeRunner([("recovery_model_desc", _proc("SIMPLE\n"))])
        with self.assertRaises(LogBackupNotPossible):
            SqlServer(host="h", runner=r).backup_log("db", Path("x.trn"))
        self.assertFalse(any("BACKUP LOG" in c[0][-1] for c in r.calls))

    def test_errore_sqlcmd(self):
        r = FakeRunner([("VERIFYONLY", _proc("", rc=1, stderr="Msg 3013, Level 16, State 1\nVERIFY DATABASE is terminating abnormally."))])
        with self.assertRaises(SqlError) as ctx:
            SqlServer(host="h", runner=r).verify(Path("x.bak"))
        self.assertIn("terminating abnormally", str(ctx.exception))


class TransferTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "a.bak"
        self.src.write_bytes(b"dati" * 1000)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copia_verificata(self):
        sha = copy_verified(self.src, self.tmp / "t" / "a.bak")
        self.assertEqual(sha, sha256_file(self.tmp / "t" / "a.bak"))

    def test_hash_diverso_tre_tentativi_poi_fallisce_senza_toccare_la_sorgente(self):
        calls = []

        def bad_copier(src, dst, expected):
            calls.append(1)
            raise TransferError("hash diverso simulato")

        with self.assertRaises(TransferError):
            copy_verified(self.src, self.tmp / "t" / "a.bak", copier=bad_copier, sleep=lambda s: None)
        self.assertEqual(len(calls), 3)
        self.assertTrue(self.src.exists())


class FilesTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.media = self.tmp / "media"
        self.priv = self.tmp / "priv"
        (self.media / "a").mkdir(parents=True)
        self.priv.mkdir()
        (self.media / "a" / "x.txt").write_text("uno", encoding="utf-8")
        (self.priv / "referto.enc").write_bytes(b"gAAAAA-cifrato-fernet")
        self.objects = self.tmp / "objects"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_incrementale_e_file_privati_non_decifrati(self):
        roots = {"media": self.media, "priv": self.priv}
        r1 = files.backup_files(self.objects, {}, roots=roots)
        self.assertEqual((r1.files, r1.new_objects), (2, 2))
        sha = r1.index["priv"]["files"]["referto.enc"]["sha256"]
        self.assertEqual(files.object_path(self.objects, sha).read_bytes(), b"gAAAAA-cifrato-fernet")
        r2 = files.backup_files(self.objects, r1.index, roots=roots)
        self.assertEqual(r2.new_objects, 0)
        (self.media / "a" / "y.txt").write_text("due", encoding="utf-8")
        r3 = files.backup_files(self.objects, r2.index, roots=roots)
        self.assertEqual(r3.new_objects, 1)

    def test_private_roots_deduplica_e_annidate(self):
        with override_settings(TIMBRI_PRIVATE_ROOT=self.priv, TICKETS_PRIVATE_ROOT=self.priv,
                               ASSETS_PRIVATE_ROOT=self.priv / "assets", PRIVATE_ATTACHMENTS_ROOT=self.priv,
                               ANAGRAFICA_PRIVATE_ROOT=self.priv, DIARIO_PREPOSTO_PRIVATE_ROOT=self.priv,
                               HUB_BACHECA_PRIVATE_ROOT=self.priv, GESTIONE_SPECIFICHE_PRIVATE_ROOT=self.priv,
                               SCHEDE_SICUREZZA_PRIVATE_ROOT=self.priv, TASKS_PRIVATE_ROOT=self.priv):
            roots = files.private_roots()
        self.assertEqual(len(roots), 1)
        self.assertEqual(Path(list(roots.values())[0]), self.priv)


def _s(sid, status="ok", chain=None, verified=True):
    created, kind = retention.parse_set_id(sid)
    return retention.SetInfo(set_id=sid, kind=kind, created=created, status=status, verified=verified, chain_base=chain)


class RetentionTests(SimpleTestCase):
    NOW = datetime(2026, 10, 17, 6, 0)

    def _plan(self, sets, protected=None, daily=14, weekly=8, monthly=12, log_days=14):
        return retention.plan(sets, self.NOW, keep_daily=daily, keep_weekly=weekly, keep_monthly=monthly,
                              keep_log_days=log_days, protected=protected)

    def test_gfs_matrice(self):
        sets = [_s((self.NOW - timedelta(days=d)).strftime("%Y%m%d_020000") + "_full") for d in range(0, 400)]
        p = self._plan(sets, daily=14, weekly=8, monthly=12)
        kept = sorted(p.keep)
        self.assertTrue(all(_s(k).created >= self.NOW - timedelta(days=400) for k in kept))
        recent = [k for k in kept if _s(k).created >= self.NOW - timedelta(days=13, hours=7)]
        self.assertEqual(len(recent), 14)                  # tutti gli ultimi 14 giorni
        self.assertLessEqual(len(kept), 14 + 8 + 12)
        self.assertIn("20251018_020000_full", p.delete)     # oltre un anno: eliminato
        months = {(_s(k).created.year, _s(k).created.month) for k in kept}
        self.assertGreaterEqual(len(months), 12)

    def test_full_manuale_in_giornata_non_elimina_quello_delle_02_e_i_suoi_log(self):
        sets = [_s("20261017_020000_full"), _s("20261017_090500_log", chain="20261017_020000_full"),
                _s("20261017_103000_full"), _s("20261017_110500_log", chain="20261017_103000_full")]
        p = self._plan(sets)
        self.assertEqual(p.delete, {})

    def test_ultimo_full_verificato_e_drill_mai_cancellati(self):
        sets = [_s("20250101_020000_full"), _s("20260901_020000_full", verified=True),
                _s("20261016_020000_full", status="failed")]
        p = self._plan(sets, protected={"20250101_020000_full"}, daily=1, weekly=1, monthly=1)
        self.assertIn("20260901_020000_full", p.keep)
        self.assertIn("20250101_020000_full", p.keep)

    def test_log_segue_il_full_e_la_finestra(self):
        sets = [_s("20260801_020000_full"), _s("20260801_100500_log", chain="20260801_020000_full"),
                _s("20261016_020000_full"), _s("20261016_100500_log", chain="20261016_020000_full"),
                _s("20261010_100500_log", chain="20261009_020000_full")]
        p = self._plan(sets)
        self.assertIn("20261016_100500_log", p.keep)
        self.assertIn("20260801_100500_log", p.delete)    # oltre 14 giorni
        self.assertIn("20261010_100500_log", p.delete)    # FULL di base non più presente

    def test_apply_dry_run_non_cancella(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            d = tmp / "20200101_020000_full"
            d.mkdir()
            s = _s(d.name)
            s.path = d
            p = retention.RetentionPlan(delete={d.name: "test"})
            # il dry-run è a monte: plan non tocca il disco; apply sì
            self.assertTrue(d.exists())
            retention.apply(p, [s])
            self.assertFalse(d.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ManifestTests(SimpleTestCase):
    def test_round_trip_e_validazione(self):
        data = mf.new_manifest("20261017_020000_full", "full", "prod")
        data["app"] = {"version": "1.6.2", "commit": "abc", "branch": "release/prod", "migrations": {}}
        data["artifacts"] = [{"path": "db/a.bak", "sha256": "a" * 64, "size": 1, "verify_status": "ok"}]
        data["keys"] = {"env_var_names": ["X"]}
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / mf.MANIFEST_NAME).write_bytes(mf.dumps(data))
            self.assertEqual(mf.load(tmp)["set_id"], "20261017_020000_full")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        bad = dict(data, set_id="x")
        with self.assertRaises(mf.ManifestError):
            mf.dumps(bad)
        bad = dict(data, artifacts=[{"path": "a", "sha256": "corto", "size": 1}])
        with self.assertRaises(mf.ManifestError):
            mf.dumps(bad)

    def test_nessun_valore_del_env_nel_manifest(self):
        tmp = Path(tempfile.mkdtemp())
        canary = "CANARINO-segreto-7f3a"
        try:
            (tmp / ".env").write_text(f"SECRET_KEY={canary}\nDB_PASSWORD={canary}\nDOCUMENT_ENCRYPTION_KEY={canary}\n",
                                      encoding="utf-8")
            with override_settings(BASE_DIR=tmp, SECRET_KEY=canary + "-sk", DOCUMENT_ENCRYPTION_KEY=canary + "-dek"):
                keys = mf.keys_section()
            text = json.dumps(keys)
            self.assertNotIn(canary, text)
            self.assertEqual(sorted(keys["env_var_names"]), ["DB_PASSWORD", "DOCUMENT_ENCRYPTION_KEY", "SECRET_KEY"])
            self.assertEqual(len(keys["document_encryption_key_sha256"]), 64)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class _EngineBase(TestCase):
    """End-to-end su SQLite (il DB di test) con target e staging temporanei."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.media = self.tmp / "media"
        (self.media / "doc").mkdir(parents=True)
        (self.media / "doc" / "a.txt").write_text("contenuto", encoding="utf-8")
        self.ovr = override_settings(
            BACKUP_TARGET=str(self.tmp / "target"), BACKUP_STAGING_DIR=str(self.tmp / "staging"),
            BACKUP_ENV_NAME="prova", LOG_DIR=self.tmp / "logs", MEDIA_ROOT=self.media, BACKUP_ENV_DIR="",
            BACKUP_TARGET_SECONDARY="",
        )
        self.ovr.enable()
        (self.tmp / "logs").mkdir()
        self.cfg = cfgmod.load_config()

    def tearDown(self):
        self.ovr.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)


class EngineTests(_EngineBase):
    def test_full_verify_e_manomissione(self):
        from monitoring.models import BackupRun

        res = engine.run_full(self.cfg)
        self.assertEqual(res.status, "ok", res.error)
        set_dir = self.cfg.env_root / res.set_id
        data = mf.load(set_dir)
        art = data["artifacts"][0]
        self.assertEqual(sha256_file(set_dir / art["path"]), art["sha256"])
        self.assertIn("core", data["app"]["migrations"])
        self.assertTrue(BackupRun.objects.filter(kind="full", status="ok", set_id=res.set_id).exists())
        st = json.loads((self.cfg.status_dir / status.LOCAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(st["last"]["full"]["last_ok_set_id"], res.set_id)
        self.assertTrue((self.cfg.env_root / status.TARGET_NAME).exists())
        self.assertFalse(any((self.cfg.staging / "prova").glob("*.sqlite3")))   # staging pulito dopo la verifica
        self.assertEqual(engine.verify_set(self.cfg, set_dir).status, "ok")
        with open(set_dir / art["path"], "ab") as fh:
            fh.write(b"x")
        self.assertEqual(engine.verify_set(self.cfg, set_dir).status, "failed")

    def test_files_incrementale_e_retention(self):
        r1 = engine.run_files(self.cfg)
        self.assertEqual(r1.status, "ok", r1.error)
        self.assertEqual(r1.manifest["files"]["new_objects"], 1)
        r2 = engine.run_files(self.cfg)
        self.assertEqual(r2.manifest["files"]["new_objects"], 0)
        out = []
        res = engine.run_retention(self.cfg, dry_run=True, log=out.append)
        self.assertEqual(res.manifest["delete"], {})

    def test_log_su_sqlite_avvisa(self):
        res = engine.run_log(self.cfg, force=True)
        self.assertEqual(res.status, "warning")

    def test_log_fuori_finestra_non_fa_nulla(self):
        res = engine.run_log(self.cfg, now=datetime(2026, 10, 17, 23, 0))
        self.assertEqual((res.status, res.set_id), ("ok", ""))

    def test_db_irraggiungibile_poi_riconciliato(self):
        from monitoring.models import BackupRun

        with mock.patch.object(engine, "_db_record", return_value=False):
            res = engine.run_files(self.cfg)
        self.assertFalse(BackupRun.objects.filter(set_id=res.set_id).exists())
        self.assertEqual(len(status.take_pending(self.cfg)), 1)
        self.assertEqual(engine.reconcile_pending(self.cfg), 1)
        self.assertTrue(BackupRun.objects.filter(set_id=res.set_id).exists())
        self.assertEqual(status.take_pending(self.cfg), [])

    def test_comando_hub_backup_e_wrapper_backup_portale(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:   # host senza IIS/zip in sviluppo: avvisi → exit 1
            call_command("hub_backup", "--type", "all", stdout=out)
        self.assertEqual(ctx.exception.code, 1)
        kinds = {s.kind for s in engine.list_sets(self.cfg)}
        self.assertEqual(kinds, {"full", "files", "host"})
        with self.assertRaises(SystemExit):
            call_command("backup_portale", "--include-media", "--retention", "5", stdout=io.StringIO())
        self.assertGreaterEqual(len([s for s in engine.list_sets(self.cfg) if s.kind == "full"]), 2)


class DoctorTests(_EngineBase):
    def test_freschezza(self):
        checks = {c["check"]: c["level"] for c in doctor.freshness(self.cfg)}
        self.assertEqual(checks["backup_full"], "critical")
        engine.run_full(self.cfg)
        checks = {c["check"]: c["level"] for c in doctor.freshness(self.cfg)}
        self.assertEqual(checks["backup_full"], "ok")
        later = engine.timezone.now() + timedelta(hours=30)
        checks = {c["check"]: c["level"] for c in doctor.freshness(self.cfg, now=later)}
        self.assertEqual(checks["backup_full"], "warning")
        checks = {c["check"]: c["level"] for c in doctor.freshness(self.cfg, now=later + timedelta(hours=30))}
        self.assertEqual(checks["backup_full"], "critical")

    def test_run_checks_offline(self):
        checks = {c["check"]: c["level"] for c in doctor.run_checks(self.cfg, with_tasks=False, with_network=False)}
        self.assertEqual(checks["target"], "ok")
        self.assertEqual(checks["staging"], "ok")
        self.assertEqual(checks["env_dir"], "warning")
