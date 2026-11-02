"""Regressione del collector OPC UA: stessi record in machines.db prima e dopo il refactor nei driver.

Un server OPC UA simulato (``sim_opcua``) recita lo stesso copione per i due modelli dati (umati e
BasicDataSet): lavoro, messaggi, allarme vero, condition segnaposto, MDI, interruzione, emergenza,
server spento e riacceso. Il collector vero (``Machine.run``) lo legge; il contenuto di machines.db
senza gli orari, deve essere identico al riferimento in ``dati/`` (generato prima del refactor
nei driver; dalla Fase 1 le righe a video sono diventate righe di log e non fanno più parte del confronto).

Rigenerare il riferimento solo per un cambio di comportamento voluto e motivato nel commit:
``CNC_REGRESSIONE_RIGENERA=1`` prima del comando di test.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from assets.collector_cnc import collector, lavoratore
from assets.collector_cnc.drivers import opcua
from assets.collector_cnc.drivers.base import spia
from assets.tests_cnc.sim_opcua import CncSimulata

DATI = Path(__file__).resolve().parent / "dati"
ATTESA_MAX = 20.0   # s per ogni passo del copione

# Segnali per modello: nome logico del copione -> nome del nodo nel simulatore
NODO = {
    "umati": {"exec": "Channel_1-ChannelState", "mode": "Channel_1-ChannelMode", "estop": "EmergencyStopTriggered",
              "program": "Channel_1-CurrentNcProgram", "feed": "Channel_1-FeedOverride", "light1": "Light_1-SignalOn",
              "light2": "Light_2-SignalOn", "pezzi": "ActiveProgram-PartCounter",
              "pezzi_tot": "Statistics-PartsProducedInLifetime", "ore": "OperationDuration"},
    "bds": {"exec": "Channel_1-ExecutionState", "mode": "Channel_1-ControllerMode", "estop": "EmergencyStop",
            "program": "Channel_1-CurrentNcProgram", "feed": "Channel_1-FeedOverride", "light1": "LightStatus1",
            "light2": "LightStatus2", "pezzi": "PartCounter", "pezzi_tot": "PartCounterOverall",
            "ore": "OperationTimeOverall", "n_alarms": "NumberOfActiveAlarms"},
}
# Valori grezzi per modello: esecuzione e modalità
ESEC = {"umati": {"run": 0, "int": 1, "idle": 2}, "bds": {"run": 1, "int": 2, "idle": 3}}
MODO = {"umati": {"auto": 0, "mdi": 1, "man": 2}, "bds": {"auto": 1, "mdi": 2, "man": 3}}
LUCE = {"umati": {"on": True, "off": False, "blink": True}, "bds": {"on": 1, "off": 0, "blink": 2}}
PROGRAMMA = {"umati": "/_N_MPF_DIR/_N_LAVORO_DIR/_N_DM9_0014_R1_3_MPF", "bds": "\\USR\\LAVORO\\DM12-0055-R0-1.h"}


def copione(modello: str) -> list[tuple[str, dict[str, Any]]]:
    """Passi del copione: ogni passo cambia o solo segnali o solo condition (mai a metà tra i due)."""
    e, m, luce = ESEC[modello], MODO[modello], LUCE[modello]
    passi: list[tuple[str, dict[str, Any]]] = [
        ("lavoro", {"exec": e["run"], "mode": m["auto"], "program": PROGRAMMA[modello], "feed": 80.0,
                    "light1": luce["on"], "pezzi": 1, "pezzi_tot": 1001}),
        ("cond", {"cond_M10": True}),
        ("cond", {"cond_A100": True, "cond_0/0000-0000": True, "cond_INFO": True}),
        ("cond", {"cond_A100": False, "cond_M10": False, "cond_0/0000-0000": False}),
        ("segnali", {"mode": m["mdi"], "light2": luce["blink"], "pezzi": 2}),
        ("segnali", {"exec": e["int"]}),
        ("segnali", {"estop": True}),
        ("segnali", {"estop": False, "exec": e["idle"], "mode": m["auto"]}),
        ("cond", {"cond_A200": True}),
    ]
    if modello == "bds":
        passi.append(("segnali", {"n_alarms": 1}))
        passi.append(("segnali", {"n_alarms": 0}))
    passi += [
        ("cond", {"cond_A200": False, "cond_INFO": False}),
        ("segnali", {"program": "", "light1": luce["off"], "light2": luce["off"]}),
        ("spegni", {}),
        ("riaccendi", {}),
        ("segnali", {"exec": e["run"], "program": PROGRAMMA[modello], "pezzi": 3, "pezzi_tot": 1003, "ore": 7200}),
        ("segnali", {"mode": m["man"]}),
    ]
    return passi


def _tabelle(db_path: str) -> dict[str, list[list[Any]]]:
    """Contenuto di machines.db senza orari e id (gli intervalli: solo «chiuso sì/no»)."""
    conn = sqlite3.connect(db_path)
    try:
        q = conn.execute
        contatori: list[list[Any]] = []
        for riga in q("SELECT machine, run_time, part_counter, parts_overall, operation_time, power_on_time "
                      "FROM counter_log ORDER BY id"):
            if not contatori or contatori[-1] != list(riga):   # una riga al giro: contano i valori distinti
                contatori.append(list(riga))
        return {
            "machines": [list(r) for r in q("SELECT name, ip, serial, model, department, data_model, server_version, "
                                            "last_seen_utc IS NOT NULL FROM machines ORDER BY name")],
            "state_log": [list(r) for r in q("SELECT machine, state, program, mode, exec, alarm_code, "
                                             "end_utc IS NOT NULL FROM state_log ORDER BY id")],
            "signal_log": [list(r) for r in q("SELECT machine, signal, value FROM signal_log ORDER BY id")],
            "alarm_log": [list(r) for r in q("SELECT machine, code, message, severity, machine_time_utc, "
                                             "end_utc IS NOT NULL FROM alarm_log ORDER BY id")],
            "counter_log": contatori,
        }
    finally:
        conn.close()


class RegressioneOpcUaTests(unittest.TestCase):
    """Il collector OPC UA produce esattamente i record del riferimento, per umati e BasicDataSet."""

    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        livelli = {}
        for nome in ("asyncua", "collector"):
            livelli[nome] = logging.getLogger(nome).level
            logging.getLogger(nome).setLevel(logging.CRITICAL)
        cls.addClassCleanup(lambda: [logging.getLogger(n).setLevel(lv) for n, lv in livelli.items()])

    def _esegui(self, modello: str) -> dict[str, Any]:
        return asyncio.run(self._copione(modello))

    async def _copione(self, modello: str) -> dict[str, Any]:
        sim = CncSimulata(modello)
        await sim.aggiungi_condizione("A100", "Asse X fuori limite", 900)
        await sim.aggiungi_condizione("M10", "Lubrificazione centralizzata", 500)
        await sim.aggiungi_condizione("0/0000-0000", "segnaposto", 1000)
        await sim.aggiungi_condizione("INFO", "", 1)
        await sim.aggiungi_condizione("A200", "Pressione aria bassa", 850)
        await sim.avvia()
        cartella = tempfile.mkdtemp(prefix="cnc_regr_")
        db_path = os.path.join(cartella, "machines.db")
        task = None
        try:
            with spia() as chiamate, mock.patch.object(lavoratore, "POLL_MINIMO", 0.01), mock.patch.multiple(
                    collector, ALARM_PERIOD=0, COUNTER_PERIOD=0):
                db = collector.DB(db_path)
                m = collector.Machine({"name": "SIM", "ip": "127.0.0.1", "port": sim.porta, "serial": sim.matricola,
                                       "model": "DMC 85", "department": "R1", "asset_tag": "SIM-1",
                                       "poll_seconds": 0.05}, db)
                giri = [0]
                tocca = m.touch

                def conta() -> None:
                    giri[0] += 1
                    tocca()

                m.touch = conta  # type: ignore[method-assign]
                task = asyncio.create_task(m.run())

                async def attendi(condizione: Any, cosa: str) -> None:
                    limite = asyncio.get_running_loop().time() + ATTESA_MAX
                    while not condizione():
                        if asyncio.get_running_loop().time() > limite:
                            self.fail(f"{modello}: attesa scaduta ({cosa})")
                        await asyncio.sleep(0.02)

                async def giri_dopo(n: int, cosa: str) -> None:
                    inizio = giri[0]
                    await attendi(lambda: giri[0] >= inizio + n, cosa)

                await giri_dopo(3, "prima lettura")
                for tipo, valori in copione(modello):
                    if tipo == "spegni":
                        await sim.ferma()
                        await attendi(lambda: m.state == collector.OFFLINE, "macchina offline")
                    elif tipo == "riaccendi":
                        await sim.avvia()
                        await attendi(lambda: m.state not in (None, collector.OFFLINE), "riconnessione")
                        await giri_dopo(3, "dopo la riconnessione")
                    else:
                        await sim.imposta(**{(k if k.startswith("cond_") else NODO[modello][k]): v
                                             for k, v in valori.items()})
                        await giri_dopo(3, f"passo {valori}")
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await sim.ferma()
        db.chiudi()
        risultato: dict[str, Any] = _tabelle(db_path)
        # spia: ogni accesso alla libreria OPC UA è nella whitelist (client o nodo)
        usati = {nome for driver, nome in chiamate if driver == "opcua"}
        self.assertTrue(usati, "la spia non ha registrato niente")
        self.assertLessEqual(usati, opcua.CLIENT_AMMESSI | opcua.NODO_AMMESSI)
        self.assertEqual({driver for driver, _n in chiamate}, {"opcua"})
        return risultato

    def _confronta(self, modello: str) -> None:
        ottenuto = self._esegui(modello)
        rif = DATI / f"regressione_opcua_{modello}.json"
        if os.environ.get("CNC_REGRESSIONE_RIGENERA") == "1":
            DATI.mkdir(exist_ok=True)
            rif.write_text(json.dumps(ottenuto, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        atteso = json.loads(rif.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(json.dumps(ottenuto)), atteso)

    def test_umati(self) -> None:
        self._confronta("umati")

    def test_basicdataset(self) -> None:
        self._confronta("bds")
