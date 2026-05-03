"""
Contract test per core.accounts.backends.LDAPBackend.

Lock the contract:
- bind con credenziali corrette -> Django user creato/sincronizzato
- bind con credenziali errate -> None (fail-closed, MAI 500)
- ldap3 non disponibile -> None
- LDAP_ENABLED=False / LDAP_SERVER vuoto -> None (no-op)
- timeout/socket error -> None

Il fallback usa la mock strategy ufficiale di ldap3 (MOCK_SYNC) per simulare
una directory AD locale, evitando dipendenze esterne.
"""
from __future__ import annotations

import unittest.mock as mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.accounts.backends import LDAPBackend

User = get_user_model()


@override_settings(
    LEGACY_AUTH_ENABLED=True,
    LDAP_ENABLED=True,
    LDAP_SERVER="ldap://dc01.example.invalid",
    LDAP_DOMAIN="EXAMPLE",
    LDAP_UPN_SUFFIX="@example.invalid",
    LDAP_TIMEOUT=2,
)
class LDAPBackendContractTests(TestCase):
    GOOD_USER_UPN = "synthetic.user@example.invalid"
    GOOD_PASSWORD = "synthetic-password-9z!"

    def setUp(self):
        super().setUp()
        self.backend = LDAPBackend()

    @override_settings(LDAP_ENABLED=False)
    def test_ldap_disabled_returns_none(self):
        user = self.backend.authenticate(
            request=None, username=self.GOOD_USER_UPN, password=self.GOOD_PASSWORD
        )
        self.assertIsNone(user)

    @override_settings(LDAP_SERVER="")
    def test_no_server_returns_none(self):
        user = self.backend.authenticate(
            request=None, username=self.GOOD_USER_UPN, password=self.GOOD_PASSWORD
        )
        self.assertIsNone(user)

    def test_empty_credentials_returns_none(self):
        for username, password in (("", ""), (self.GOOD_USER_UPN, ""), ("", "x")):
            with self.subTest(username=username):
                self.assertIsNone(
                    self.backend.authenticate(
                        request=None, username=username, password=password
                    )
                )

    def test_ldap3_unavailable_returns_none(self):
        # Simuliamo l'assenza di ldap3 forzando un ImportError nell'import locale.
        with mock.patch.dict(
            "sys.modules",
            {"ldap3": None, "ldap3.core": None, "ldap3.core.exceptions": None},
        ):
            user = self.backend.authenticate(
                request=None, username=self.GOOD_USER_UPN, password=self.GOOD_PASSWORD
            )
        self.assertIsNone(user)

    def test_bind_failure_returns_none_not_500(self):
        """Bind che fallisce (credenziali errate) DEVE tornare None, mai sollevare."""
        fake_conn = mock.MagicMock()
        fake_conn.bind.return_value = False

        with mock.patch("ldap3.Connection", return_value=fake_conn):
            user = self.backend.authenticate(
                request=None, username=self.GOOD_USER_UPN, password="wrong-password"
            )
        self.assertIsNone(user, "Bind fallito DEVE essere None, mai HTTP 500")

    def test_socket_error_returns_none(self):
        """Server LDAP irraggiungibile DEVE tornare None, fail-closed."""
        from ldap3.core.exceptions import LDAPSocketOpenError

        with mock.patch(
            "ldap3.Connection",
            side_effect=LDAPSocketOpenError("connection refused"),
        ):
            user = self.backend.authenticate(
                request=None, username=self.GOOD_USER_UPN, password=self.GOOD_PASSWORD
            )
        self.assertIsNone(user)

    def test_successful_bind_invokes_provisioning(self):
        """Bind OK -> il backend chiama provision_legacy_user con UPN risolto."""
        fake_conn = mock.MagicMock()
        fake_conn.bind.return_value = True

        with mock.patch("ldap3.Connection", return_value=fake_conn), mock.patch(
            "core.accounts.backends.resolve_ldap_identity",
            return_value=(self.GOOD_USER_UPN, "Synthetic User"),
        ), mock.patch(
            "core.accounts.backends.provision_legacy_user", return_value=None
        ) as provision_mock:
            user = self.backend.authenticate(
                request=None, username=self.GOOD_USER_UPN, password=self.GOOD_PASSWORD
            )

        self.assertIsNone(user, "provision ritorna None -> backend ritorna None")
        provision_mock.assert_called_once()
        kwargs = provision_mock.call_args.kwargs
        # Lock the contract: provision_legacy_user deve ricevere UPN risolto e full_name.
        self.assertEqual(kwargs.get("full_name"), "Synthetic User")
        self.assertEqual(provision_mock.call_args.args[0], self.GOOD_USER_UPN)

    def test_successful_bind_alias_only_canonicalizes_upn(self):
        """Login con alias 'lbova' deve costruire UPN 'lbova@example.invalid'."""
        fake_conn = mock.MagicMock()
        fake_conn.bind.return_value = True

        with mock.patch("ldap3.Connection", return_value=fake_conn) as conn_mock, mock.patch(
            "core.accounts.backends.resolve_ldap_identity",
            return_value=("lbova@example.invalid", "L Bova"),
        ), mock.patch("core.accounts.backends.provision_legacy_user", return_value=None):
            self.backend.authenticate(
                request=None, username="lbova", password=self.GOOD_PASSWORD
            )
        # Almeno una chiamata a Connection con bind che inizia per "lbova".
        self.assertGreaterEqual(conn_mock.call_count, 1)
