"""
Contract test per core/graph_utils.py.

Lock the contract:
- token returned -> str
- error response (no access_token) -> RuntimeError con messaggio diagnostico
- nuova chiamata con cache calda -> niente nuova invocazione MSAL
"""
from __future__ import annotations

import unittest.mock as mock

from django.core.cache import cache
from django.test import TestCase

from core.contract_tests.base import load_cassette, skip_unless_live
from core.graph_utils import acquire_graph_token, invalidate_graph_token_cache


def _fake_msal_app(response_payload: dict):
    """Costruisce un mock della ConfidentialClientApplication MSAL."""
    fake_app = mock.MagicMock()
    fake_app.acquire_token_for_client.return_value = response_payload
    return fake_app


class GraphTokenContractTests(TestCase):
    TENANT = "synthetic-tenant-id"
    CLIENT_ID = "synthetic-client-id"
    CLIENT_SECRET = "synthetic-client-secret"

    def setUp(self):
        cache.clear()
        invalidate_graph_token_cache(self.TENANT, self.CLIENT_ID, self.CLIENT_SECRET)

    def test_token_ok_response_returns_string(self):
        cassette = load_cassette("graph_token_ok")
        fake_app = _fake_msal_app(cassette)
        with mock.patch(
            "msal.ConfidentialClientApplication", return_value=fake_app
        ):
            token = acquire_graph_token(self.TENANT, self.CLIENT_ID, self.CLIENT_SECRET)

        self.assertIsInstance(token, str)
        self.assertEqual(token, cassette["access_token"])
        # Lock the contract: i campi che il nostro codice usa devono esistere.
        self.assertIn("access_token", cassette)
        self.assertIn("expires_in", cassette)
        self.assertIsInstance(cassette["expires_in"], int)

    def test_token_error_response_raises_runtime_error(self):
        cassette = load_cassette("graph_token_invalid_secret")
        fake_app = _fake_msal_app(cassette)
        with mock.patch(
            "msal.ConfidentialClientApplication", return_value=fake_app
        ):
            with self.assertRaises(RuntimeError) as ctx:
                acquire_graph_token(self.TENANT, self.CLIENT_ID, self.CLIENT_SECRET)

        # Il messaggio diagnostico deve includere il payload di errore (per il triage).
        self.assertIn("invalid_client", str(ctx.exception))

    def test_second_call_uses_cache(self):
        cassette = load_cassette("graph_token_ok")
        fake_app = _fake_msal_app(cassette)
        with mock.patch(
            "msal.ConfidentialClientApplication", return_value=fake_app
        ):
            acquire_graph_token(self.TENANT, self.CLIENT_ID, self.CLIENT_SECRET)
            acquire_graph_token(self.TENANT, self.CLIENT_ID, self.CLIENT_SECRET)

        self.assertEqual(
            fake_app.acquire_token_for_client.call_count,
            1,
            "Token Graph deve essere riusato dalla cache al secondo accesso",
        )


class GraphMessagesShapeTests(TestCase):
    """Lock dei campi messaggio Graph che le automazioni si aspettano.

    Se Microsoft rinominasse o rimuovesse uno di questi campi, il test live
    fallirebbe e l'aggiornamento della cassetta evidenzierebbe la regressione
    in PR (rispetto alla cassetta precedente in git diff).
    """

    REQUIRED_FIELDS = ("id", "receivedDateTime", "subject", "from", "toRecipients", "isRead")

    def test_messages_value_array_contract(self):
        cassette = load_cassette("graph_messages_list_ok")
        self.assertIn("value", cassette)
        self.assertIsInstance(cassette["value"], list)
        self.assertGreaterEqual(len(cassette["value"]), 1)

        first = cassette["value"][0]
        for field in self.REQUIRED_FIELDS:
            self.assertIn(
                field,
                first,
                f"Campo richiesto '{field}' assente: contratto Graph cambiato?",
            )

    def test_from_address_structure(self):
        cassette = load_cassette("graph_messages_list_ok")
        first = cassette["value"][0]
        self.assertIn("emailAddress", first["from"])
        self.assertIn("address", first["from"]["emailAddress"])


# ──────────────────────────────────────────────────────────────────────────────
# Livello B — opt-in
# ──────────────────────────────────────────────────────────────────────────────

from django.test import tag  # noqa: E402 - tag importato qui per chiarezza
from django.conf import settings  # noqa: E402


@tag("live_integration")
@skip_unless_live()
class GraphLiveTokenTests(TestCase):
    """Tocca davvero MSAL/Azure. Richiede credenziali in env."""

    def test_acquire_token_live(self):
        tenant = (getattr(settings, "GRAPH_TENANT_ID", "") or "").strip()
        client_id = (getattr(settings, "GRAPH_CLIENT_ID", "") or "").strip()
        client_secret = (getattr(settings, "GRAPH_CLIENT_SECRET", "") or "").strip()
        if not (tenant and client_id and client_secret):
            self.skipTest("Credenziali Graph non configurate per il live test")

        cache.clear()
        invalidate_graph_token_cache(tenant, client_id, client_secret)
        token = acquire_graph_token(tenant, client_id, client_secret)
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 100, "Token Graph troppo corto: contratto rotto?")
