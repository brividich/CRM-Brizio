"""
Contract test per SQLServerLegacyBackend.

Lock the contract:
- credenziali corrette -> Django user sincronizzato
- credenziali sbagliate -> None (NON solleva)
- utente non attivo -> None
- AD-managed (password sentinel) -> None (deve passare per LDAP)
- utente inesistente -> None
- alias senza dominio (es. "lbova") risolto via email__istartswith
"""
from __future__ import annotations

import unittest.mock as mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from werkzeug.security import generate_password_hash

from core.accounts.backends import SQLServerLegacyBackend
from core.legacy_models import UtenteLegacy

User = get_user_model()


def _ensure_legacy_tables() -> None:
    """Replica le tabelle legacy in SQLite per il backend offline.

    Include anche ``anagrafica_dipendenti`` perche' il backend la interroga
    nel fallback ``_resolve_legacy_user_by_alias`` quando l'utente non e'
    trovato per email.
    """
    vendor = connection.vendor
    if vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS utenti (
                id INTEGER PRIMARY KEY,
                nome VARCHAR(200) NOT NULL,
                email VARCHAR(200) NULL,
                password VARCHAR(500) NOT NULL,
                ruolo VARCHAR(100) NULL,
                attivo INTEGER NOT NULL DEFAULT 1,
                deve_cambiare_password INTEGER NOT NULL DEFAULT 0,
                ruolo_id INTEGER NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS anagrafica_dipendenti (
                id INTEGER PRIMARY KEY,
                aliasusername VARCHAR(200) NULL,
                email VARCHAR(200) NULL,
                utente_id INTEGER NULL
            )
            """
        )


def _clear_legacy_tables() -> None:
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        for table in ("utenti", "anagrafica_dipendenti"):
            try:
                cursor.execute(f"DELETE FROM {table}")
            except Exception:
                continue


@override_settings(LEGACY_AUTH_ENABLED=True)
class SQLServerLegacyBackendContractTests(TestCase):
    PASSWORD_PLAIN = "synthetic-password-9z!"

    def setUp(self):
        super().setUp()
        _ensure_legacy_tables()
        _clear_legacy_tables()
        self.backend = SQLServerLegacyBackend()

    def _make_user(
        self,
        *,
        email: str | None = "active@example.invalid",
        password: str | None = None,
        attivo: bool = True,
        nome: str = "Utente Sintetico",
    ) -> UtenteLegacy:
        return UtenteLegacy.objects.create(
            email=email,
            password=password if password is not None else generate_password_hash(self.PASSWORD_PLAIN),
            attivo=attivo,
            nome=nome,
        )

    def test_correct_credentials_authenticate(self):
        self._make_user(email="active@example.invalid")
        user = self.backend.authenticate(
            request=None, username="active@example.invalid", password=self.PASSWORD_PLAIN
        )
        self.assertIsNotNone(user, "Backend deve restituire un Django user su credenziali valide")
        self.assertTrue(isinstance(user, User))

    def test_wrong_password_returns_none(self):
        self._make_user(email="active@example.invalid")
        user = self.backend.authenticate(
            request=None, username="active@example.invalid", password="wrong-password"
        )
        self.assertIsNone(user, "Password sbagliata DEVE restituire None, non sollevare")

    def test_inactive_user_returns_none(self):
        self._make_user(email="inactive@example.invalid", attivo=False)
        user = self.backend.authenticate(
            request=None,
            username="inactive@example.invalid",
            password=self.PASSWORD_PLAIN,
        )
        self.assertIsNone(user)

    def test_ad_managed_password_sentinel_returns_none(self):
        # Password sentinel "*AD_MANAGED*" segnala che l'utente va autenticato via LDAP.
        # Il backend legacy deve cedere la responsabilità (None), non tentare il check hash.
        self._make_user(email="admanaged@example.invalid", password="*AD_MANAGED*")
        user = self.backend.authenticate(
            request=None,
            username="admanaged@example.invalid",
            password="qualsiasi-password",
        )
        self.assertIsNone(user)

    def test_unknown_user_returns_none(self):
        # Il fallback _resolve_legacy_user_by_alias usa SQL raw con placeholder
        # ``?`` per anagrafica_dipendenti. Su SQLite Django instrumenta
        # ``last_executed_query`` con ``%`` formatting che e' incompatibile con
        # ``?``, sollevando TypeError quando il debug cursor e' attivo nei test.
        # Il contratto "utente sconosciuto -> None" non dipende dal contenuto
        # del fallback, quindi mockiamo la chiamata per isolarci dalla quirk.
        with mock.patch(
            "core.accounts.backends._resolve_legacy_user_by_alias", return_value=None
        ):
            user = self.backend.authenticate(
                request=None,
                username="not-in-db@example.invalid",
                password=self.PASSWORD_PLAIN,
            )
        self.assertIsNone(user)

    def test_alias_only_resolves_via_email_local_part(self):
        # Login con solo alias (senza @dominio) deve risolvere via UPN local-part.
        self._make_user(email="lbova@example.invalid")
        user = self.backend.authenticate(
            request=None, username="lbova", password=self.PASSWORD_PLAIN
        )
        self.assertIsNotNone(user)

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_legacy_auth_disabled_returns_none(self):
        self._make_user(email="active@example.invalid")
        user = self.backend.authenticate(
            request=None, username="active@example.invalid", password=self.PASSWORD_PLAIN
        )
        self.assertIsNone(user, "Con LEGACY_AUTH_ENABLED=False il backend deve essere no-op")

    def test_empty_credentials_returns_none(self):
        for username, password in (("", ""), ("active@example.invalid", ""), ("", "x")):
            with self.subTest(username=username):
                self.assertIsNone(
                    self.backend.authenticate(request=None, username=username, password=password)
                )
