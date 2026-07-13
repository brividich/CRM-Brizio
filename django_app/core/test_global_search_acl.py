from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from core import views


class GlobalSearchModuleGateTests(SimpleTestCase):
    """api_global_search non deve esporre dati di moduli a cui l'utente non ha
    accesso ACL: ogni blocco è eseguito solo se _global_search_module_allowed()
    è vero. Regressione per la data-exposure cross-modulo (anagrafica/DPI/ticket/
    KICK-OFF/procedure) verso qualsiasi utente autenticato."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _req(self, q="ab", superuser=False):
        request = self.factory.get(f"/api/search/?q={q}")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=superuser)
        return request

    def test_helper_superuser_short_circuits_without_acl_call(self):
        with patch("core.acl_v2.resolve_acl_access") as mock_resolve:
            self.assertTrue(
                views._global_search_module_allowed(self._req(superuser=True), "/dpi/gestione/")
            )
            mock_resolve.assert_not_called()

    def test_helper_delegates_to_acl_for_non_superuser(self):
        req = self._req(superuser=False)
        with patch("core.legacy_utils.get_legacy_user", return_value=SimpleNamespace()), \
             patch("core.acl_v2.resolve_acl_access", return_value={"allowed": False}) as mock_resolve:
            self.assertFalse(views._global_search_module_allowed(req, "/dpi/gestione/"))
            mock_resolve.assert_called_once()
        # Seconda chiamata stesso path: usa la cache per-request (no nuova resolve)
        with patch("core.acl_v2.resolve_acl_access") as mock_resolve2:
            self.assertFalse(views._global_search_module_allowed(req, "/dpi/gestione/"))
            mock_resolve2.assert_not_called()

    def test_search_returns_no_results_when_all_modules_denied(self):
        # Con il gate che nega ogni modulo, la ricerca non espone nulla, anche se
        # i blocchi venissero eseguiti: tutti i blocchi sono saltati.
        with patch("core.views._global_search_module_allowed", return_value=False) as gate:
            resp = views.api_global_search(self._req(q="ab", superuser=False))
        payload = json.loads(resp.content)
        self.assertEqual(payload["results"], [])
        # Il gate è stato interrogato (almeno per un modulo) → wiring presente.
        self.assertTrue(gate.called)

    def test_short_query_skips_gate(self):
        with patch("core.views._global_search_module_allowed") as gate:
            resp = views.api_global_search(self._req(q="a", superuser=False))
        self.assertEqual(json.loads(resp.content)["results"], [])
        gate.assert_not_called()
