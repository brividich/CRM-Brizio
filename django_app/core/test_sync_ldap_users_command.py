from __future__ import annotations

from io import StringIO
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from django.core.management import call_command
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
        self.assertIs(fake_ldap3.Connection.call_args.kwargs["auto_bind"], False)
        self.assertIs(fake_ldap3.Connection.call_args.kwargs["auto_referrals"], False)
        fake_conn.unbind.assert_called_once()

    def test_plain_service_user_falls_back_to_ntlm_without_auto_bind(self):
        class FakeLDAPException(Exception):
            pass

        class FakeLDAPSocketOpenError(FakeLDAPException):
            pass

        simple_conn = MagicMock()
        simple_conn.bind.return_value = False
        simple_conn.result = {"description": "invalidCredentials"}
        ntlm_conn = MagicMock()
        ntlm_conn.bind.return_value = True
        ntlm_conn.search.side_effect = FakeLDAPSocketOpenError("stop after ntlm bind")

        fake_ldap3 = ModuleType("ldap3")
        fake_ldap3.NONE = "NONE"
        fake_ldap3.NTLM = "NTLM"
        fake_ldap3.SIMPLE = "SIMPLE"
        fake_ldap3.SUBTREE = "SUBTREE"
        fake_ldap3.Connection = MagicMock(side_effect=[simple_conn, ntlm_conn])
        fake_ldap3.Server = MagicMock(return_value=object())

        fake_ldap3_core = ModuleType("ldap3.core")
        fake_ldap3_exceptions = ModuleType("ldap3.core.exceptions")
        fake_ldap3_exceptions.LDAPException = FakeLDAPException
        fake_ldap3_exceptions.LDAPSocketOpenError = FakeLDAPSocketOpenError

        with override_settings(
            LDAP_SERVICE_USER="svc_ldap",
            LDAP_UPN_SUFFIX="",
        ), self.assertRaisesMessage(
            CommandError,
            "Ricerca LDAP fallita: stop after ntlm bind",
        ), patch.dict(
            sys.modules,
            {
                "ldap3": fake_ldap3,
                "ldap3.core": fake_ldap3_core,
                "ldap3.core.exceptions": fake_ldap3_exceptions,
            },
            clear=False,
        ):
            Command().handle()

        self.assertEqual(fake_ldap3.Connection.call_count, 2)
        first_call, second_call = fake_ldap3.Connection.call_args_list
        self.assertEqual(first_call.kwargs["user"], "svc_ldap")
        self.assertEqual(first_call.kwargs["authentication"], "SIMPLE")
        self.assertIs(first_call.kwargs["auto_bind"], False)
        self.assertEqual(second_call.kwargs["user"], "EXAMPLE\\svc_ldap")
        self.assertEqual(second_call.kwargs["authentication"], "NTLM")
        self.assertIs(second_call.kwargs["auto_bind"], False)
        simple_conn.unbind.assert_called_once()
        ntlm_conn.unbind.assert_called_once()

    def test_no_such_object_search_error_suggests_domain_root(self):
        class FakeLDAPException(Exception):
            pass

        class FakeLDAPSocketOpenError(FakeLDAPException):
            pass

        fake_conn = MagicMock()
        fake_conn.bind.return_value = True
        fake_conn.search.return_value = False
        fake_conn.result = {
            "result": 32,
            "description": "noSuchObject",
            "message": "0000208D: NameErr",
        }

        fake_ldap3 = ModuleType("ldap3")
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

        with self.assertRaisesMessage(
            CommandError,
            "Base DN non trovato (OU=Utenti_Novicrom,DC=CNOVICROM,DC=LOCAL)",
        ) as ctx, patch.dict(
            sys.modules,
            {
                "ldap3": fake_ldap3,
                "ldap3.core": fake_ldap3_core,
                "ldap3.core.exceptions": fake_ldap3_exceptions,
            },
            clear=False,
        ):
            Command().handle(search_base="OU=Utenti_Novicrom,DC=CNOVICROM,DC=LOCAL")

        self.assertIn("ad esempio DC=CNOVICROM,DC=LOCAL", str(ctx.exception))
        fake_conn.unbind.assert_called_once()

    def test_call_command_accepts_internal_config_overrides(self):
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

        with override_settings(
            LDAP_ENABLED=False,
            LDAP_SERVER="",
            LDAP_UPN_SUFFIX="",
            LDAP_SERVICE_USER="",
            LDAP_SERVICE_PASSWORD="",
            LDAP_BASE_DN="",
            LDAP_USER_FILTER="",
        ), self.assertRaisesMessage(
            CommandError,
            "Ricerca LDAP fallita: invalid server address",
        ), patch.dict(
            sys.modules,
            {
                "ldap3": fake_ldap3,
                "ldap3.core": fake_ldap3_core,
                "ldap3.core.exceptions": fake_ldap3_exceptions,
            },
            clear=False,
        ):
            call_command(
                "sync_ldap_users",
                ldap_enabled=True,
                server="ldap://override.example.local",
                domain="OVERRIDE",
                timeout=7,
                service_user="svc_override",
                service_password="override-secret",
                search_base="DC=OVERRIDE,DC=LOCAL",
                user_filter="(objectClass=user)",
                page_size=640,
                stdout=StringIO(),
            )

        fake_ldap3.Server.assert_called_once_with(
            "ldap://override.example.local",
            connect_timeout=7,
            get_info="NONE",
        )
        self.assertEqual(fake_ldap3.Connection.call_args.kwargs["user"], "svc_override")
        self.assertEqual(fake_ldap3.Connection.call_args.kwargs["password"], "override-secret")
        self.assertIs(fake_ldap3.Connection.call_args.kwargs["auto_bind"], False)
