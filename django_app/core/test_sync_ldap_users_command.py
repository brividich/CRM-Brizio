from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core.management.commands.sync_ldap_users import Command


@override_settings(
    LDAP_ENABLED=True,
    LDAP_SERVER="ldap://dc1.example.local",
    LDAP_DOMAIN="EXAMPLE",
    LDAP_TIMEOUT=5,
    LDAP_SERVICE_USER="svc_ldap@example.local",
    LDAP_SERVICE_PASSWORD="secret",
    LDAP_BASE_DN="DC=EXAMPLE,DC=LOCAL",
    LDAP_USER_FILTER="(&(objectCategory=person)(objectClass=user))",
    LDAP_GROUP_ALLOWLIST=["EMPLOYEES"],
)
class SyncLdapUsersCommandTests(SimpleTestCase):
    def test_search_error_is_wrapped_and_auto_referrals_disabled(self):
        class FakeLDAPException(Exception):
            pass

        class FakeLDAPSocketOpenError(FakeLDAPException):
            pass

        fake_conn = MagicMock()
        fake_conn.bind.return_value = True
        fake_conn.search.side_effect = FakeLDAPSocketOpenError("invalid server address")

        fake_ldap3 = ModuleType("ldap3")
        fake_ldap3.AUTO_BIND_NO_TLS = "AUTO_BIND_NO_TLS"
        fake_ldap3.NONE = "NONE"
        fake_ldap3.NTLM = "NTLM"
        fake_ldap3.SIMPLE = "SIMPLE"
        fake_ldap3.SUBTREE = "SUBTREE"
        fake_ldap3.Connection = MagicMock(return_value=fake_conn)
        fake_ldap3.Server = MagicMock(return_value=object())

        fake_ldap3_core = ModuleType("ldap3.core")
        fake_ldap3_exceptions = ModuleType("ldap3.core.exceptions")
        fake_ldap3_exceptions.LDAPException = FakeLDAPException
        fake_ldap3_exceptions.LDAPSocketOpenError = FakeLDAPSocketOpenError

        with self.assertRaisesMessage(CommandError, "Ricerca LDAP fallita: invalid server address"), patch.dict(
            sys.modules,
            {
                "ldap3": fake_ldap3,
                "ldap3.core": fake_ldap3_core,
                "ldap3.core.exceptions": fake_ldap3_exceptions,
            },
            clear=False,
        ):
            Command().handle()

        self.assertEqual(fake_ldap3.Connection.call_count, 1)
        self.assertIs(fake_ldap3.Connection.call_args.kwargs["auto_referrals"], False)
        fake_conn.unbind.assert_called_once()
