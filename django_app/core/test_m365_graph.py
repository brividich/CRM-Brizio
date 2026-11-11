"""core.m365_graph: errori leggibili, retry, letture troncate (rete sempre simulata)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from core import graph_utils, m365_graph

URL_GRAPH = f"{m365_graph.GRAPH}/users"
URL_DEFENDER = f"{m365_graph.DEFENDER_API}/machines"


def _resp(status=200, payload=None, *, tipo="application/json", headers=None, json_rotto=False):
    r = MagicMock()
    r.status_code = status
    r.headers = {"Content-Type": tipo, **(headers or {})}
    if json_rotto:
        r.json.side_effect = ValueError("non JSON")
    else:
        r.json.return_value = payload if payload is not None else {}
    r.content = b"x"
    return r


class GetTests(SimpleTestCase):
    def setUp(self):
        self.sessione = MagicMock()
        patcher = patch.object(m365_graph, "_sessione", return_value=self.sessione)
        patcher.start()
        self.addCleanup(patcher.stop)
        dormi = patch.object(m365_graph, "_dormi")
        self.dormi = dormi.start()
        self.addCleanup(dormi.stop)
        for nome in ("_invalida_token",):
            p = patch.object(m365_graph, nome)
            p.start()
            self.addCleanup(p.stop)

    def test_errore_di_rete_diventa_graph_error_con_host(self):
        self.sessione.get.side_effect = requests.ConnectionError("rifiutata")
        with self.assertRaises(m365_graph.GraphError) as ctx:
            m365_graph.get(URL_GRAPH, permesso="User.Read.All", tok="t")
        self.assertIn("graph.microsoft.com", str(ctx.exception))

    def test_200_non_json_dice_chi_risponde(self):
        self.sessione.get.return_value = _resp(200, tipo="text/html", headers={"Server": "proxy-sintetico"},
                                               json_rotto=True)
        with self.assertRaises(m365_graph.GraphError) as ctx:
            m365_graph.get(URL_GRAPH, permesso="x", tok="t")
        self.assertIn("senza JSON", str(ctx.exception))
        self.assertIn("proxy-sintetico", str(ctx.exception))

    def test_401_parla_di_token_403_di_permesso_con_codice(self):
        self.sessione.get.return_value = _resp(401, {"error": {"code": "InvalidAuthenticationToken"}})
        with self.assertRaises(m365_graph.GraphError) as ctx:
            m365_graph.get(URL_GRAPH, permesso="User.Read.All", tok="t")
        self.assertIn("token", str(ctx.exception))
        self.assertIn("InvalidAuthenticationToken", str(ctx.exception))
        self.assertNotIn("User.Read.All", str(ctx.exception))

        self.sessione.get.return_value = _resp(403, {"error": {"code": "Authorization_RequestDenied"}})
        with self.assertRaises(m365_graph.GraphError) as ctx:
            m365_graph.get(URL_GRAPH, permesso="User.Read.All", tok="t")
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("User.Read.All", str(ctx.exception))
        self.assertIn("Authorization_RequestDenied", str(ctx.exception))

    def test_api_defender_non_si_chiama_graph(self):
        self.sessione.get.return_value = _resp(403, {"error": {"code": "Forbidden"}})
        with self.assertRaises(m365_graph.GraphError) as ctx:
            m365_graph.get(URL_DEFENDER, permesso="Machine.Read.All", tok="t")
        self.assertIn("Defender for Endpoint", str(ctx.exception))
        self.assertFalse(str(ctx.exception).startswith("Graph"))

    def test_retry_su_429_rispetta_retry_after_con_tetto(self):
        self.sessione.get.side_effect = [_resp(429, headers={"Retry-After": "120"}), _resp(503), _resp(200, {"ok": 1})]
        self.assertEqual(m365_graph.get(URL_GRAPH, permesso="x", tok="t"), {"ok": 1})
        self.assertEqual(self.sessione.get.call_count, 3)
        attese = [c.args[0] for c in self.dormi.call_args_list]
        self.assertEqual(attese[0], m365_graph.RETRY_ATTESA_MAX)  # 120 s chiesti, 10 concessi

    def test_retry_al_massimo_tre_volte(self):
        self.sessione.get.return_value = _resp(504)
        with self.assertRaises(m365_graph.GraphError) as ctx:
            m365_graph.get(URL_GRAPH, permesso="x", tok="t")
        self.assertEqual(ctx.exception.status, 504)
        self.assertEqual(self.sessione.get.call_count, m365_graph.RETRY_MAX + 1)

    def test_get_all_segnala_lettura_troncata(self):
        pagina = {"value": [{"id": "a"}], "@odata.nextLink": f"{URL_GRAPH}?$skiptoken=x"}
        self.sessione.get.return_value = _resp(200, pagina)
        with patch.object(m365_graph, "_token_per", return_value="t"):
            elenco = m365_graph.get_all(URL_GRAPH, permesso="x", max_pages=2)
        self.assertEqual(len(elenco), 2)
        self.assertTrue(m365_graph.troncata(elenco))
        self.assertTrue(elenco.prossimo_link)

    def test_get_all_completa_non_troncata(self):
        self.sessione.get.side_effect = [
            _resp(200, {"value": [{"id": "a"}], "@odata.nextLink": f"{URL_GRAPH}?$skiptoken=x"}),
            _resp(200, {"value": [{"id": "b"}]}),
        ]
        with patch.object(m365_graph, "_token_per", return_value="t"):
            elenco = m365_graph.get_all(URL_GRAPH, permesso="x", max_pages=2)
        self.assertEqual([e["id"] for e in elenco], ["a", "b"])
        self.assertFalse(m365_graph.troncata(elenco))
        self.assertFalse(m365_graph.troncata([{"id": "lista qualunque"}]))

    def test_scrivi_ripete_solo_429(self):
        self.sessione.request.side_effect = [_resp(429), _resp(201, {"id": "ev"})]
        with patch.object(m365_graph, "token", return_value="t"):
            self.assertEqual(m365_graph.scrivi("POST", URL_GRAPH, permesso="x", json={}), (201, {"id": "ev"}))
        self.sessione.request.reset_mock(side_effect=True)
        self.sessione.request.return_value = _resp(503)
        with patch.object(m365_graph, "token", return_value="t"), self.assertRaises(m365_graph.GraphError):
            m365_graph.scrivi("POST", URL_GRAPH, permesso="x", json={})
        self.assertEqual(self.sessione.request.call_count, 1)  # una scrittura su 503 non si ripete


class ErroreTokenTests(SimpleTestCase):
    def test_codice_aadsts_senza_dump(self):
        risultato = {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret. Trace ID: x",
                     "trace_id": "t", "correlation_id": "c"}
        testo = graph_utils.descrivi_errore_token(risultato)
        self.assertIn("invalid_client", testo)
        self.assertIn("AADSTS7000215", testo)
        self.assertIn("segreto", testo)
        self.assertNotIn("Trace ID", testo)

    def test_token_non_ottenuto_diventa_graph_error(self):
        with patch.object(m365_graph, "configurato", return_value=True), \
             patch.object(m365_graph, "credenziali", return_value={"tenant_id": "t", "client_id": "c", "client_secret": "s"}), \
             patch("core.graph_utils.acquire_graph_token", side_effect=RuntimeError("Token Graph non ottenuto: invalid_client")):
            with self.assertRaises(m365_graph.GraphError):
                m365_graph.token()
