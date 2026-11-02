"""Riga di comando: --check-config, --once, --browse, --jsonl, log silenzioso, avvio rifiutato."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from assets.collector_cnc import cli, collector, esplora, lavoratore, sink
from assets.tests_cnc.finti import FwlibFinta, PgmState, StatoLsv2, modulo_lsv2
from assets.tests_cnc.sim_opcua import CncSimulata

ESEMPIO = Path(cli.__file__).resolve().parent / "machines.example.json"


def _scrivi(cartella: str, dati: dict[str, Any]) -> Path:
    p = Path(cartella) / "machines.json"
    p.write_text(json.dumps(dati), encoding="utf-8")
    return p


def _esegui(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        codice = cli.esegui(argv)
    return codice, out.getvalue(), err.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.cartella = tempfile.mkdtemp(prefix="cnc_cli_")
        radice = logging.getLogger()
        stato = (list(radice.handlers), radice.level)

        def ripristina() -> None:
            for h in list(radice.handlers):
                radice.removeHandler(h)
                h.close()
            for h in stato[0]:
                radice.addHandler(h)
            radice.setLevel(stato[1])
            for n in ("asyncua", "collector"):
                logging.getLogger(n).setLevel(logging.NOTSET)

        self.addCleanup(ripristina)
        logging.getLogger("asyncua").setLevel(logging.CRITICAL)


class CheckConfigTests(_Base):
    def test_esempio_valido(self) -> None:
        with mock.patch.dict(os.environ, {"CNC_FWLIB_PATH": ""}):
            codice, out, _err = _esegui(["--config", str(ESEMPIO), "--check-config"])
        self.assertEqual(codice, 0, out)
        self.assertIn("configurazione valida", out)
        nomi = [m["name"] for m in json.loads(ESEMPIO.read_text(encoding="utf-8"))["machines"]]
        for pilota in ("DM6", "DM6-MDC", "AGV1", "HYUNDAI"):
            self.assertIn(pilota, nomi)

    def test_errori_chiari(self) -> None:
        p = _scrivi(self.cartella, {"machines": [
            {"name": "A", "driver": "siemens", "ip": "192.0.2.1"},
            {"name": "B", "driver": "lsv2", "ip": "192.0.2.2", "poll_seconds": 0.5},
            {"name": "C", "driver": "lsv2", "ip": "192.0.2.2"},
            {"name": "C", "driver": "opcua", "ip": "non valido!"},
            {"name": "D", "driver": "opcua", "ip": "192.0.2.4", "password": "in-chiaro"},
            {"name": "E", "driver": "opcua", "ip": "192.0.2.5", "password_env": "CNC_TEST_MANCANTE"},
            {"name": "F", "driver": "focas", "ip": "192.0.2.6", "fwlib_path": "Z:/non/esiste/Fwlib64.dll"},
            {"name": "G", "driver": "opcua", "ip": "192.0.2.7", "nodes": {"program": "ns=2;s=P", "boh": "x"}},
            {"name": "H", "driver": "opcua", "ip": "192.0.2.8", "execution_map": {"1": "CORRE"}},
        ]})
        codice, out, _err = _esegui(["--config", str(p), "--check-config"])
        self.assertEqual(codice, 1)
        for atteso in ("driver «siemens» sconosciuto", "sotto il minimo di 2 s", "stesso indirizzo e porta di «B»",
                       "nome duplicato", "indirizzo «non valido!»", "password in chiaro", "CNC_TEST_MANCANTE non impostata",
                       "Fwlib non trovata", "nodes.boh sconosciuto", "nodes senza «exec»", "execution_map.1 = 'CORRE'"):
            self.assertIn(atteso, out)

    def test_servizio_non_parte_con_errori(self) -> None:
        p = _scrivi(self.cartella, {"machines": [{"name": "A", "driver": "siemens", "ip": "192.0.2.1"}]})
        codice, _out, err = _esegui(["--config", str(p)])
        self.assertEqual(codice, 2)
        self.assertIn("non avviato", err)
        log = (Path(self.cartella) / "collector.log").read_text(encoding="utf-8")
        self.assertIn("collector NON avviato", log)

    def test_file_rotto(self) -> None:
        p = Path(self.cartella) / "machines.json"
        p.write_text("{rotto", encoding="utf-8")
        self.assertEqual(_esegui(["--config", str(p), "--check-config"])[0], 1)
        p.write_text("[]", encoding="utf-8")
        self.assertEqual(_esegui(["--config", str(p), "--check-config"])[0], 1)


class OnceTests(_Base):
    def test_once_lsv2_e_focas(self) -> None:
        st, lib = StatoLsv2(), FwlibFinta()
        st.programma = PgmState.STARTED
        lib.run = 3
        p = _scrivi(self.cartella, {"machines": [
            {"name": "AGV1", "driver": "lsv2", "ip": "192.0.2.105"},
            {"name": "HYUNDAI", "driver": "focas", "ip": "192.0.2.117"},
            {"name": "DM6", "driver": "lsv2", "ip": "192.0.2.114", "enabled": False}]})

        def lsv2_finto(m: collector.MacchinaSincrona) -> Any:
            from assets.collector_cnc.drivers.lsv2 import DriverLsv2

            return DriverLsv2(m.name, m.ip, log=m.log, modulo=modulo_lsv2(st))

        def focas_finto(m: collector.MacchinaSincrona) -> Any:
            from assets.collector_cnc.drivers.focas import DriverFocas

            return DriverFocas(m.name, m.ip, log=m.log, raw=lib)

        with mock.patch.dict(collector.FABBRICHE, {"lsv2": lsv2_finto, "focas": focas_finto}):
            codice, out, _err = _esegui(["--config", str(p), "--once"])
            records = json.loads(out)
            self.assertEqual(codice, 0)
            self.assertEqual([r["machine"] for r in records], ["AGV1", "HYUNDAI"])   # DM6 disabilitata: esclusa
            self.assertEqual([r["stato"] for r in records], ["LAVORO", "LAVORO"])
            self.assertEqual(records[0]["raw"]["program_status"], "STARTED")
            self.assertEqual(records[1]["program"], "O1234")
            # una macchina scelta per nome si legge anche se disabilitata (confronto LSV2/MDC su DM6)
            codice, out, _err = _esegui(["--config", str(p), "--once", "DM6"])
            self.assertEqual(json.loads(out)[0]["machine"], "DM6")
            st.dnc = False
            codice, out, _err = _esegui(["--config", str(p), "--once", "AGV1"])
            r = json.loads(out)[0]
            self.assertEqual((codice, r["stato"], r["online"]), (1, "NON_LEGGIBILE", False))
            self.assertIn("#18", r["errore"])
        self.assertFalse((Path(self.cartella) / "machines.db").exists())   # --once non scrive niente
        self.assertEqual(st.connessioni, st.disconnessioni)
        self.assertEqual(lib.handle_aperti, set())

    def test_once_opcua_e_macchina_spenta(self) -> None:
        async def con_server() -> tuple[int, str]:
            sim = CncSimulata("bds")
            await sim.avvia()
            await sim.imposta(**{"Channel_1-ExecutionState": 1, "Channel_1-CurrentNcProgram": "\\USR\\P-1.h"})
            try:
                p = _scrivi(self.cartella, {"machines": [{"name": "DM9", "ip": "127.0.0.1", "port": sim.porta}]})
                return await asyncio.to_thread(lambda: _esegui(["--config", str(p), "--once"])[:2])
            finally:
                await sim.ferma()

        codice, out = asyncio.run(con_server())
        r = json.loads(out)[0]
        self.assertEqual((codice, r["stato"], r["program"], r["raw"]["modello_dati"]), (0, "LAVORO", "P-1", "bds"))
        self.assertEqual(r["parts_total"], 2000)
        p = _scrivi(self.cartella, {"machines": [{"name": "DM9", "ip": "127.0.0.1", "port": 1}]})
        codice, out, _err = _esegui(["--config", str(p), "--once", "DM9"])
        self.assertEqual((codice, json.loads(out)[0]["stato"]), (1, "OFFLINE"))
        self.assertEqual(_esegui(["--config", str(p), "--once", "NESSUNA"])[0], 1)


class BrowseTests(_Base):
    def _esplora(self, modello: str) -> tuple[dict[str, Any], int]:
        async def scenario() -> tuple[dict[str, Any], int]:
            sim = CncSimulata(modello)
            await sim.aggiungi_condizione("A1", "Prova", 900)
            await sim.avvia()
            try:
                m = {"name": "SIM", "ip": "127.0.0.1", "port": sim.porta}
                esito = await esplora.esplora(m, Path(self.cartella) / "browse.tsv")
                return esito, sim.porta
            finally:
                await sim.ferma()

        return asyncio.run(scenario())

    def test_suggerimenti_e_tsv(self) -> None:
        esito, _porta = self._esplora("bds")
        self.assertEqual(esito["modello"], "DMG MORI BasicDataSet")
        primo = {campo: (lista[0]["percorso"].rsplit("/", 1)[-1] if lista else None) for campo, lista in esito["suggerimenti"].items()}
        self.assertEqual(primo["execution"], "Channel_1-ExecutionState")
        self.assertEqual(primo["program"], "Channel_1-CurrentNcProgram")
        self.assertEqual(primo["feed_ovr"], "Channel_1-FeedOverride")
        self.assertEqual(primo["part_count"], "PartCounter")
        self.assertEqual(primo["alarm"], "NumberOfActiveAlarms")
        self.assertEqual(primo["estop"], "EmergencyStop")
        self.assertTrue(all(len(lista) <= 5 for lista in esito["suggerimenti"].values()))
        righe = (Path(self.cartella) / "browse.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(righe[0], "nodeid\tpercorso\tclasse\ttipo\tvalore")
        self.assertFalse(any("/Server/" in r or r.split("\t")[1] == "Objects/Server" for r in righe[1:]))
        self.assertTrue(any("Channel_1-ControllerMode\tVariable\tInt32\t1" in r for r in righe))
        out = io.StringIO()
        esplora.stampa_esplorazione(esito, out)
        self.assertIn('"exec": "ns=', out.getvalue())

    def test_umati_e_snippet_usabile_come_mappa_di_nodi(self) -> None:
        esito, _porta = self._esplora("umati")
        self.assertEqual(esito["modello"], "OPC 40501 Machine Tools (umati)")
        nodi = esito["snippet"]["nodes"]
        self.assertIn("Channel_1-ChannelState", nodi["exec"])

        # lo snippet incollato in machines.json si legge con la mappa «nodes»
        async def con_mappa() -> tuple[int, str]:
            sim = CncSimulata("umati")
            await sim.avvia()
            await sim.imposta(**{"Channel_1-ChannelState": 0, "Channel_1-ChannelMode": 0})
            try:
                m = {**esito["snippet"], "port": sim.porta, "execution_map": {"0": "RUNNING", "1": "INTERRUPTED", "2": "IDLE"},
                     "mode_map": {"0": "AUTO", "1": "MDI", "2": "MANUAL"}}
                p = _scrivi(self.cartella, {"machines": [m]})
                return await asyncio.to_thread(lambda: _esegui(["--config", str(p), "--once"])[:2])
            finally:
                await sim.ferma()

        codice, out = asyncio.run(con_mappa())
        r = json.loads(out)[0]
        self.assertEqual((codice, r["stato"], r["mode"], r["raw"]["modello_dati"]), (0, "LAVORO", "AUTO", "nodi"))

    def test_browse_solo_opcua(self) -> None:
        p = _scrivi(self.cartella, {"machines": [{"name": "AGV1", "driver": "lsv2", "ip": "192.0.2.105"}]})
        self.assertEqual(_esegui(["--config", str(p), "--browse", "AGV1"])[0], 1)

    def test_modelli(self) -> None:
        self.assertEqual(esplora.modello(["urn:mtconnect:agent"]), "derivato da MTConnect")
        self.assertEqual(esplora.modello(["urn:x"]), "sconosciuto")


class ServizioTests(_Base):
    def test_silenzioso_log_su_file_jsonl_e_stop(self) -> None:
        st = StatoLsv2()
        st.programma = PgmState.STARTED
        p = _scrivi(self.cartella, {"collector": {"heartbeat_seconds": 0.2, "log_file": "logs/c.log"},
                                    "machines": [{"name": "AGV1", "driver": "lsv2", "ip": "192.0.2.105", "poll_seconds": 2}]})
        from assets.collector_cnc.drivers.lsv2 import DriverLsv2

        def finto(m: collector.MacchinaSincrona) -> Any:
            return DriverLsv2(m.name, m.ip, log=m.log, modulo=modulo_lsv2(st))

        jsonl = Path(self.cartella) / "dati"
        vero_run = asyncio.run

        def ferma_presto(coro: Any) -> None:
            async def con_limite() -> None:
                task = asyncio.ensure_future(coro)
                limite = asyncio.get_running_loop().time() + 15
                while not (jsonl / "status.json").exists() or len(list((jsonl / "AGV1").glob("*.jsonl"))) == 0 or \
                        len((next((jsonl / "AGV1").glob("*.jsonl"))).read_text(encoding="utf-8").splitlines()) < 3:
                    if asyncio.get_running_loop().time() > limite:
                        break
                    await asyncio.sleep(0.05)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            vero_run(con_limite())

        with mock.patch.dict(collector.FABBRICHE, {"lsv2": finto}), mock.patch.object(lavoratore, "POLL_MINIMO", 0.01), \
                mock.patch.object(cli.asyncio, "run", ferma_presto), mock.patch.object(collector, "SALUTE", 0.1):
            codice, out, err = _esegui(["--config", str(p), "--jsonl", str(jsonl)])
        self.assertEqual((codice, out, err), (0, "", ""))   # niente a schermo senza -v
        log = (Path(self.cartella) / "logs" / "c.log").read_text(encoding="utf-8")
        self.assertIn("[AGV1 lsv2 192.0.2.105] - -> LAVORO", log)
        self.assertIn("salute: memoria", log)
        self.assertIn("collector fermato", log)
        stato = json.loads((jsonl / "status.json").read_text(encoding="utf-8"))
        self.assertEqual((stato["AGV1"]["stato"], stato["AGV1"]["driver"]), ("LAVORO", "lsv2"))
        righe = next((jsonl / "AGV1").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(righe), 3)   # cambio + battiti
        self.assertTrue((Path(self.cartella) / "machines.db").exists())
        self.assertEqual(st.connessioni, st.disconnessioni)

    def test_verbose_a_schermo(self) -> None:
        cli.configura_log(Path(self.cartella) / "x.log", verbose=True)
        nomi = {type(h).__name__ for h in logging.getLogger().handlers}
        self.assertEqual(nomi, {"RotatingFileHandler", "StreamHandler"})
        file = next(h for h in logging.getLogger().handlers if type(h).__name__ == "RotatingFileHandler")
        self.assertEqual((file.maxBytes, file.backupCount), (5 * 1024 * 1024, 5))  # type: ignore[attr-defined]
        self.assertEqual(logging.getLogger("asyncua").level, logging.ERROR)
        self.assertEqual(logging.getLogger("LSV2 Client").level, logging.ERROR)

    def test_memoria(self) -> None:
        mem = collector.memoria_mb()
        self.assertIsNotNone(mem)
        self.assertGreater(mem or 0, 1)


class SinkTests(_Base):
    def test_jsonl_e_status_atomico(self) -> None:
        s = sink.CartellaJsonl(Path(self.cartella) / "out")
        s.write({"ts": "2026-10-27T10:00:00+00:00", "machine": "DM/6", "stato": "LAVORO"})
        s.write({"ts": "2026-10-28T00:00:01+00:00", "machine": "DM/6", "stato": "FERMA"})
        self.assertTrue((Path(self.cartella) / "out" / "DM_6" / "2026-10-27.jsonl").exists())
        self.assertTrue((Path(self.cartella) / "out" / "DM_6" / "2026-10-28.jsonl").exists())
        self.assertEqual(json.loads((Path(self.cartella) / "out" / "status.json").read_text())["DM/6"]["stato"], "FERMA")
        chiamate = {"n": 0}
        vero = os.replace

        def bloccato(a: Any, b: Any) -> None:
            chiamate["n"] += 1
            if chiamate["n"] < 3:
                raise PermissionError("file aperto")
            vero(a, b)

        with mock.patch.object(sink.os, "replace", bloccato), mock.patch.object(sink, "ATTESA_REPLACE", 0):
            s.write({"ts": "2026-10-28T00:00:02+00:00", "machine": "DM/6", "stato": "LAVORO"})
        self.assertEqual(json.loads((Path(self.cartella) / "out" / "status.json").read_text())["DM/6"]["stato"], "LAVORO")
        with mock.patch.object(sink.os, "replace", side_effect=PermissionError("sempre")), mock.patch.object(sink, "ATTESA_REPLACE", 0):
            with self.assertLogs("collector", "WARNING"):
                s.write({"ts": "2026-10-28T00:00:03+00:00", "machine": "DM/6", "stato": "FERMA"})
        self.assertEqual(s.errori, 1)
        self.assertEqual(list((Path(self.cartella) / "out").glob("*.tmp")), [])
