"""Regressioni dell'audit sicurezza 09/10 sulle automazioni (A6, M7, S1)."""
from __future__ import annotations

import socket
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from automazioni.services import (
    AutomationSafetyError,
    discover_module_tables,
    is_protected_table,
    validate_http_action_target,
    validate_target_table_and_fields,
)


class ProtectedTablesTests(SimpleTestCase):
    """Audit A6: nessuna regola scrive su ACL, profili, audit o automazioni."""

    def test_acl_and_auth_tables_are_protected(self):
        for table in (
            "core_userpermissiongrant",
            "core_rolepermissiongrant",
            "core_routepermissionbinding",
            "core_profile",
            "core_auditlog",
            "automazioni_automationtableconfig",
            "auth_user",
            "twofa_usertwofactor",
            "utenti",
            "ruoli",
            "permessi",
            "pulsanti",
            "",
        ):
            self.assertTrue(is_protected_table(table), table)

    def test_module_tables_stay_writable(self):
        for table in ("core_notifica", "tasks_task", "anagrafica_dipendenti", "tickets_ticket"):
            self.assertFalse(is_protected_table(table), table)

    def test_runtime_rejects_protected_table_even_if_whitelisted(self):
        whitelist = {
            "insert_record": {"core_userpermissiongrant": {"fields": {"user_id"}, "where_fields": set()}},
            "update_record": {},
        }
        with patch("automazioni.services.get_action_table_whitelist", return_value=whitelist):
            with self.assertRaises(AutomationSafetyError):
                validate_target_table_and_fields("insert_record", "core_userpermissiongrant", ["user_id"])

    def test_picker_does_not_offer_protected_tables(self):
        tables = discover_module_tables()
        self.assertNotIn("core_userpermissiongrant", tables)
        self.assertNotIn("core_profile", tables)
        self.assertIn("core_notifica", tables)


def _fake_resolve(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


class HttpActionSsrfTests(SimpleTestCase):
    """Audit M7: niente richieste verso loopback, metadati cloud o LAN non autorizzata."""

    def _check(self, url: str, ip: str):
        with patch("socket.getaddrinfo", return_value=_fake_resolve(ip)):
            validate_http_action_target(url)

    def test_loopback_and_link_local_always_blocked(self):
        for ip in ("127.0.0.1", "169.254.169.254", "0.0.0.0"):
            with self.assertRaises(AutomationSafetyError, msg=ip):
                self._check("https://example.com/hook", ip)

    @override_settings(AUTOMATION_HTTP_ALLOWED_HOSTS=[])
    def test_private_network_blocked_by_default(self):
        with self.assertRaises(AutomationSafetyError):
            self._check("http://intranet.local/api", "10.0.0.5")

    @override_settings(AUTOMATION_HTTP_ALLOWED_HOSTS=["*.local"])
    def test_private_network_allowed_for_listed_host(self):
        self._check("http://intranet.local/api", "10.0.0.5")

    @override_settings(AUTOMATION_HTTP_ALLOWED_HOSTS=["*.local"])
    def test_allowlist_does_not_open_loopback(self):
        with self.assertRaises(AutomationSafetyError):
            self._check("http://intranet.local/api", "127.0.0.1")

    def test_public_address_allowed(self):
        self._check("https://example.com/hook", "93.184.216.34")

    def test_perform_http_request_disables_redirects(self):
        from automazioni import services

        with patch("socket.getaddrinfo", return_value=_fake_resolve("93.184.216.34")), \
             patch.object(services.requests, "request") as fake_request:
            services._perform_http_request(
                method="POST", url="https://example.com/hook", headers={}, body=None, timeout_seconds=5,
            )
        self.assertIs(fake_request.call_args.kwargs["allow_redirects"], False)
