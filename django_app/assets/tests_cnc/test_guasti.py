"""Test dei guasti del collector completo (requisito G), su simulatori e senza database del portale.

Ogni guasto ha il suo test: macchina spenta all'avvio, cavo staccato, riavvio del controllo, server
OPC UA che si riavvia o cambia certificato, portale giù per un'ora (nessuna perdita, nessun doppione),
machines.db bloccato, Fwlib assente, login DNC rifiutato, valori malformati, thread bloccato, stop
durante una riconnessione. I tempi sono compressi (polling a centesimi di secondo).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from assets.collector_cnc import archivio, collector, lavoratore, portale, stati
from assets.collector_cnc.drivers import focas, opcua
from assets.collector_cnc.drivers.base import Lettura, Messaggio
from assets.services.collector_cnc import evento_gia_applicato
from assets.tests_cnc.finti import FwlibFinta, PgmState, StatoLsv2, modulo_lsv2
from assets.tests_cnc.sim_opcua import CncSimulata, porta_libera

ATTESA = 15.0


def _silenzia() -> Callable[[], None]:
    livelli = {n: logging.getLogger(n).level for n in ("asyncua", "collector")}
    for n in livelli:
        logging.getLogger(n).setLevel(logging.CRITICAL)
    return lambda: [logging.getLogger(n).setLevel(lv) for n, lv in livelli.items()]  # type: ignore[func-returns-value]


def righe(db_path: str, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        return list(conn.execute(sql, args).fetchall())
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):   # il collector non ha ancora creato machines.db
            return []
        raise
    finally:
        conn.close()


async def attendi(condizione: Callable[[], bool], cosa: str, massimo: float = ATTESA) -> None:
    limite = time.monotonic() + massimo
    while not condizione():
        if time.monotonic() > limite:
            raise AssertionError(f"attesa scaduta: {cosa}")
        await asyncio.sleep(0.02)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(_silenzia())
        self.cartella = tempfile.mkdtemp(prefix="cnc_guasti_")
        self.db_path = os.path.join(self.cartella, "machines.db")
        for patcher in (mock.patch.object(lavoratore, "POLL_MINIMO", 0.01),
                        mock.patch.object(lavoratore, "BACKOFF_MASSIMO", 0.2)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def stati_registrati(self, macchina: str) -> list[str]:
        return [r[0] for r in righe(self.db_path, "SELECT state FROM state_log WHERE machine=? ORDER BY id", (macchina,))]


# ----------------------------------------------------------------------------
# Collector completo con driver LSV2 e FOCAS simulati
# ----------------------------------------------------------------------------
class CollectorSincronoTests(_Base):
    def _config(self, *macchine: dict[str, Any]) -> Path:
        p = Path(self.cartella) / "machines.json"
        p.write_text(json.dumps({"machines": list(macchine)}), encoding="utf-8")
        return p

    def _fabbriche(self, st: StatoLsv2 | None = None, lib: FwlibFinta | None = None) -> Any:
        from assets.collector_cnc.drivers.lsv2 import DriverLsv2

        def crea_lsv2(m: collector.MacchinaSincrona) -> Any:
            return DriverLsv2(m.name, m.ip, m.port, m.timeout, m.log, cicli_iniziali=m.totale_iniziale or 0,
                              modulo=modulo_lsv2(st or StatoLsv2()))

        def crea_focas(m: collector.MacchinaSincrona) -> Any:
            return focas.DriverFocas(m.name, m.ip, m.port, m.timeout, m.log, pezzi_totali=m.totale_iniziale or 0,
                                     pezzi_ultimo_grezzo=m.grezzo_iniziale,
                                     raw=None if m.cfg.get("fwlib_path") else (lib or FwlibFinta()),
                                     percorso=m.cfg.get("fwlib_path") or None)

        return mock.patch.dict(collector.FABBRICHE, {"lsv2": crea_lsv2, "focas": crea_focas})

    def _esegui(self, config: Path, copione: Callable[[], Any], portale_finto: Any = None) -> None:
        async def tutto() -> None:
            task = asyncio.create_task(collector.avvia(portale_finto, self.db_path, config))
            try:
                await copione()
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        asyncio.run(tutto())
        vivi = [t.name for t in threading.enumerate() if t.name.startswith("cnc-")]
        self.assertEqual(vivi, [], "thread delle macchine ancora vivi dopo lo stop")

    def test_lsv2_e_focas_insieme(self) -> None:
        st, lib = StatoLsv2(), FwlibFinta()
        st.programma = PgmState.STARTED
        lib.run = 3
        config = self._config({"name": "AGV1", "ip": "192.0.2.105", "driver": "lsv2", "poll_seconds": 0.02},
                              {"name": "HYUNDAI", "ip": "192.0.2.117", "driver": "focas", "port": 8193, "poll_seconds": 0.02})

        async def copione() -> None:
            await attendi(lambda: "LAVORO" in self.stati_registrati("AGV1") and "LAVORO" in self.stati_registrati("HYUNDAI"),
                          "entrambe in lavoro")
            st.programma = PgmState.FINISHED   # un ciclo chiuso su AGV1
            lib.pezzi = 107                    # sette pezzi su HYUNDAI
            st.messaggi = [(1, 1, 7, "Refrigerante basso")]
            await attendi(lambda: righe(self.db_path, "SELECT MAX(parts_overall) FROM counter_log WHERE machine='AGV1'")[0][0] == 1,
                          "ciclo contato")
            await attendi(lambda: righe(self.db_path, "SELECT MAX(parts_overall) FROM counter_log WHERE machine='HYUNDAI'")[0][0] == 7,
                          "pezzi contati")
            await attendi(lambda: bool(righe(self.db_path, "SELECT 1 FROM alarm_log WHERE machine='AGV1'")), "messaggio")

        with self._fabbriche(st, lib):
            self._esegui(config, copione)
        stati_agv1 = self.stati_registrati("AGV1")
        self.assertEqual(stati_agv1[0], "LAVORO")
        self.assertIn("FERMA", stati_agv1)   # FINISHED -> ferma
        self.assertEqual(righe(self.db_path, "SELECT code, message FROM alarm_log WHERE machine='AGV1'"),
                         [("1-1-7", "Refrigerante basso")])
        # fermato il collector: nessun intervallo resta aperto
        self.assertEqual(righe(self.db_path, "SELECT COUNT(*) FROM state_log WHERE end_utc IS NULL")[0][0], 0)
        self.assertEqual(lib.handle_aperti, set())
        self.assertEqual(st.connessioni, st.disconnessioni)

    def test_spenta_all_avvio_cavo_staccato_buchi_espliciti(self) -> None:
        st = StatoLsv2()
        st.acceso = False
        config = self._config({"name": "AGV2", "ip": "192.0.2.106", "driver": "lsv2", "poll_seconds": 0.02})

        async def copione() -> None:
            await attendi(lambda: self.stati_registrati("AGV2")[:1] == ["OFFLINE"], "offline all'avvio")
            st.acceso = True
            await attendi(lambda: self.stati_registrati("AGV2")[-1:] == ["FERMA"], "accesa")
            st.guasto_lettura = ConnectionResetError("cavo staccato")
            await attendi(lambda: self.stati_registrati("AGV2")[-2:] == ["FERMA", "OFFLINE"], "cavo staccato")
            await attendi(lambda: self.stati_registrati("AGV2")[-1:] == ["FERMA"], "riconnessa")

        with self._fabbriche(st):
            self._esegui(config, copione)
        intervalli = righe(self.db_path, "SELECT state, start_utc, end_utc FROM state_log WHERE machine='AGV2' ORDER BY id")
        offline = [r for r in intervalli if r[0] == "OFFLINE"]
        self.assertGreaterEqual(len(offline), 2)
        self.assertTrue(all(r[2] is not None for r in offline))   # buchi con inizio e fine

    def test_login_dnc_rifiutato_e_fwlib_assente_visibili(self) -> None:
        st = StatoLsv2()
        st.dnc = False
        config = self._config({"name": "DM3", "ip": "192.0.2.107", "driver": "lsv2", "poll_seconds": 0.02},
                              {"name": "HY2", "ip": "192.0.2.118", "driver": "focas", "poll_seconds": 0.02,
                               "fwlib_path": "Z:/non/esiste/Fwlib64.dll"})
        inviati: list[dict[str, Any]] = []
        p = _PortaleFinto(inviati)

        async def copione() -> None:
            await attendi(lambda: "NON_LEGGIBILE" in self.stati_registrati("DM3"), "DM3 non leggibile")
            await attendi(lambda: "NON_LEGGIBILE" in self.stati_registrati("HY2"), "HY2 non leggibile")
            await attendi(lambda: {r["asset_tag"] for r in inviati if r.get("stato") == "NON_LEGGIBILE"} == {"T-DM3"},
                          "evento al portale")

        with self._fabbriche(st), mock.patch.object(focas, "_libreria", None), mock.patch.object(portale, "INVIO_CAMBI", 0.02):
            config.write_text(json.dumps({"machines": [
                {**m, "asset_tag": "T-" + m["name"]} if m["name"] == "DM3" else m
                for m in json.loads(config.read_text())["machines"]]}))
            self._esegui(config, copione, p)
        riga = next(r for r in inviati if r.get("stato") == "NON_LEGGIBILE")
        self.assertIn("#18", riga["errore"])
        self.assertNotIn("OFFLINE", self.stati_registrati("DM3"))

    def test_ombra_legge_ma_non_invia(self) -> None:
        config = self._config({"name": "AGV3", "ip": "192.0.2.128", "driver": "lsv2", "poll_seconds": 0.02,
                               "asset_tag": "T-AGV3", "ombra": True})
        inviati: list[dict[str, Any]] = []

        async def copione() -> None:
            await attendi(lambda: len(self.stati_registrati("AGV3")) >= 1, "letta")
            await asyncio.sleep(0.3)

        with self._fabbriche(), mock.patch.object(portale, "INVIO_CAMBI", 0.02):
            self._esegui(config, copione, _PortaleFinto(inviati))
        self.assertEqual(inviati, [])
        self.assertEqual(righe(self.db_path, "SELECT COUNT(*) FROM outbox")[0][0], 0)

    def test_valori_malformati_non_propagati(self) -> None:
        st = StatoLsv2()
        st.override = (float("nan"), 999.0, 50.0)
        st.main = "\x00\x01"   # programma illeggibile: resta vuoto
        config = self._config({"name": "DM14", "ip": "192.0.2.132", "driver": "lsv2", "poll_seconds": 0.02})

        async def copione() -> None:
            await attendi(lambda: bool(righe(self.db_path, "SELECT 1 FROM signal_log WHERE machine='DM14' AND signal='rapid_ovr'")),
                          "segnali")

        with self._fabbriche(st):
            self._esegui(config, copione)
        segnali = dict(righe(self.db_path, "SELECT signal, value FROM signal_log WHERE machine='DM14'"))
        self.assertIsNone(segnali["feed_ovr"])      # NaN scartato: nessun valore, mai «nan»
        self.assertIsNone(segnali["spindle_ovr"])   # 999 % fuori 0-200: scartato
        self.assertEqual(segnali["rapid_ovr"], "50.0")
        self.assertEqual(segnali.get("program"), "")

    def test_lettura_ferma_diventa_offline(self) -> None:
        """Nessuno stato allungato per inerzia: senza letture la macchina passa OFFLINE."""
        db = archivio.DB(self.db_path)
        m = collector.MacchinaSincrona({"name": "X", "ip": "192.0.2.1", "driver": "lsv2", "timeout": 0.01,
                                        "poll_seconds": 0.01}, db)
        m.applica(Lettura(ts=collector.dt.datetime.now(collector.dt.timezone.utc), machine="X", driver="lsv2",
                          online=True, stato=stati.LAVORO, messaggi=[Messaggio("1", "x")]))
        self.assertEqual(m.compute_state(), (stati.LAVORO, None))
        m._ultima -= 60
        m.controlla_vecchiaia()
        self.assertEqual(m.state, stati.OFFLINE)
        self.assertIn("nessuna lettura", m.errore)
        db.chiudi()


class _PortaleFinto(portale.Portale):
    """Portale in memoria: registra le righe di stato ricevute; ``giu`` = non risponde."""

    def __init__(self, ricevute: list[dict[str, Any]]) -> None:
        super().__init__("http://portale.test", "token-sintetico", [], collector.prog_name)
        self.ricevute = ricevute
        self.giu = False
        self.letture: list[dict[str, Any]] = []
        self.applicati: dict[str, str] = {}   # asset_tag -> ultimo evento (come il portale vero)
        self.doppioni = 0
        self.rinfreschi = 0

    def scarica_macchine(self) -> None:
        return None

    async def invia(self, path: str, body: dict[str, Any]) -> bool:
        if self.giu:
            self._errore("portale non raggiungibile (finto)")
            return False
        if path == portale.URL_STATO:
            for riga in body["macchine"]:
                ev = riga.get("evento", "")
                if ev and evento_gia_applicato(self.applicati.get(riga["asset_tag"], ""), ev):
                    self.doppioni += 1
                    continue
                if ev and ev == self.applicati.get(riga["asset_tag"]):
                    self.rinfreschi += 1   # stessa chiave (battito o ultimo reinviato): aggiorna, non aggiunge
                    continue
                if ev:
                    self.applicati[riga["asset_tag"]] = ev
                self.ricevute.append(riga)
        else:
            self.letture.extend(body["readings"])
        return True


# ----------------------------------------------------------------------------
# Store-and-forward
# ----------------------------------------------------------------------------
class _MacchinaFinta:
    def __init__(self, tag: str) -> None:
        self.asset_tag, self.state, self.state_since = tag, "FERMA", collector.utcnow()
        self.values: dict[str, Any] = {}
        self.alarms: dict[str, Any] = {}
        self.spec = None
        self.counters_at = None
        self.portale_cambiata = False
        self.ombra = False
        self.n = 0

    def programma(self) -> str:
        return f"P{self.n}"


class StoreAndForwardTests(_Base):
    def test_portale_giu_un_ora_nessuna_perdita_nessun_doppione(self) -> None:
        db = archivio.DB(self.db_path)
        ricevute: list[dict[str, Any]] = []
        p = _PortaleFinto(ricevute)
        p.collega(db)
        m = _MacchinaFinta("CNC-1")
        p.machines = [m]  # type: ignore[list-item]

        async def scenario() -> None:
            # un'ora di portale giù: un cambio ogni 5 s = 720 eventi in coda
            p.giu = True
            for i in range(720):
                m.n = i
                m.state = "LAVORO" if i % 2 else "FERMA"
                p.accoda_stato(m)
            self.assertFalse(await p.svuota())
            self.assertEqual(db.in_coda(), 720)
            # il portale torna su
            p.giu = False
            self.assertTrue(await p.svuota())
            self.assertEqual(db.in_coda(), 0)
            # reinvio forzato (es. crash dopo l'invio, prima della cancellazione): niente doppioni
            for i in range(5):
                m.n = 1000 + i
                p.accoda_stato(m)
            with mock.patch.object(db, "inviati", lambda fino_a: None):
                self.assertTrue(await _una_volta(p))
            self.assertTrue(await p.svuota())

        asyncio.run(scenario())
        programmi = [r["programma"] for r in ricevute]
        self.assertEqual(programmi, [f"P{i}" for i in range(720)] + [f"P{1000 + i}" for i in range(5)])  # ordine, completezza
        # dei 5 reinviati: 4 scartati come vecchi, l'ultimo riconosciuto come già applicato
        self.assertEqual((p.doppioni, p.rinfreschi), (4, 1))
        chiavi = [r["evento"] for r in ricevute]
        self.assertEqual(len(chiavi), len(set(chiavi)))
        self.assertTrue(all(k.startswith(db.istanza + ":") for k in chiavi))
        db.chiudi()

    def test_battito_solo_a_coda_vuota_e_backoff(self) -> None:
        db = archivio.DB(self.db_path)
        ricevute: list[dict[str, Any]] = []
        p = _PortaleFinto(ricevute)
        p.collega(db)
        m = _MacchinaFinta("CNC-2")
        p.machines = [m]  # type: ignore[list-item]
        attese: list[float] = []

        async def scenario() -> None:
            p.giu = True
            p.accoda_stato(m)
            with mock.patch.multiple(portale, INVIO_CAMBI=0.01, RIPROVA=0.02, RIPROVA_MAX=0.08):
                task = asyncio.create_task(p.run())
                await attendi(lambda: p.tentativi >= 4, "tentativi")
                attese.append(p.tentativi)
                self.assertEqual(ricevute, [])          # niente battito con la coda piena
                p.giu = False
                await attendi(lambda: len(ricevute) >= 1 and p.rinfreschi >= 1, "evento e battito")
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        asyncio.run(scenario())
        self.assertEqual(len(ricevute), 1)   # il battito porta la chiave dell'ultimo evento: aggiorna, non duplica
        self.assertEqual(p.tentativi, 0)
        self.assertEqual(p.ultimo_evento["CNC-2"], ricevute[0]["evento"])
        # al riavvio la chiave dell'ultimo evento consegnato si riprende da machines.db
        q = _PortaleFinto([])
        q.collega(db)
        self.assertEqual(q.ultimo_evento["CNC-2"], ricevute[0]["evento"])
        db.chiudi()

    def test_coda_potata_oltre_il_massimo(self) -> None:
        db = archivio.DB(self.db_path)
        for i in range(12):
            db.accoda(portale.URL_STATO, "X", json.dumps({"i": i}), "2026-01-01 00:00:00")
        with mock.patch.object(archivio, "MAX_OUTBOX", 10):
            self.assertEqual(db.pota_outbox(), 2)
        self.assertEqual([json.loads(r[3])["i"] for r in db.da_inviare()], list(range(2, 12)))
        db.chiudi()


async def _una_volta(p: _PortaleFinto) -> bool:
    """Un solo giro di svuotamento (con ``inviati`` disattivato la coda non si svuoterebbe mai)."""
    assert p.db is not None
    righe_ = p.db.da_inviare(portale.LOTTO)
    eventi = []
    for id_, _p, _m, corpo in righe_:
        r = json.loads(corpo)
        r["evento"] = f"{p.db.istanza}:{id_:012d}"
        eventi.append(r)
    ok = await p.invia(portale.URL_STATO, {"macchine": eventi})
    # il portale li ha ricevuti, ma la cancellazione dalla coda «non è avvenuta»: al giro dopo si reinviano
    return ok


# ----------------------------------------------------------------------------
# machines.db bloccato
# ----------------------------------------------------------------------------
class DatabaseBloccatoTests(_Base):
    def test_scritture_in_attesa_e_poi_tutte_in_ordine(self) -> None:
        with mock.patch.object(archivio, "TIMEOUT_DB", 0.05):
            db = archivio.DB(self.db_path)
            altro = sqlite3.connect(self.db_path, timeout=0.05)
            altro.execute("BEGIN EXCLUSIVE")   # un altro processo tiene il file
            for i in range(5):
                self.assertFalse(db.x("INSERT INTO signal_log(machine, ts_utc, signal, value) VALUES('M','t','s',?)", (str(i),)))
            self.assertEqual(len(db.in_attesa), 5)
            self.assertTrue(db.bloccato)
            self.assertEqual(db.q("SELECT COUNT(*) FROM signal_log"), [(0,)])   # in WAL si legge anche così
            altro.rollback()
            altro.close()
            self.assertTrue(db.x("INSERT INTO signal_log(machine, ts_utc, signal, value) VALUES('M','t','s','5')"))
            self.assertEqual([r[0] for r in db.q("SELECT value FROM signal_log ORDER BY id")], [str(i) for i in range(6)])
            self.assertFalse(db.bloccato)
            db.chiudi()

    def test_limite_delle_scritture_in_attesa(self) -> None:
        with mock.patch.object(archivio, "TIMEOUT_DB", 0.01), mock.patch.object(archivio, "MAX_IN_ATTESA", 3):
            db = archivio.DB(self.db_path)
            altro = sqlite3.connect(self.db_path, timeout=0.01)
            altro.execute("BEGIN EXCLUSIVE")
            for i in range(5):
                db.x("INSERT INTO meta(chiave, valore) VALUES(?, 'x')", (f"k{i}",))
            self.assertEqual((len(db.in_attesa), db.scartate), (3, 2))
            altro.rollback()
            altro.close()
            db.chiudi()

    def test_machines_db_vecchio_aggiornato(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.executescript("CREATE TABLE alarm_log (id INTEGER PRIMARY KEY AUTOINCREMENT, machine TEXT NOT NULL, "
                           "code TEXT NOT NULL, message TEXT, severity INTEGER, start_utc TEXT NOT NULL, end_utc TEXT, "
                           "machine_time_utc TEXT);")
        conn.close()
        db = archivio.DB(self.db_path)
        self.assertIn("cond_key", {r[1] for r in db.q("PRAGMA table_info(alarm_log)")})
        istanza = db.istanza
        db.chiudi()
        self.assertEqual(archivio.DB(self.db_path).istanza, istanza)   # l'istanza resta la stessa


# ----------------------------------------------------------------------------
# OPC UA: macchina spenta all'avvio, certificato cambiato, sessioni chiuse
# ----------------------------------------------------------------------------
class OpcUaGuastiTests(_Base):
    def test_spenta_all_avvio_poi_accesa_e_certificato_cambiato(self) -> None:
        porta = porta_libera()

        async def scenario() -> list[str]:
            db = archivio.DB(self.db_path)
            m = collector.Machine({"name": "DM9", "ip": "127.0.0.1", "port": porta, "poll_seconds": 0.05}, db)
            task = asyncio.create_task(m.run())
            sim = CncSimulata("bds", porta)
            try:
                await attendi(lambda: m.state == stati.OFFLINE, "offline all'avvio")
                await sim.avvia_con_certificato("A")
                await attendi(lambda: m.state == stati.FERMA, "accesa")
                await sim.ferma()
                await attendi(lambda: m.state == stati.OFFLINE, "server fermo")
                await sim.avvia_con_certificato("B")   # stesso server, certificato nuovo
                await attendi(lambda: m.state == stati.FERMA, "riconnessa con il certificato nuovo")
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                await sim.ferma()
                db.chiudi()
            return self.stati_registrati("DM9")

        self.assertEqual(asyncio.run(scenario()), ["OFFLINE", "FERMA", "OFFLINE", "FERMA"])

    def test_sessione_chiusa_anche_se_l_apertura_fallisce(self) -> None:
        conteggi = {"connect": 0, "disconnect": 0}

        class ClientFinto:
            def __init__(self, url: str, timeout: float = 0) -> None:
                self.session_timeout = 0

            def set_user(self, u: str) -> None: ...
            def set_password(self, p: str) -> None: ...

            async def connect(self) -> None:
                conteggi["connect"] += 1
                raise TimeoutError("sessione non attivata")

            async def disconnect(self) -> None:
                conteggi["disconnect"] += 1

        async def prova() -> None:
            with mock.patch.object(opcua, "Client", ClientFinto):
                with self.assertRaises(TimeoutError):
                    async with opcua.sessione("opc.tcp://127.0.0.1:1", None, None, "X"):
                        pass

        asyncio.run(prova())
        self.assertEqual(conteggi, {"connect": 1, "disconnect": 1})


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
