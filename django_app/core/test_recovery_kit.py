"""Recovery Kit, ricostruzione dei file, piano da riga di comando e lock dei prerequisiti (BUILD_SPEC R3)."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from core.backup_engine import recovery_kit as rk
from core.backup_engine import restore_files, restore_plan

PW = "cavallo batteria graffetta corretta montagna"
ENV = b"DJANGO_SECRET_KEY=sk-sintetica\nDOCUMENT_ENCRYPTION_KEY=dek-sintetica\nDB_HOST=x\n"
FAST = {"n": 2 ** 12}


class RecoveryKitTests(SimpleTestCase):
    def test_round_trip_e_impronte(self):
        kit = rk.build_kit(ENV, PW, env_name="prova", pfx_bytes=b"PFX", pfx_password="pw-pfx", pfx_thumbprint="AB12", **FAST)
        self.assertNotIn(b"dek-sintetica", kit)
        self.assertNotIn(b"pw-pfx", kit)
        header, payload = rk.open_kit(kit, PW)
        self.assertEqual(payload["files"][".env"], ENV)
        self.assertEqual(payload["files"]["cert.pfx"], b"PFX")
        self.assertEqual(payload["pfx_password"], "pw-pfx")
        self.assertEqual(header["contains"], [".env", "cert.pfx"])
        self.assertEqual(header["fingerprints"]["document_encryption_key_sha256"],
                         __import__("hashlib").sha256(b"dek-sintetica").hexdigest())

    def test_parametri_scrypt_di_default(self):
        self.assertEqual((rk.SCRYPT_N, rk.SCRYPT_R, rk.SCRYPT_P), (2 ** 17, 8, 1))

    def test_passphrase_errata(self):
        kit = rk.build_kit(ENV, PW, **FAST)
        with self.assertRaises(rk.KitError):
            rk.open_kit(kit, PW + " sbagliata")

    def test_manomissione_dell_intestazione_e_del_contenuto(self):
        kit = rk.build_kit(ENV, PW, env_name="prova", **FAST)
        with self.assertRaises(rk.KitError):
            rk.open_kit(kit.replace(b'"env":"prova"', b'"env":"altro"'), PW)
        with self.assertRaises(rk.KitError):
            rk.open_kit(kit[:-1] + bytes([kit[-1] ^ 1]), PW)
        with self.assertRaises(rk.KitError):
            rk.open_kit(b"ZIP" + kit, PW)

    def test_passphrase_debole_rifiutata(self):
        for weak in ("corta", "tre parole soltanto qui", "a b c d e"):
            with self.assertRaises(rk.KitError):
                rk.build_kit(ENV, weak, **FAST)

    def test_confronto_impronte(self):
        header, _ = rk.open_kit(rk.build_kit(ENV, PW, **FAST), PW)
        self.assertEqual(rk.compare_fingerprints(header, {}), [])
        self.assertEqual(rk.compare_fingerprints(header, {"document_encryption_key_sha256": "x" * 64}),
                         ["DOCUMENT_ENCRYPTION_KEY"])

    def test_impronta_secret_key_letta_da_django_secret_key(self):
        sha = __import__("hashlib").sha256(b"sk-sintetica").hexdigest()
        self.assertEqual(rk.fingerprints_from_env(ENV)["secret_key_sha256"], sha)
        self.assertEqual(rk.fingerprints_from_env(b"SECRET_KEY=sk-sintetica\n")["secret_key_sha256"], sha)

    def test_kit_esportato_senza_impronta_secret_key_si_apre(self):
        # kit dei primi export: secret_key_sha256 vuota perché si cercava SECRET_KEY
        with mock.patch.object(rk, "fingerprints_from_env",
                               lambda b: {**self._fp(b), "secret_key_sha256": None}):
            kit = rk.build_kit(ENV, PW, **FAST)
        header, _ = rk.open_kit(kit, PW)
        sha = __import__("hashlib").sha256(b"sk-sintetica").hexdigest()
        self.assertEqual(header["fingerprints"]["secret_key_sha256"], sha)
        self.assertEqual(rk.compare_fingerprints(header, {"secret_key_sha256": sha}), [])

    @staticmethod
    def _fp(env_bytes):
        values = rk.parse_env(env_bytes)
        return {"document_encryption_key_sha256": rk._sha(values.get("DOCUMENT_ENCRYPTION_KEY")),
                "secret_key_sha256": rk._sha(values.get("DJANGO_SECRET_KEY")),
                "env_sha256": rk._sha(env_bytes)}

    def test_cli_import_si_ferma_se_le_impronte_non_coincidono(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            kit = tmp / "k.hubkit"
            kit.write_bytes(rk.build_kit(ENV, PW, **FAST))
            plan = tmp / "plan.json"
            plan.write_text(json.dumps({"expected_keys": {"document_encryption_key_sha256": "y" * 64}}), encoding="utf-8")
            with mock.patch("sys.stdin", io.StringIO(PW + "\n")), mock.patch("sys.stdout", io.StringIO()) as out:
                code = rk.main(["import", str(kit), "--env-dest", str(tmp / ".env"), "--plan", str(plan), "--passphrase-stdin"])
            self.assertEqual(code, 3)
            self.assertFalse((tmp / ".env").exists())
            self.assertNotIn("dek-sintetica", out.getvalue())
            plan.write_text(json.dumps({"expected_keys": {}}), encoding="utf-8")
            (tmp / ".env").write_text("VECCHIO=1\n", encoding="utf-8")
            with mock.patch("sys.stdin", io.StringIO(PW + "\n")), mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(rk.main(["import", str(kit), "--env-dest", str(tmp / ".env"), "--passphrase-stdin"]), 2)
            with mock.patch("sys.stdin", io.StringIO(PW + "\n")), mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(rk.main(["import", str(kit), "--env-dest", str(tmp / ".env"), "--force", "--passphrase-stdin"]), 0)
            self.assertEqual((tmp / ".env").read_bytes(), ENV)
            self.assertTrue(list(tmp.glob(".env.bak-*")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RecoveryKitCommandTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "app").mkdir()
        (self.tmp / "app" / ".env").write_bytes(ENV)
        self.ovr = override_settings(BASE_DIR=self.tmp / "app", LOG_DIR=self.tmp, SECRET_KEY="sk-sintetica",
                                     DOCUMENT_ENCRYPTION_KEY="dek-sintetica")
        self.ovr.enable()

    def tearDown(self):
        self.ovr.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_verify_e_stato_per_il_monitoraggio(self):
        from core.backup_engine import config as cfgmod
        from core.backup_engine import doctor

        out = self.tmp / "kit" / "prova.hubkit"
        with mock.patch("sys.stdin", io.StringIO(PW + "\n")):
            call_command("hub_recovery_kit", "export", "--out", str(out), "--passphrase-stdin", stdout=io.StringIO())
        self.assertTrue(out.exists())
        state = json.loads((self.tmp / doctor.RECOVERY_KIT_STATUS).read_text(encoding="utf-8"))
        self.assertNotIn("dek-sintetica", json.dumps(state))
        with override_settings(BACKUP_TARGET=str(self.tmp / "t")):
            self.assertEqual(doctor.recovery_kit_check(cfgmod.load_config(env="prova"))["level"], "ok")
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(PW + "\n")):
            call_command("hub_recovery_kit", "verify", str(out), "--passphrase-stdin", stdout=buf)
        self.assertIn("i documenti si aprono", buf.getvalue())
        with override_settings(DOCUMENT_ENCRYPTION_KEY="altra"), mock.patch("sys.stdin", io.StringIO(PW + "\n")):
            with self.assertRaises(CommandError):
                call_command("hub_recovery_kit", "verify", str(out), "--passphrase-stdin", stdout=io.StringIO())
        with mock.patch("sys.stdin", io.StringIO(PW + "\n")), self.assertRaises(CommandError):
            call_command("hub_recovery_kit", "export", "--out", str(out), "--passphrase-stdin", stdout=io.StringIO())

    def test_export_usa_il_config_env_persistente_del_deploy(self):
        from core.management.commands import hub_recovery_kit as cmd

        app = self.tmp / "prod" / "current" / "django_app"
        app.mkdir(parents=True)
        (app / ".env").write_bytes(b"COPIA=1\n")
        (self.tmp / "prod" / "config").mkdir()
        (self.tmp / "prod" / "config" / ".env").write_bytes(ENV)
        with override_settings(BASE_DIR=app), mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("PORTAL_CONFIG_ENV_FILE", None)
            self.assertEqual(cmd._env_path(), self.tmp / "prod" / "config" / ".env")


class ReleaseZipTests(SimpleTestCase):
    def test_zip_trovato_in_shared_packages_anche_dalla_cartella_releases(self):
        import zipfile

        from core.backup_engine import host_manifest

        tmp = Path(tempfile.mkdtemp()).resolve()   # percorsi 8.3 (LB2EF~1) vs nome lungo
        try:
            # BASE_DIR come lo vede resolve() dietro la junction current: <root>\prod\releases\<id>\django_app
            app = tmp / "prod" / "releases" / "20261019_123258" / "django_app"
            app.mkdir(parents=True)
            packages = tmp / "shared" / "packages"
            packages.mkdir(parents=True)
            zp = packages / "portale-novicrom-v1.6.8-20261019_122110.zip"
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("BUILD_INFO.json", json.dumps({"commit": "abc123"}))
            with override_settings(BASE_DIR=app):
                self.assertEqual(host_manifest.find_release_zip({"commit": "abc123"}), zp)
                self.assertIsNone(host_manifest.find_release_zip({"commit": "altro"}))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RestoreFilesTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.key = Fernet.generate_key()
        enc = restore_files.MAGIC + Fernet(self.key).encrypt(b"referto")
        self.objects = self.tmp / "env" / "_objects"
        self.index = {"priv": {"path": str(self.tmp / "orig" / "priv"), "files": {}},
                      "media": {"path": str(self.tmp / "orig" / "media"), "files": {}}}
        import hashlib

        for label, rel, data in (("priv", "a/referto.enc", enc), ("media", "logo.png", b"PNG")):
            sha = hashlib.sha256(data).hexdigest()
            p = self.objects / sha[:2] / sha
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            self.index[label]["files"][rel] = {"sha256": sha, "size": len(data), "mtime": 1700000000}
        (self.tmp / ".env").write_text(f"DOCUMENT_ENCRYPTION_KEY={self.key.decode()}\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ricostruzione_verificata_e_campioni_decifrati(self):
        new = self.tmp / "nuovo"
        rep = restore_files.restore(self.tmp / "env", self.index, mapping=[(str(self.tmp / "orig"), str(new))],
                                    env_file=self.tmp / ".env", samples=5)
        self.assertEqual(rep["status"], "ok", rep)
        self.assertEqual(rep["files"], 2)
        self.assertTrue((new / "priv" / "a" / "referto.enc").read_bytes().startswith(restore_files.MAGIC))  # resta cifrato
        self.assertEqual(rep["decrypt"]["priv"]["decrypted"], 1)

    def test_oggetto_corrotto_e_chiave_sbagliata(self):
        sha = self.index["media"]["files"]["logo.png"]["sha256"]
        (self.objects / sha[:2] / sha).write_bytes(b"corrotto")
        (self.tmp / ".env").write_text(f"DOCUMENT_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n", encoding="utf-8")
        rep = restore_files.restore(self.tmp / "env", self.index, mapping=[(str(self.tmp / "orig"), str(self.tmp / "n"))],
                                    env_file=self.tmp / ".env")
        self.assertEqual(rep["status"], "failed")
        self.assertTrue(any("hash" in e for e in rep["errors"]))
        self.assertEqual(rep["decrypt"]["priv"]["decrypted"], 0)


class RestorePlanCliTests(SimpleTestCase):
    def test_main_senza_django(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            with mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(restore_plan.main([str(tmp)]), 2)      # nessun FULL
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PrereqsLockTests(SimpleTestCase):
    def test_lock_valido(self):
        lock_path = Path(settings.BASE_DIR).parent / "deployment" / "recovery" / "prereqs.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertEqual(lock["schema_version"], 1)
        names = set()
        for item in lock["items"]:
            names.add(item["name"])
            self.assertTrue(item["url"].startswith("https://"), item["name"])
            self.assertTrue(item.get("silent_args"), item["name"])
            self.assertTrue(item.get("check"), item["name"])
            self.assertTrue(item.get("signer_must_contain"), item["name"])
            if item.get("sha256"):
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(item["url_resolved"].startswith("https://"), item["name"])
                self.assertIn(item["signer_must_contain"], item["signer"])
        for required in ("odbc-driver-18", "httpplatformhandler-1.2", "vcredist-x64", "python-3.13",
                         "sql-server-2025-express-bootstrapper", "entra-private-network-connector"):
            self.assertIn(required, names)
        self.assertTrue(all(i.get("sha256") for i in lock["items"]), "tutte le voci devono essere verificate")
