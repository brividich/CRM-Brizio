"""Regressioni dell'audit sicurezza 09/10, Fase 2 (M1, M2, M4, M10, M12, S4, S6, A7/CSP)."""
from __future__ import annotations

import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings


class TotpPerUserLockoutTests(SimpleTestCase):
    """Audit M1: tentativi contati per utente, codice TOTP valido una volta sola."""

    def setUp(self):
        cache.clear()
        self.user = SimpleNamespace(pk=4242)

    def tearDown(self):
        cache.clear()

    def test_lock_after_max_attempts_is_per_user(self):
        from twofa.utils import TOTP_MAX_ATTEMPTS, register_totp_failure, totp_lock_remaining

        for _ in range(TOTP_MAX_ATTEMPTS - 1):
            remaining, locked = register_totp_failure(self.user)
            self.assertEqual(locked, 0)
        remaining, locked = register_totp_failure(self.user)
        self.assertEqual(remaining, 0)
        self.assertGreater(locked, 0)
        # Il blocco vale per l'utente, non per la sessione: un nuovo login non lo azzera.
        self.assertGreater(totp_lock_remaining(self.user), 0)
        self.assertEqual(totp_lock_remaining(SimpleNamespace(pk=4243)), 0)

    def test_lock_is_progressive(self):
        from twofa.utils import TOTP_MAX_ATTEMPTS, register_totp_failure

        first = second = 0
        for _ in range(TOTP_MAX_ATTEMPTS):
            _, first = register_totp_failure(self.user)
        for _ in range(TOTP_MAX_ATTEMPTS):
            _, second = register_totp_failure(self.user)
        self.assertGreater(second, first)

    def test_totp_code_cannot_be_replayed(self):
        import pyotp

        from twofa.utils import verify_totp_once

        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        self.assertTrue(verify_totp_once(self.user, secret, code))
        self.assertFalse(verify_totp_once(self.user, secret, code))

    def test_email_resend_is_limited(self):
        from twofa.utils import EMAIL_OTP_MAX_SENDS, email_otp_send_allowed

        for _ in range(EMAIL_OTP_MAX_SENDS):
            self.assertTrue(email_otp_send_allowed(self.user))
        self.assertFalse(email_otp_send_allowed(self.user))


class LdapGroupAllowlistLoginTests(SimpleTestCase):
    """Audit M2: allowlist dei gruppi AD applicata al login."""

    def test_group_cns_from_member_of(self):
        from core.legacy_utils import ldap_group_cns

        self.assertEqual(
            ldap_group_cns(["CN=Portale Utenti,OU=Gruppi,DC=example,DC=local", "CN=Altro,DC=example"]),
            ["Portale Utenti", "Altro"],
        )

    @override_settings(LDAP_GROUP_ALLOWLIST=["Portale Utenti"], LDAP_GROUP_ALLOWLIST_ON_LOGIN=True)
    def test_login_requires_allowed_group(self):
        from core.legacy_utils import ldap_login_group_allowed

        self.assertTrue(ldap_login_group_allowed(["portale utenti"]))
        self.assertFalse(ldap_login_group_allowed(["Altro"]))
        self.assertFalse(ldap_login_group_allowed([]))

    @override_settings(LDAP_GROUP_ALLOWLIST=[], LDAP_GROUP_ALLOWLIST_ON_LOGIN=True)
    def test_empty_allowlist_does_not_filter(self):
        from core.legacy_utils import ldap_login_group_allowed

        self.assertTrue(ldap_login_group_allowed([]))

    @override_settings(LDAP_GROUP_ALLOWLIST=["Portale Utenti"], LDAP_GROUP_ALLOWLIST_ON_LOGIN=False)
    def test_opt_out(self):
        from core.legacy_utils import ldap_login_group_allowed

        self.assertTrue(ldap_login_group_allowed([]))


class InactiveUserSessionTests(TestCase):
    """Audit M4: un utente disattivato perde subito le sessioni."""

    def test_backends_reject_inactive_user(self):
        from core.accounts.backends import LDAPBackend, SQLServerLegacyBackend

        user = get_user_model().objects.create_user(username="m4-user", password="x-pass-123")
        self.assertEqual(LDAPBackend().get_user(user.pk), user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        self.assertIsNone(LDAPBackend().get_user(user.pk))
        self.assertIsNone(SQLServerLegacyBackend().get_user(user.pk))

    def test_deactivation_syncs_django_user(self):
        from admin_portale.views import _sync_django_active_from_legacy
        from core.models import Profile

        user = get_user_model().objects.create_user(username="m4-sync", password="x-pass-123")
        Profile.objects.create(user=user, legacy_user_id=9101, legacy_ruolo_id=2, legacy_ruolo="utente")
        self.assertEqual(_sync_django_active_from_legacy([9101], False), 1)
        user.refresh_from_db()
        self.assertFalse(user.is_active)


class DocumentKeyRotationTests(SimpleTestCase):
    """Audit M12: MultiFernet legge con la chiave vecchia e ri-cifra con la nuova."""

    def test_old_key_still_decrypts_and_rotate_uses_new_key(self):
        from core.encrypted_storage import decrypt_bytes, encrypt_bytes, rotate_bytes

        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        with override_settings(DOCUMENT_ENCRYPTION_KEY=old_key, DOCUMENT_ENCRYPTION_OLD_KEYS=[]):
            blob = encrypt_bytes(b"referto sintetico")
        with override_settings(DOCUMENT_ENCRYPTION_KEY=new_key, DOCUMENT_ENCRYPTION_OLD_KEYS=[old_key]):
            self.assertEqual(decrypt_bytes(blob), b"referto sintetico")
            rotated = rotate_bytes(blob)
        with override_settings(DOCUMENT_ENCRYPTION_KEY=new_key, DOCUMENT_ENCRYPTION_OLD_KEYS=[]):
            self.assertEqual(decrypt_bytes(rotated), b"referto sintetico")

    def test_rotate_skips_plain_files(self):
        from core.encrypted_storage import rotate_bytes

        with override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            self.assertIsNone(rotate_bytes(b"in chiaro"))


class AclCacheVersionTests(SimpleTestCase):
    """Audit S4: la versione ACL non torna mai a un valore gia' usato."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_lost_version_key_does_not_restart_from_one(self):
        from core.legacy_cache import LEGACY_CACHE_VERSION_KEY, bump_legacy_cache_version, get_legacy_cache_version

        import time

        first = get_legacy_cache_version()
        bumped = bump_legacy_cache_version()
        self.assertGreater(bumped, first)
        cache.delete(LEGACY_CACHE_VERSION_KEY)  # come un _cull di DatabaseCache
        later = time.time() + 5  # il ripristino avviene dopo, non nello stesso millisecondo
        with patch("time.time", return_value=later):
            restored = get_legacy_cache_version()
        # Mai di nuovo 1 ne' una versione gia' superata (permessi vecchi in cache).
        self.assertGreater(restored, bumped)

    def test_consecutive_bumps_always_increase(self):
        from core.legacy_cache import bump_legacy_cache_version

        values = [bump_legacy_cache_version() for _ in range(5)]
        self.assertEqual(values, sorted(set(values)))


class BackupEnvSeparationTests(SimpleTestCase):
    """Audit M10: il .env completo non finisce accanto ai dati."""

    def _run_config(self, base_dir: Path, backup_dir: Path, env_dir: str):
        from core.management.commands.backup_portale import Command

        logs = []
        errors = []
        with override_settings(BASE_DIR=base_dir, BACKUP_ENV_DIR=env_dir):
            Command()._backup_config(backup_dir, lambda msg, level="INFO": logs.append((level, msg)), errors)
        return logs, errors

    def test_env_values_not_copied_in_backup(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".env").write_text("SECRET_KEY=valore-segreto\nDB_PASSWORD=x\n", encoding="utf-8")
        backup_dir = tmp / "backups" / "20261009_120000"
        backup_dir.mkdir(parents=True)
        self._run_config(tmp, backup_dir, "")
        self.assertFalse((backup_dir / "config" / ".env").exists())
        keys = (backup_dir / "config" / "env_keys.txt").read_text(encoding="utf-8")
        self.assertIn("SECRET_KEY", keys)
        self.assertNotIn("valore-segreto", keys)

    def test_env_copied_only_to_separate_dir(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".env").write_text("SECRET_KEY=valore-segreto\n", encoding="utf-8")
        backup_dir = tmp / "backups" / "20261009_120000"
        backup_dir.mkdir(parents=True)
        env_dir = tmp / "env_vault"
        self._run_config(tmp, backup_dir, str(env_dir))
        self.assertTrue((env_dir / "20261009_120000" / ".env").exists())


class CspPolicyTests(SimpleTestCase):
    """CSP senza CDN: le librerie sono self-hostate."""

    def test_no_external_script_hosts(self):
        policy = settings.CSP_POLICY
        self.assertNotIn("cdn.jsdelivr.net", policy)
        self.assertNotIn("cdnjs.cloudflare.com", policy)
        self.assertIn("object-src 'none'", policy)


class LogFilePerProcessTests(SimpleTestCase):
    """Audit S6: web, qcluster e comandi scrivono file distinti."""

    def test_log_file_names(self):
        from config.settings import base

        with patch.object(base.sys, "argv", ["manage.py", "qcluster"]):
            self.assertEqual(base._log_file_for_process(), "qcluster.log")
        with patch.object(base.sys, "argv", ["manage.py", "backup_portale"]):
            self.assertEqual(base._log_file_for_process(), "commands.log")
        with patch.object(base.sys, "argv", [r"C:\venv\Lib\site-packages\waitress\__main__.py"]):
            self.assertEqual(base._log_file_for_process(), "app.log")
