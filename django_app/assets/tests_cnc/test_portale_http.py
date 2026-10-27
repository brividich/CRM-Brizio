"""Il client HTTP del collector (``portale.py``) contro un server HTTP locale: elenco, invii, errori."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest import mock

from assets.collector_cnc import collector, portale


class _Gestore(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *a: Any) -> None:   # niente righe di accesso nei test
        pass

    def _rispondi(self, codice: int, corpo: dict[str, Any]) -> None:
        dati = json.dumps(corpo).encode()
        self.send_response(codice)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dati)))
        self.end_headers()
        self.wfile.write(dati)

    def do_GET(self) -> None:
        self.server.richieste.append(("GET", self.path, self.headers.get("Authorization"), None))
        self._rispondi(self.server.codice, {"machines": [{"name": "DM6", "ip": "192.0.2.115"}, "rotta"]})

    def do_POST(self) -> None:
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.richieste.append(("POST", self.path, self.headers.get("Authorization"), corpo))
        righe = corpo.get("macchine") or corpo.get("readings") or []
        self._rispondi(self.server.codice, {"results": [{"asset_tag": r.get("asset_tag"), "status": "rejected", "reason": "prova"}
                                                        for r in righe[:1]]})


class _Server(ThreadingHTTPServer):
    richieste: list[tuple[str, str, str | None, Any]]
    codice: int


class PortaleHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _Server(("127.0.0.1", 0), _Gestore)
        self.server.richieste, self.server.codice = [], 200
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.p = portale.Portale(self.url + "/", "token-sintetico", [], collector.prog_name)

    def test_elenco_delle_macchine(self) -> None:
        self.assertEqual(self.p.scarica_macchine(), [{"name": "DM6", "ip": "192.0.2.115"}])
        self.assertEqual(self.server.richieste[0][1:3], (portale.URL_CONFIG, "Bearer token-sintetico"))
        self.server.codice = 401
        with self.assertLogs("collector.portale", "WARNING") as cm:
            self.assertIsNone(self.p.scarica_macchine())
            self.assertIsNone(self.p.scarica_macchine())   # stesso errore: una riga sola
        self.assertEqual(len(cm.output), 1)
        self.assertIn("token o rete non ammessi", cm.output[0])

    def test_invii_ed_errori(self) -> None:
        corpo = {"macchine": [{"asset_tag": "CNC-1", "stato": "LAVORO"}]}
        with self.assertLogs("collector.portale", "WARNING") as cm:
            self.assertTrue(asyncio.run(self.p.invia(portale.URL_STATO, corpo)))
        self.assertIn("CNC-1 scartata (prova)", cm.output[0])
        self.assertEqual(self.server.richieste[-1][3], corpo)
        self.server.codice = 500
        with self.assertLogs("collector.portale", "WARNING"):
            self.assertFalse(asyncio.run(self.p.invia(portale.URL_STATO, corpo)))
        self.server.codice = 200
        with self.assertLogs("collector.portale", "INFO") as cm:
            self.assertTrue(asyncio.run(self.p.invia(portale.URL_STATO, corpo)))
        self.assertTrue(any("di nuovo raggiungibile" in r for r in cm.output))

    def test_portale_spento(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        spento = portale.Portale("http://127.0.0.1:9", "t", [], collector.prog_name)
        with self.assertLogs("collector.portale", "WARNING"):
            self.assertIsNone(spento.scarica_macchine())
            self.assertFalse(asyncio.run(spento.invia(portale.URL_STATO, {"macchine": []})))
        self.addCleanup(lambda: None)

    def test_da_ambiente(self) -> None:
        with mock.patch.dict(os.environ, {"PORTALE_URL": "", "PORTALE_TOKEN": ""}):
            self.assertIsNone(portale.Portale.da_ambiente([], collector.prog_name))
        with mock.patch.dict(os.environ, {"PORTALE_URL": self.url, "PORTALE_TOKEN": "t", "PORTALE_CA": ""}):
            p = portale.Portale.da_ambiente([], collector.prog_name)
        self.assertIsNotNone(p)

    def test_senza_coda_si_invia_come_prima(self) -> None:
        """Uso diretto (senza machines.db): stato e contatori partono subito, come nella versione precedente."""
        m = mock.Mock(asset_tag="CNC-9", state="LAVORO", state_since=collector.utcnow(), counters_at=collector.utcnow(),
                      alarms={}, values={"cnt_parts_overall": 5}, ombra=False, portale_cambiata=True,
                      found_serial="", data_model="lsv2", errore="", hours_unit="")
        m.spec = None   # (spec= nel costruttore di Mock è un'altra cosa)
        m.programma.return_value = "P1"
        m.modalita.return_value = "AUTO"
        m.esecuzione.return_value = "RUNNING"
        p = portale.Portale(self.url, "t", [m], collector.prog_name)

        async def giro() -> None:
            with mock.patch.object(portale, "INVIO_CAMBI", 0.01):
                task = asyncio.create_task(p.run())
                while len(self.server.richieste) < 2:
                    await asyncio.sleep(0.01)
                task.cancel()

        logging.getLogger("collector.portale").disabled = True
        self.addCleanup(lambda: setattr(logging.getLogger("collector.portale"), "disabled", False))
        asyncio.run(giro())
        percorsi = [r[1] for r in self.server.richieste]
        self.assertEqual(set(percorsi[:2]), {portale.URL_STATO, portale.URL_CONTATORI})
        stato = next(r[3] for r in self.server.richieste if r[1] == portale.URL_STATO)
        self.assertEqual(stato["macchine"][0]["modalita"], "AUTO")
        self.assertEqual(portale.fattore_ore(m), None)
