"""LDAP: affidabilità di login, ricerche e cache colonne legacy (ldap3 sempre mockato, dati sintetici)."""
from __future__ import annotations

from unittest import mock

from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from ldap3 import NTLM, SIMPLE
from ldap3.core.exceptions import LDAPSocketOpenError

from core import ldap_conn
from core.accounts.backends import LDAPBackend, _prosegui_dopo_bind_rifiutato

BAD_PWD_52E = {
    "result": 49,
    "description": "invalidCredentials",
    "message": "80090308: LdapErr: DSID-0C09042A, comment: AcceptSecurityContext error, data 52e, v4563",
}
USER_NOT_FOUND_525 = {
    "result": 49,
    "description": "invalidCredentials",
    "message": "80090308: LdapErr: DSID-0C09042A, comment: AcceptSecurityContext error, data 525, v4563",
}
STRONGER_AUTH = {"result": 8, "description": "strongerAuthRequired", "message": "00002028: LdapErr"}


def _conn(bind_ok: bool, result=None):
    c = mock.MagicMock()
    c.bind.return_value = bind_ok
    c.result = result
    return c


class _PulitoMixin:
    def setUp(self):
        super().setUp()
        ldap_conn.reset_ldap_servers()
        ldap_conn.ldap_breaker_reset()
        self.addCleanup(ldap_conn.reset_ldap_servers)
        self.addCleanup(ldap_conn.ldap_breaker_reset)


@override_settings(LDAP_SERVER="ldap://dc01.example.invalid ldap://dc02.example.invalid", LDAP_TIMEOUT=2)
class LdapServerPoolTests(_PulitoMixin, SimpleTestCase):
    def test_pool_condiviso_first_con_esclusione(self):
        from ldap3 import FIRST, ServerPool

        pool = ldap_conn.get_ldap_server()
        self.assertIsInstance(pool, ServerPool)
        self.assertEqual(pool.strategy, FIRST)
        self.assertEqual(pool.exhaust, ldap_conn.LDAP_POOL_EXHAUST_SECONDS)
        self.assertTrue(pool.active)
        self.assertEqual(len(pool), 2)
        # Stessa configurazione = stesso oggetto: niente Server nuovo a ogni login.
        self.assertIs(ldap_conn.get_ldap_server(), pool)

    def test_start_tls_spenta_di_serie(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("LDAP_START_TLS", None)
            self.assertFalse(ldap_conn.ldap_start_tls_enabled())
        self.assertTrue(ldap_conn.ldap_transport_is_insecure())

    @override_settings(LDAP_START_TLS=True)
    def test_start_tls_server_con_certificato_verificato(self):
        import ssl

        server = ldap_conn.build_ldap_server("ldap://dc01.example.invalid", 2)
        self.assertIsNotNone(server.tls)
        self.assertEqual(server.tls.validate, ssl.CERT_REQUIRED)
        self.assertFalse(ldap_conn.ldap_transport_is_insecure())

    @override_settings(LDAP_START_TLS=True)
    def test_start_tls_prima_del_bind(self):
        conn = _conn(True, {"result": 0})
        conn.start_tls.return_value = True
        with mock.patch("ldap3.Connection", return_value=conn):
            got, _ = ldap_conn.ldap_bind([("u@example.invalid", SIMPLE)], "x")
        self.assertIs(got, conn)
        conn.open.assert_called_once()
        conn.start_tls.assert_called_once_with(read_server_info=False)
        names = [c[0] for c in conn.method_calls]
        self.assertLess(names.index("start_tls"), names.index("bind"))

    @override_settings(LDAP_START_TLS=True)
    def test_start_tls_fallito_nessun_bind(self):
        conn = _conn(True)
        conn.start_tls.return_value = False
        with mock.patch("ldap3.Connection", return_value=conn):
            got, _ = ldap_conn.ldap_bind([("u@example.invalid", SIMPLE), ("EX\\u", NTLM)], "x")
        self.assertIsNone(got)
        conn.bind.assert_not_called()
        conn.unbind.assert_called()


@override_settings(LDAP_SERVER="ldap://dc01.example.invalid", LDAP_TIMEOUT=2)
class LdapBindTests(_PulitoMixin, SimpleTestCase):
    def test_dc_irraggiungibile_interrompe_e_arma_breaker(self):
        with mock.patch("ldap3.Connection", side_effect=LDAPSocketOpenError("connection refused")) as cm:
            with self.assertRaises(ldap_conn.LDAPUnreachable):
                ldap_conn.ldap_bind([("a@example.invalid", SIMPLE), ("a", SIMPLE), ("EX\\a", NTLM)], "x")
        self.assertEqual(cm.call_count, 1, "con il DC giù non si provano gli altri metodi")
        self.assertTrue(ldap_conn.ldap_breaker_open())

    def test_bind_falliti_chiusi(self):
        c1, c2 = _conn(False, {"description": "invalidCredentials"}), _conn(False, {"description": "x"})
        with mock.patch("ldap3.Connection", side_effect=[c1, c2]):
            got, last = ldap_conn.ldap_bind([("a@example.invalid", SIMPLE), ("EX\\a", NTLM)], "x")
        self.assertIsNone(got)
        c1.unbind.assert_called_once()
        c2.unbind.assert_called_once()

    def test_stronger_auth_messaggio_chiaro(self):
        self.assertIn("LDAP_START_TLS", ldap_conn.describe_bind_failure(STRONGER_AUTH))
        self.assertEqual(ldap_conn.ad_bind_subcode(BAD_PWD_52E), "52e")


class LdapPagedSearchTests(SimpleTestCase):
    def _conn(self, items, result):
        c = mock.MagicMock()
        c.extend.standard.paged_search.return_value = iter(items)
        c.result = result
        return c

    def test_legge_tutte_le_pagine(self):
        items = [
            {"type": "searchResEntry", "dn": f"CN=u{i}", "attributes": {"sAMAccountName": [f"u{i}"]}}
            for i in range(1201)
        ] + [{"type": "searchResRef", "uri": ["ldap://x"]}]
        c = self._conn(items, {"result": 0, "description": "success"})
        rows = ldap_conn.ldap_paged_search(c, search_base="DC=EX", search_filter="(x=1)", attributes=["sAMAccountName"],
                                           paged_size=500)
        self.assertEqual(len(rows), 1201)
        self.assertTrue(c.extend.standard.paged_search.call_args.kwargs["generator"])
        c.search.assert_not_called()

    def test_lettura_incompleta_solleva(self):
        c = self._conn([{"type": "searchResEntry", "dn": "CN=a", "attributes": {}}], {"result": 51, "description": "busy"})
        with self.assertRaises(ldap_conn.LDAPIncompleteRead):
            ldap_conn.ldap_paged_search(c, search_base="DC=EX", search_filter="(x=1)", attributes=[])


@override_settings(
    LEGACY_AUTH_ENABLED=True,
    LDAP_ENABLED=True,
    LDAP_SERVER="ldap://dc01.example.invalid",
    LDAP_DOMAIN="EXAMPLE",
    LDAP_UPN_SUFFIX="@example.invalid",
    LDAP_TIMEOUT=2,
    LDAP_SERVICE_USER="svc@example.invalid",
    LDAP_SERVICE_PASSWORD="synthetic",
    LDAP_BASE_DN="DC=EXAMPLE,DC=INVALID",
)
class LdapBackendAffidabilitaTests(_PulitoMixin, TestCase):
    def test_breaker_attivo_salta_subito_il_backend(self):
        ldap_conn.ldap_breaker_trip("test")
        with mock.patch("ldap3.Connection") as cm, self.assertLogs("core.accounts.backends", "WARNING") as logs:
            self.assertIsNone(LDAPBackend().authenticate(None, username="mario.rossi", password="x"))
        cm.assert_not_called()
        self.assertIn("non raggiungibile", "\n".join(logs.output))

    def test_dc_giu_un_solo_tentativo_e_breaker(self):
        with mock.patch("ldap3.Connection", side_effect=LDAPSocketOpenError("timed out")) as cm:
            self.assertIsNone(LDAPBackend().authenticate(None, username="mario.rossi", password="x"))
            self.assertIsNone(LDAPBackend().authenticate(None, username="mario.rossi", password="x"))
        self.assertEqual(cm.call_count, 1, "il secondo login non riprova finché il breaker è attivo")

    @mock.patch("core.accounts.backends._md4_supported", return_value=True)
    def test_password_errata_52e_un_solo_bind(self, _md4):
        upn_conn = _conn(False, BAD_PWD_52E)
        with mock.patch("ldap3.Connection", return_value=upn_conn) as cm, mock.patch(
            "core.accounts.backends._account_ad_esiste", return_value=True
        ) as esiste:
            self.assertIsNone(LDAPBackend().authenticate(None, username="mario.rossi", password="sbagliata"))
        self.assertEqual(cm.call_count, 1, "niente NTLM dopo un 52e su account esistente")
        esiste.assert_called_once_with("mario.rossi@example.invalid")

    @mock.patch("core.accounts.backends._md4_supported", return_value=True)
    def test_52e_ma_upn_inesistente_prosegue(self, _md4):
        upn_conn = _conn(False, BAD_PWD_52E)
        alias_conn = _conn(False, {"result": 34, "description": "invalidDNSyntax"})
        ntlm_conn = _conn(True, {"result": 0})
        with mock.patch("ldap3.Connection", side_effect=[upn_conn, alias_conn, ntlm_conn]) as cm, mock.patch(
            "core.accounts.backends._account_ad_esiste", return_value=False
        ), mock.patch(
            "core.accounts.backends.resolve_ldap_identity", return_value=("mario.rossi@example.invalid", "Mario Rossi")
        ), mock.patch("core.accounts.backends.provision_legacy_user", return_value=None) as prov:
            LDAPBackend().authenticate(None, username="mario.rossi", password="giusta")
        self.assertEqual(cm.call_count, 3)
        self.assertEqual(cm.call_args_list[2].kwargs["authentication"], NTLM)
        prov.assert_called_once()

    def test_politica_dopo_bind_rifiutato(self):
        self.assertTrue(_prosegui_dopo_bind_rifiutato("a@example.invalid", SIMPLE, USER_NOT_FOUND_525))
        self.assertTrue(_prosegui_dopo_bind_rifiutato("a@example.invalid", SIMPLE, STRONGER_AUTH))
        self.assertTrue(_prosegui_dopo_bind_rifiutato("a@example.invalid", SIMPLE, None))
        locked = dict(BAD_PWD_52E, message="AcceptSecurityContext error, data 775, v4563")
        self.assertFalse(_prosegui_dopo_bind_rifiutato("a@example.invalid", SIMPLE, locked))
        with mock.patch("core.accounts.backends._account_ad_esiste", return_value=None):
            self.assertFalse(_prosegui_dopo_bind_rifiutato("a@example.invalid", SIMPLE, BAD_PWD_52E))

    def test_credenziali_giuste_login_invariato(self):
        ok_conn = _conn(True, {"result": 0})
        with mock.patch("ldap3.Connection", return_value=ok_conn) as cm, mock.patch(
            "core.accounts.backends.resolve_ldap_identity", return_value=("mario.rossi@example.invalid", "Mario Rossi")
        ), mock.patch("core.accounts.backends.provision_legacy_user", return_value=None) as prov:
            LDAPBackend().authenticate(None, username="mario.rossi@example.invalid", password="giusta")
        self.assertEqual(cm.call_count, 1)
        self.assertEqual(cm.call_args.kwargs["user"], "mario.rossi@example.invalid")
        prov.assert_called_once()
        ok_conn.unbind.assert_called_once()


@override_settings(
    LDAP_ENABLED=True,
    LDAP_SERVER="ldap://dc01.example.invalid",
    LDAP_SERVICE_USER="svc@example.invalid",
    LDAP_SERVICE_PASSWORD="synthetic",
    LDAP_BASE_DN="DC=EXAMPLE,DC=INVALID",
    LDAP_USER_FILTER="(objectClass=user)",
)
class SyncLdapPaginaTests(_PulitoMixin, SimpleTestCase):
    def test_lettura_incompleta_ferma_il_giro_prima_del_db(self):
        from core.management.commands.sync_ldap_users import Command

        c = _conn(True, {"result": 51, "description": "busy"})
        c.extend.standard.paged_search.return_value = iter([])
        with mock.patch("ldap3.Connection", return_value=c), mock.patch(
            "core.management.commands.sync_ldap_users.Ruolo"
        ) as ruolo:
            with self.assertRaisesMessage(CommandError, "Ricerca LDAP fallita"):
                Command().handle()
        ruolo.objects.filter.assert_not_called()
        c.unbind.assert_called_once()


class LegacyTableColumnsCacheTests(TestCase):
    def setUp(self):
        from core.legacy_utils import legacy_table_columns

        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)

    def test_errore_non_resta_in_cache(self):
        from core import legacy_utils

        with mock.patch.object(legacy_utils, "connections") as conns:
            conns.__getitem__.return_value.cursor.side_effect = RuntimeError("db giù")
            self.assertEqual(legacy_utils.legacy_table_columns("utenti"), set())
        cols = legacy_utils.legacy_table_columns("utenti")
        self.assertIn("email", cols, "dopo l'errore la lettura successiva va di nuovo sul database")
        # La lettura riuscita resta in cache e non è condivisa per riferimento.
        cols.add("finta")
        self.assertNotIn("finta", legacy_utils.legacy_table_columns("utenti"))
