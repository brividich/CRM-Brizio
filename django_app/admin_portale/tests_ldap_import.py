"""«Importa da LDAP»: tutte le pagine della ricerca e filtro LDAP escapato (ldap3 mockato, dati sintetici)."""
from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from admin_portale.views import _helpers
from admin_portale.views import utenti as utenti_views


def _entry(i: int) -> dict:
    return {
        "type": "searchResEntry",
        "dn": f"CN=Utente {i},DC=EXAMPLE,DC=INVALID",
        "attributes": {
            "userPrincipalName": [f"utente{i}@example.invalid"],
            "sAMAccountName": [f"utente{i}"],
            "displayName": [f"Utente {i}"],
            "memberOf": [],
        },
    }


@override_settings(
    LDAP_ENABLED=True,
    LDAP_SERVER="ldap://dc01.example.invalid",
    LDAP_SERVICE_USER="svc@example.invalid",
    LDAP_BASE_DN="DC=EXAMPLE,DC=INVALID",
    LDAP_USER_FILTER="(objectClass=user)",
    LDAP_SYNC_PAGE_SIZE=500,
)
class LdapImportRicercaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin-ldap-test", "admin.ldap@example.invalid", "x")
        self.factory = RequestFactory()
        patches = [
            mock.patch.object(_helpers, "_effective_env_value", side_effect=lambda key, default="": str(default or "")),
            mock.patch.object(_helpers, "_effective_env_int", side_effect=lambda key, default=0: default),
            mock.patch.object(_helpers, "_effective_env_bool", side_effect=lambda key, default=False: default),
            mock.patch.object(utenti_views, "_ldap_effective_service_password", return_value="synthetic"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _post(self, data):
        request = self.factory.post("/admin-portale/utenti/ldap-import/", data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        request.user = self.user
        request.legacy_user = None
        return utenti_views.ldap_import_utenti(request)

    def _conn(self, items, result=None):
        conn = mock.MagicMock()
        conn.extend.standard.paged_search.return_value = iter(items)
        conn.result = result or {"result": 0, "description": "success"}
        return conn

    def test_ricerca_legge_tutte_le_pagine_e_escapa_il_termine(self):
        conn = self._conn([_entry(i) for i in range(1203)])
        with mock.patch("core.ldap_conn.ldap_service_bind", return_value=(conn, None)):
            response = self._post({"action": "search", "q": "ro*ssi)(cn=*"})
        self.assertEqual(response.status_code, 200, response.content)
        payload = json.loads(response.content)
        self.assertEqual(payload["total"], 1203, "prima si leggeva solo la prima pagina")
        filtro = conn.extend.standard.paged_search.call_args.kwargs["search_filter"]
        self.assertIn("(displayName=*ro\\2assi\\29\\28cn=\\2a*)", filtro)
        self.assertNotIn("(cn=*", filtro)
        conn.search.assert_not_called()
        conn.unbind.assert_called_once()

    def test_ricerca_incompleta_errore_json(self):
        conn = self._conn([_entry(1)], {"result": 51, "description": "busy"})
        with mock.patch("core.ldap_conn.ldap_service_bind", return_value=(conn, None)):
            response = self._post({"action": "search", "q": "rossi"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("incompleta", json.loads(response.content)["error"])

    def test_import_email_escapate_nel_filtro(self):
        conn = self._conn([])
        with mock.patch("core.ldap_conn.ldap_service_bind", return_value=(conn, None)), mock.patch(
            "core.legacy_utils.legacy_table_columns", return_value=set()
        ):
            response = self._post({"action": "import", "emails[]": ["a*)(mail=*@example.invalid"]})
        self.assertEqual(response.status_code, 200, response.content)
        filtro = conn.extend.standard.paged_search.call_args.kwargs["search_filter"]
        self.assertIn("(userPrincipalName=a\\2a\\29\\28mail=\\2a@example.invalid)", filtro)
