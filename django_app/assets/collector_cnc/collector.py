"""
collector.py - Collector delle CNC (OPC UA DMG MORI, Heidenhain LSV2, Fanuc FOCAS) in sola lettura.

Tutto quello che parla con le macchine sta in ``drivers/`` dietro whitelist di sola lettura
(``drivers/base.py``); qui ci sono stato, intervalli, machines.db e il ciclo delle macchine:
  - OPC UA (``driver: "opcua"``, default): asincrono, una coroutine per macchina. Modelli dati umati /
    OPC UA for Machine Tools (es. DM16, DM17) e DMG MORI BasicDataSet (es. DM6, DM9, DM10, DM11...).
  - LSV2 e FOCAS (``driver: "lsv2"`` / ``"focas"``): un thread per macchina con la sua connessione
    persistente (``lavoratore.py``), che passa i record al ciclo asincrono tramite una coda.

Uso:
  py collector.py                      # usa machines.json e machines.db
  py collector.py --config machines.json --db machines.db

Con il NOVICROM HUB (vedi portale.py e README.md): con le variabili d'ambiente PORTALE_URL e
PORTALE_TOKEN l'elenco delle macchine arriva dal portale (Asset › Configurazione › Macchine
collegate, riletto ogni 5 minuti: macchine aggiunte, tolte o cambiate senza riavviare) e lo
stato, gli allarmi e i contatori vanno al portale passando dalla coda in machines.db (un portale
fermo non fa perdere niente). Le macchine in ``ombra`` si leggono e si salvano solo in locale.

Requisiti: pip install asyncua pyLSV2 (FOCAS: libreria Fwlib, vedi CNC_FWLIB_PATH)
"""
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import datetime as dt
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:   # dentro il portale (manage.py collector_cnc)
    from . import stati
    from .archivio import DB
    from .drivers import opcua
    from .drivers.base import DriverSincrono, Lettura
    from .drivers.opcua import CONNECT_TIMEOUT, DMG_MACHINE_URI, MODELS, UMATI_URI, text
    from .lavoratore import Orologio, Ritmo, Sorvegliante, log_macchina
    from .portale import AGGIORNA_ELENCO, Portale
    from .sink import Sink
except ImportError:   # sul PC dell'officina (py collector.py)
    import stati  # type: ignore[no-redef]
    from archivio import DB  # type: ignore[no-redef]
    from drivers import opcua  # type: ignore[no-redef]
    from drivers.base import DriverSincrono, Lettura  # type: ignore[no-redef]
    from drivers.opcua import CONNECT_TIMEOUT, DMG_MACHINE_URI, MODELS, UMATI_URI, text  # type: ignore[no-redef]
    from lavoratore import Orologio, Ritmo, Sorvegliante, log_macchina  # type: ignore[no-redef]
    from portale import AGGIORNA_ELENCO, Portale  # type: ignore[no-redef]
    from sink import Sink  # type: ignore[no-redef]

__all__ = ["CONNECT_TIMEOUT", "DB", "DMG_MACHINE_URI", "MODELS", "UMATI_URI", "text"]   # usati da cerca.py e dai test

VERSIONE = "2.0.0"

# ----------------------------------------------------------------------------
# Parametri
# ----------------------------------------------------------------------------
ALARM_PERIOD = 5.0       # s - lettura allarmi attivi (OPC UA)
COUNTER_PERIOD = 60.0    # s - lettura contatori (OPC UA)
HEARTBEAT_CONTATORI = 300.0  # s - riga dei contatori anche senza cambi (LSV2, FOCAS)
STATUS_PRINT_PERIOD = 300.0  # s - riepilogo nel log (solo se qualcosa e' cambiato)
CONTROLLO_OROLOGIO = 10.0    # s
HEARTBEAT_USCITE = 300.0     # s - record di ogni macchina sulle uscite (--jsonl) anche senza cambi
SALUTE = 600.0               # s - riga di salute del collector nel log (memoria, thread, code)
ALARM_SEVERITY = 801     # da questa severita' un messaggio e' un allarme vero
# condition "segnaposto" senza significato (es. 0/0000-0000 su DM13): ignorate
IGNORE_CODES = {"0/0000-0000"}
# nel log a livello INFO solo i messaggi da questa severita' in su (nel database finiscono tutti)
PRINT_MIN_SEVERITY = 401
DRIVER_NOTI = ("opcua", "lsv2", "focas")
PORTE_DEFAULT = {"opcua": 4840, "lsv2": 19000, "focas": 8193}

OFFLINE, EMERGENZA, ALLARME, LAVORO, SETUP, INTERROTTA, FERMA, NON_LEGGIBILE = (
    stati.OFFLINE, stati.EMERGENZA, stati.ALLARME, stati.LAVORO, stati.SETUP, stati.INTERROTTA, stati.FERMA,
    stati.NON_LEGGIBILE)

log = logging.getLogger("collector")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def ts(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def prog_name(path: Any) -> str:
    """'/_N_MPF_DIR/_N_LAVORO_DIR/_N_DM9_0014_R1_3_MPF' -> 'DM9_0014_R1_3'
    '\\USR\\LAVORO\\DM12-0055-R0-1.h' -> 'DM12-0055-R0-1'"""
    if not path:
        return ""
    name = str(path).replace("\\", "/").rstrip("/").split("/")[-1]
    if name.startswith("_N_"):
        name = name[3:]
        for suf in ("_MPF", "_SPF"):
            if name.endswith(suf):
                name = name[: -len(suf)]
    for ext in (".h", ".H", ".i", ".I", ".nc", ".NC"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    return name


# ----------------------------------------------------------------------------
# Macchina OPC UA (e base comune)
# ----------------------------------------------------------------------------
class Machine:
    """Stato, intervalli e registro di una macchina; questa classe legge via OPC UA (asincrono)."""

    def __init__(self, cfg: dict[str, Any], db: DB) -> None:
        self.name: str = cfg["name"]
        self.ip: str = cfg["ip"]
        self.driver_nome: str = str(cfg.get("driver") or "opcua")
        self.port: int = int(cfg.get("port") or PORTE_DEFAULT.get(self.driver_nome, 4840))
        self.serial: str = cfg.get("serial", "")
        self.model_name: str = cfg.get("model", "")
        self.department: str = cfg.get("department", "")
        self.asset_tag: str = cfg.get("asset_tag", "")   # codice dell'asset nel portale (vuoto = non inviata)
        self.ombra: bool = bool(cfg.get("ombra", False))  # legge e salva in locale, non invia al portale
        self.hours_unit: str = cfg.get("hours_unit") or ""  # unita' delle ore scelta nel portale (h | min | s), vuoto = dal modello
        self.found_serial = ""      # matricola letta dal namespace DMG MORI del server
        # credenziali OPC UA opzionali (per server che rifiutano l'accesso anonimo)
        self.cfg = cfg
        self.username: str | None = cfg.get("username") or None
        # password: mai scritta in machines.json a mano; «password_env» = nome della variabile d'ambiente
        self.password: str | None = cfg.get("password") or (os.environ.get(str(cfg["password_env"])) if cfg.get("password_env") else None)
        self.ignored: set[str] = set()        # condition segnaposto da non registrare
        self.url = f"opc.tcp://{self.ip}:{self.port}"
        self.db = db
        self.log = log_macchina(self.name, self.driver_nome, self.ip)
        self.ritmo = Ritmo(cfg.get("poll_seconds"), log=self.log)

        self.data_model: str | None = None      # "umati" | "bds" (OPC UA), nome del driver per gli altri
        self.spec: dict[str, Any] | None = None
        self.values: dict[str, Any] = {}            # segnale -> ultimo valore
        self.colors: dict[str, str] = {}            # light1..4 -> nome colore
        self.alarms: dict[str, dict[str, Any]] = {}  # nodeid condition -> dict(code, message, severity, since)
        self.state: str | None = None
        self.state_key: tuple[Any, ...] | None = None
        self.state_since: dt.datetime | None = None     # inizio dello stato attuale (UTC), per il portale
        self.errore = ""            # perché la macchina è OFFLINE / NON_LEGGIBILE
        self.portale_cambiata = False
        self.notifica: Callable[[Machine], None] | None = None   # coda verso il portale (None = non si invia)
        self.uscite: list[Sink] = []    # uscite facoltative (--jsonl): record a ogni cambio e a ogni battito
        self.counters_at: dt.datetime | None = None     # ultima lettura dei contatori (UTC)
        self.last_seen: dt.datetime | None = None
        self.last_err: str | None = None

        db.x("""INSERT INTO machines(name, ip, serial, model, department) VALUES(?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET ip=excluded.ip, serial=excluded.serial,
                model=excluded.model, department=excluded.department""",
             (self.name, self.ip, self.serial, self.model_name, self.department))

    # ---------------- valori normalizzati (per state_log e portale) ----------------
    def modalita(self) -> str:
        return str((self.spec or {}).get("mode_map", {}).get(self.values.get("mode"), ""))

    def esecuzione(self) -> str:
        return str((self.spec or {}).get("exec_map", {}).get(self.values.get("exec"), ""))

    def programma(self) -> str:
        return prog_name(self.values.get("program"))

    # ---------------- stato comune ----------------
    def compute_state(self, online: bool = True) -> tuple[str, str | None]:
        if not online:
            return OFFLINE, None
        v, spec = self.values, self.spec or {}
        if v.get("estop") is True:
            return EMERGENZA, None
        hard = [a for a in self.alarms.values() if (a["severity"] or 0) >= ALARM_SEVERITY]
        if hard:
            return ALLARME, hard[0]["code"]
        if self.data_model in ("bds", "nodi") and (v.get("n_alarms") or 0) > 0:
            return ALLARME, None
        ex = spec["exec_map"].get(v.get("exec"))
        md = spec["mode_map"].get(v.get("mode"))
        if ex == "RUNNING":
            return (LAVORO if md == "AUTO" else SETUP), None
        if ex == "INTERRUPTED":
            return INTERROTTA, None
        return FERMA, None

    def update_state(self, online: bool = True) -> None:
        now = utcnow()
        state, alarm_code = self.compute_state(online)
        leggibile = state not in (OFFLINE, NON_LEGGIBILE)
        program = self.programma() if leggibile else ""
        mode = self.modalita() if leggibile else ""
        ex = self.esecuzione() if leggibile else ""
        key = (state, program, alarm_code)
        if key == self.state_key:
            return
        self.db.x("UPDATE state_log SET end_utc=? WHERE machine=? AND end_utc IS NULL", (ts(now), self.name))
        self.db.x("""INSERT INTO state_log(machine, state, start_utc, program, mode, exec, alarm_code)
                     VALUES(?,?,?,?,?,?,?)""",
                  (self.name, state, ts(now), program, mode, ex, alarm_code))
        if state != self.state:
            self.state_since = now
            extra = f"  prog={program}" if program else ""
            extra += f"  allarme={alarm_code}" if alarm_code else ""
            extra += f"  ({self.errore})" if not leggibile and self.errore else ""
            self.log.info("%s -> %s%s", self.state or "-", state, extra)
        self.state_key, self.state = key, state
        self.cambiata()

    def cambiata(self) -> None:
        """Stato o allarmi cambiati: un evento nella coda verso il portale (se la macchina ci va)."""
        self.portale_cambiata = True
        if self.notifica is not None:
            self.notifica(self)
        self.scrivi_uscite()

    def scrivi_uscite(self) -> None:
        if not self.uscite or self.state is None:
            return
        record = self.record()
        for uscita in self.uscite:
            uscita.write(record)

    def record(self) -> dict[str, Any]:
        """Il record normalizzato della macchina in questo istante (stesso formato per tutti i driver)."""
        leggibile = self.state not in (None, OFFLINE, NON_LEGGIBILE)
        v = self.values
        allarme = next(iter(self.alarms.values()), None)
        return {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(), "machine": self.name, "driver": self.driver_nome,
            "online": leggibile, "stato": self.state, "dal": self.state_since.replace(tzinfo=dt.timezone.utc).isoformat()
            if self.state_since else None,
            "mode": self.modalita() if leggibile else "", "execution": (self.esecuzione() or "UNKNOWN") if leggibile else "OFFLINE",
            "program": self.programma() if leggibile else None, "subprogram": None,
            "feed_ovr": v.get("feed_ovr"), "spindle_ovr": v.get("spindle_ovr"), "rapid_ovr": v.get("rapid_ovr"),
            "alarm": self.state in (ALLARME, EMERGENZA), "alarm_text": allarme["message"] if allarme else None,
            "part_count": v.get("cnt_part_counter"), "parts_total": v.get("cnt_parts_overall"),
            "errore": self.errore if not leggibile else "", "line": None, "feed": None, "speed": None,
            "raw": {k: v[k] for k in ("exec", "mode", "tool", "estop", "n_alarms") if k in v},
        }

    def touch(self) -> None:
        self.last_seen = utcnow()

    def flush_last_seen(self) -> None:
        if self.last_seen:
            self.db.x("UPDATE machines SET last_seen_utc=? WHERE name=?", (ts(self.last_seen), self.name))

    def chiudi_intervalli(self) -> None:
        """Alla fermata della macchina (tolta dall'elenco o collector fermato)."""
        now = ts(utcnow())
        self.db.x("UPDATE state_log SET end_utc=? WHERE machine=? AND end_utc IS NULL", (now, self.name))
        self.db.x("UPDATE alarm_log SET end_utc=? WHERE machine=? AND end_utc IS NULL", (now, self.name))
        self.flush_last_seen()

    async def stop(self) -> None:
        """Chiusure che richiedono attesa (thread dei driver bloccanti); OPC UA: niente."""

    # ---------------- connessione ----------------
    async def run(self) -> None:
        await asyncio.sleep(self.ritmo.avvio())
        tentativi = 0
        while True:
            try:
                async with opcua.sessione(self.url, self.username, self.password, self.name, self.log) as client:
                    tentativi = 0
                    await self.session(await opcua.DriverOpcUa.rileva(client, self.name, self.log, self.cfg))
                self.last_err = None
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - qualunque errore OPC UA = macchina offline, si ritenta
                tentativi += 1
                self.log.debug("%s", e)
                err = type(e).__name__
                self.errore = f"{err}: {e}"[:300]
                if self.state != OFFLINE or err != self.last_err:
                    self.last_err = err
                    if "Identity" in err or "UserAccessDenied" in err:
                        self.log.warning("rifiuta l'accesso %s (%s): servono utente e password OPC UA validi "
                                         "(portale: Macchine collegate > Modifica; senza portale: machines.json)",
                                         "con queste credenziali" if self.username else "anonimo", err)
                    else:
                        self.log.warning("non raggiungibile (%s), ritento tra %.0f s", err, self.ritmo.backoff(tentativi))
            # fuori sessione: macchina offline
            self.alarms_close_all()
            self.update_state(online=False)
            self.flush_last_seen()
            await asyncio.sleep(self.ritmo.backoff(tentativi))

    async def session(self, drv: Any) -> None:
        """Una sessione aperta: ``drv`` è il ``DriverOpcUa`` (solo letture), qui stato e database."""
        fast, counters, alarm_folder = await self.prepara(drv)

        t_alarm = t_counter = 0.0
        loop = asyncio.get_running_loop()
        while True:
            t0 = loop.time()
            await self.read_fast(drv, fast)
            if t0 >= t_alarm:
                if alarm_folder is not None:
                    await self.read_alarms(drv, alarm_folder)
                t_alarm = t0 + ALARM_PERIOD
            self.touch()
            self.update_state()
            if t0 >= t_counter:
                await self.read_counters(drv, counters)
                self.flush_last_seen()
                t_counter = t0 + COUNTER_PERIOD
            await asyncio.sleep(max(0.2, self.ritmo.attesa() - (loop.time() - t0)))

    async def una_lettura(self, drv: Any) -> dict[str, Any]:
        """Un solo giro di letture (``--once``): stesso percorso del servizio, poi il record."""
        fast, counters, alarm_folder = await self.prepara(drv)
        await self.read_fast(drv, fast)
        if alarm_folder is not None:
            await self.read_alarms(drv, alarm_folder)
        self.touch()
        self.update_state()
        await self.read_counters(drv, counters)
        return self.record()

    async def prepara(self, drv: Any) -> tuple[dict[str, Any], dict[str, Any], Any]:
        """Modello dati, nodi presenti, versione, colori: ``(fast, counters, cartella allarmi o None)``."""
        self.data_model = drv.data_model
        self.spec = drv.spec
        found_serial = drv.found_serial
        self.found_serial = found_serial
        if self.serial and found_serial != self.serial:
            self.log.warning("matricola attesa %s ma il server riporta %s (IP cambiato?)", self.serial, found_serial)
        assert self.spec is not None

        fast = await drv.resolve(self.spec["fast"])
        counters = await drv.resolve(self.spec["counters"])
        static = await drv.resolve(self.spec["static"])
        if "exec" not in fast:
            raise RuntimeError("nodo di stato canale assente: serve --browse")

        version = await drv.server_version()
        self.db.x("UPDATE machines SET data_model=?, server_version=? WHERE name=?",
                  (self.data_model, version, self.name))

        # colori del semaforo (configurazione statica)
        self.colors.update(await drv.colors(static))

        alarm_folder = drv.node(self.spec["alarm_folder"]) if self.spec.get("alarm_folder") else None
        self.errore = ""
        self.log.info("connessa (%s%s) - %d segnali", self.data_model, ", v" + version if version else "", len(fast))
        return fast, counters, alarm_folder

    # ---------------- letture ----------------
    def registra_segnale(self, name: str, val: Any, now: str) -> None:
        if self.values.get(name, "__nuovo__") != val:
            self.values[name] = val
            self.db.x("INSERT INTO signal_log(machine, ts_utc, signal, value) VALUES(?,?,?,?)",
                      (self.name, now, name, None if val is None else str(val)))

    async def read_fast(self, drv: Any, fast: dict[str, Any]) -> None:
        letti = await drv.read_fast(fast)
        now = ts(utcnow())
        for name, val in letti:
            self.registra_segnale(name, val, now)

    async def read_counters(self, drv: Any, counters: dict[str, Any]) -> None:
        if not counters:
            return
        row = await drv.read_counters(counters)
        self.values.update({f"cnt_{k}": v for k, v in row.items()})
        self.counters_at = utcnow()
        self.db.x("""INSERT INTO counter_log(machine, ts_utc, run_time, part_counter,
                     parts_overall, operation_time, power_on_time) VALUES(?,?,?,?,?,?,?)""",
                  (self.name, ts(utcnow()), row.get("run_time"), row.get("part_counter"),
                   row.get("parts_overall"), row.get("operation_time"), row.get("power_on_time")))

    def apri_allarme(self, key: str, code: str, msg: str, sev: int | None, now: dt.datetime, mtime: str | None) -> None:
        self.db.x("""INSERT INTO alarm_log(machine, code, message, severity, start_utc, machine_time_utc, cond_key)
                     VALUES(?,?,?,?,?,?,?)""", (self.name, code, msg, sev, ts(now), mtime, key))
        self.alarms[key] = {"code": code, "message": msg, "severity": sev, "since": now}
        if (sev or 0) >= PRINT_MIN_SEVERITY:
            self.log.info("+ msg %s (sev %s) %s", code, sev, msg)

    def chiudi_allarme(self, key: str, now: dt.datetime) -> None:
        a = self.alarms.pop(key)
        self.db.x("UPDATE alarm_log SET end_utc=? WHERE machine=? AND cond_key=? AND end_utc IS NULL",
                  (ts(now), self.name, key))
        if (a["severity"] or 0) >= PRINT_MIN_SEVERITY:
            self.log.info("- msg %s rientrato", a["code"])

    async def read_alarms(self, drv: Any, folder: Any) -> None:
        conds = await drv.conditions(folder)
        if not conds:
            return
        now = utcnow()
        cambiati = False
        for key, info, active in conds:
            if key in self.ignored:
                if not active:
                    self.ignored.discard(key)
                continue
            if active and key not in self.alarms:
                vals = await drv.condition_details(info)
                code = str(vals.get("code") or info["name"])
                msg = text(vals.get("message"))
                sev = vals.get("severity")
                if code in IGNORE_CODES or (not msg and (sev or 0) <= 1):
                    self.ignored.add(key)
                    continue
                mtime = vals.get("time")
                mtime = ts(mtime.astimezone(dt.timezone.utc).replace(tzinfo=None)) \
                    if isinstance(mtime, dt.datetime) and mtime.tzinfo else (ts(mtime) if isinstance(mtime, dt.datetime) else None)
                self.apri_allarme(key, code, msg, sev, now, mtime)
                cambiati = True
            elif not active and key in self.alarms:
                self.chiudi_allarme(key, now)
                cambiati = True
        if cambiati:
            self.cambiata()

    def alarms_close_all(self) -> None:
        if self.alarms:
            self.db.x("UPDATE alarm_log SET end_utc=? WHERE machine=? AND end_utc IS NULL", (ts(utcnow()), self.name))
        self.alarms.clear()
        self.ignored.clear()


# ----------------------------------------------------------------------------
# Macchine con driver bloccante (LSV2, FOCAS): un thread per macchina
# ----------------------------------------------------------------------------
SEGNALI_LETTURA = ("program", "subprogram", "mode", "execution", "feed_ovr", "spindle_ovr", "rapid_ovr",
                   "alarm_text", "part_count", "parts_total")


def crea_lsv2(m: MacchinaSincrona) -> DriverSincrono:
    try:
        from .drivers.lsv2 import DriverLsv2
    except ImportError:
        from drivers.lsv2 import DriverLsv2  # type: ignore[no-redef]
    return DriverLsv2(m.name, m.ip, m.port, m.timeout, m.log, cicli_iniziali=m.totale_iniziale or 0)


def crea_focas(m: MacchinaSincrona) -> DriverSincrono:
    try:
        from .drivers.focas import DriverFocas
    except ImportError:
        from drivers.focas import DriverFocas  # type: ignore[no-redef]
    return DriverFocas(m.name, m.ip, m.port, m.timeout, m.log, pezzi_totali=m.totale_iniziale or 0,
                       pezzi_ultimo_grezzo=m.grezzo_iniziale, percorso=m.cfg.get("fwlib_path") or None)


FABBRICHE: dict[str, Callable[[MacchinaSincrona], DriverSincrono]] = {"lsv2": crea_lsv2, "focas": crea_focas}


class MacchinaSincrona(Machine):
    """Macchina letta da un ``Lavoratore`` (thread): i record arrivano qui da una coda asincrona."""

    def __init__(self, cfg: dict[str, Any], db: DB) -> None:
        super().__init__(cfg, db)
        self.data_model = self.driver_nome
        self.timeout = float(cfg.get("timeout") or 5.0)
        self.grezzo_iniziale, self.totale_iniziale = db.ultimi_contatori(self.name)
        self.lettura: Lettura | None = None
        self._stato: str | None = None
        self._ultima = time.monotonic()
        self._contatori: tuple[Any, Any] = (self.grezzo_iniziale, self.totale_iniziale)
        self._contatori_scritti = 0.0
        self.sorvegliante: Sorvegliante | None = None
        self.coda: asyncio.Queue[Lettura] | None = None

    def crea_driver(self) -> DriverSincrono:
        return FABBRICHE[self.driver_nome](self)

    def modalita(self) -> str:
        return self.lettura.mode if self.lettura else ""

    def esecuzione(self) -> str:
        return self.lettura.execution if self.lettura else ""

    def programma(self) -> str:
        return prog_name(self.lettura.program) if self.lettura else ""

    def record(self) -> dict[str, Any]:
        base = super().record()
        if self.lettura is not None and base["online"]:
            dati = self.lettura.come_dict()
            dati.pop("messaggi", None)
            base.update({k: dati[k] for k in ("subprogram", "feed_ovr", "spindle_ovr", "rapid_ovr", "line", "feed",
                                              "speed", "raw", "part_count", "parts_total", "alarm_text")})
        return base

    def compute_state(self, online: bool = True) -> tuple[str, str | None]:
        stato = self._stato or OFFLINE
        if stato == ALLARME and self.alarms:
            return stato, next(iter(self.alarms.values()))["code"]
        return stato, None

    def applica(self, lettura: Lettura) -> None:
        """Un record dal thread: segnali, messaggi, contatori e stato."""
        self._ultima = time.monotonic()
        now = utcnow()
        self._stato = lettura.stato
        self.errore = lettura.errore
        if lettura.online:
            self.lettura = lettura
            self.touch()
            now_s = ts(now)
            for campo in SEGNALI_LETTURA:
                self.registra_segnale(campo, getattr(lettura, campo), now_s)
            self._messaggi(lettura, now)
            self._registra_contatori(lettura)
        else:
            self.alarms_close_all()
        self.update_state()
        if not lettura.online:
            self.flush_last_seen()

    def _messaggi(self, lettura: Lettura, now: dt.datetime) -> None:
        attivi = {f"{m.codice}|{m.testo}": m for m in lettura.messaggi}
        cambiati = False
        for key in [k for k in self.alarms if k not in attivi]:
            self.chiudi_allarme(key, now)
            cambiati = True
        for key, m in attivi.items():
            if key not in self.alarms:
                self.apri_allarme(key, m.codice, m.testo, m.severita, now, None)
                cambiati = True
        if cambiati:
            self.cambiata()

    def _registra_contatori(self, lettura: Lettura) -> None:
        valori = (lettura.part_count, lettura.parts_total)
        self.values["cnt_part_counter"] = lettura.part_count
        self.values["cnt_parts_overall"] = lettura.parts_total
        ora = time.monotonic()
        if valori == self._contatori and ora - self._contatori_scritti < HEARTBEAT_CONTATORI:
            return
        self._contatori, self._contatori_scritti = valori, ora
        self.counters_at = utcnow()
        self.db.x("INSERT INTO counter_log(machine, ts_utc, part_counter, parts_overall) VALUES(?,?,?,?)",
                  (self.name, ts(self.counters_at), lettura.part_count, lettura.parts_total))
        self.flush_last_seen()

    def controlla_vecchiaia(self) -> None:
        """Mai uno stato «allungato per inerzia»: senza letture recenti la macchina diventa OFFLINE."""
        limite = self.ritmo.poll + 3 * self.timeout + 2
        if self._stato in (None, OFFLINE, NON_LEGGIBILE) or time.monotonic() - self._ultima <= limite:
            return
        self._stato = OFFLINE
        self.errore = f"nessuna lettura da oltre {limite:.0f} s"
        self.alarms_close_all()
        self.update_state()
        self.flush_last_seen()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self.coda = coda = asyncio.Queue[Lettura]()

        def consegna(lettura: Lettura) -> None:
            with contextlib.suppress(RuntimeError):   # ciclo già chiuso: il collector si sta fermando
                loop.call_soon_threadsafe(coda.put_nowait, lettura)

        self.sorvegliante = Sorvegliante(self.name, self.crea_driver, self.ritmo, consegna, self.log)
        self.sorvegliante.avvia()
        self._ultima = time.monotonic()
        while True:
            try:
                lettura = await asyncio.wait_for(coda.get(), 1.0)
            except asyncio.TimeoutError:
                lettura = None
            if lettura is not None:
                self.applica(lettura)
            self.sorvegliante.controlla()
            self.controlla_vecchiaia()

    async def stop(self) -> None:
        """Ferma il thread (con attesa limitata) senza bloccare il ciclo asincrono."""
        if self.sorvegliante is not None:
            await asyncio.to_thread(self.sorvegliante.ferma, 2 * self.timeout + 1)


def nuova_macchina(cfg: dict[str, Any], db: DB) -> Machine:
    driver = str(cfg.get("driver") or "opcua")
    return Machine(cfg, db) if driver == "opcua" else MacchinaSincrona(cfg, db)


# ----------------------------------------------------------------------------
# Riepilogo nel log
# ----------------------------------------------------------------------------
async def status_printer(elenco: Callable[[], list[Machine]]) -> None:
    last = None
    while True:
        await asyncio.sleep(STATUS_PRINT_PERIOD)
        rows = []
        for m in elenco():
            v = m.values
            lights = ",".join(m.colors.get(k, "?") for k in ("light1", "light2", "light3", "light4")
                              if v.get(k) not in (None, False)) or "-"
            pezzi = v.get("cnt_part_counter")
            rows.append(f"{m.name:<9}{(m.state or '-'):<14}{m.programma()[:25]:<26}"
                        f"{'' if pezzi is None else pezzi:>7}{len(m.alarms):>9}  {lights}")
        if rows == last:
            continue
        last = rows
        log.info("riepilogo\n%s\n%s", f"{'Macchina':<9}{'Stato':<14}{'Programma':<26}{'Pezzi':>7}{'Messaggi':>9}  Semaforo",
                 "\n".join(rows))


async def sorveglia_orologio(orologio: Orologio) -> None:
    while True:
        await asyncio.sleep(CONTROLLO_OROLOGIO)
        orologio.controlla()


def memoria_mb() -> float | None:
    """Memoria residente del processo in MB (solo libreria standard), None se non si riesce a leggere."""
    try:
        if sys.platform.startswith("win"):
            class _Contatori(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            c = _Contatori()
            c.cb = ctypes.sizeof(c)
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
            psapi = ctypes.windll.psapi  # type: ignore[attr-defined,unused-ignore]
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Contatori), ctypes.c_ulong]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return round(float(c.WorkingSetSize) / 1048576, 1)
            return None
        with open("/proc/self/statm", encoding="ascii") as f:
            pagine = int(f.read().split()[1])
        return round(pagine * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)
    except (OSError, AttributeError, ValueError) as e:
        log.debug("memoria non letta: %s", e)
        return None


def riga_salute(macchine: list[Machine], db: DB, portale: Portale | None) -> str:
    """Una riga per il pilota: memoria, thread, stati, thread bloccati, code."""
    per_stato: dict[str, int] = {}
    for m in macchine:
        per_stato[m.state or "-"] = per_stato.get(m.state or "-", 0) + 1
    bloccati = sum(m.sorvegliante.bloccati for m in macchine if isinstance(m, MacchinaSincrona) and m.sorvegliante)
    mem = memoria_mb()
    return (f"salute: memoria {mem if mem is not None else '?'} MB, thread {threading.active_count()}, "
            f"macchine {len(macchine)} ({', '.join(f'{k} {v}' for k, v in sorted(per_stato.items())) or '-'}), "
            f"thread bloccati {bloccati}, coda portale {db.in_coda() if portale is not None else 0}, "
            f"scritture in attesa {len(db.in_attesa)}")


async def ripeti(ogni: float, azione: Callable[[], None]) -> None:
    while True:
        await asyncio.sleep(ogni)
        azione()


async def avvia(portale: Portale | None, db_path: str, config_path: Path | None = None,
                copia_path: Path | None = None, uscite: list[Sink] | None = None,
                elenco_iniziale: list[dict[str, Any]] | None = None) -> None:
    """Legge le macchine finché non viene fermato.

    ``portale``: dove prendere l'elenco e mandare stato e contatori (``Portale`` via HTTP dal PC
    dell'officina, ``PortaleDiretto`` dentro il portale) oppure None (solo machines.json, nessun invio).
    ``copia_path``: dove tenere l'ultimo elenco scaricato, per ripartire se il portale non risponde.
    """
    db = DB(db_path)
    db.close_dangling()
    log.info("collector CNC %s avviato, database %s", VERSIONE, Path(db_path).resolve())
    elenco = elenco_iniziale
    if portale is not None:
        portale.collega(db)
        scaricato = await asyncio.to_thread(portale.scarica_macchine)
        elenco = scaricato if scaricato is not None else elenco
        if scaricato is not None:
            if copia_path:
                copia_path.write_text(json.dumps({"machines": scaricato}, indent=1), encoding="utf-8")
            log.info("elenco delle macchine dal portale: %d", len(scaricato))
        elif copia_path and copia_path.exists():
            elenco = json.loads(copia_path.read_text(encoding="utf-8"))["machines"]
            log.warning("portale non raggiungibile: uso l'ultimo elenco scaricato (%d macchine)", len(elenco))
    if elenco is None:
        elenco = json.loads(config_path.read_text(encoding="utf-8"))["machines"] if config_path and config_path.exists() else []
        log.info("elenco delle macchine da %s: %d", config_path.name if config_path else "(nessun file)", len(elenco))
    if portale is None:
        log.info("invio al portale spento (mancano PORTALE_URL e PORTALE_TOKEN)")

    attive: dict[str, tuple[Machine, asyncio.Task[None], dict[str, Any]]] = {}

    def parti(c: dict[str, Any]) -> None:
        m = nuova_macchina(c, db)
        m.uscite = list(uscite or [])
        attive[m.name] = (m, asyncio.create_task(m.run(), name=m.name), dict(c))

    async def ferma(nome: str) -> None:
        m, task, _cfg = attive.pop(nome)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await m.stop()
        m.chiudi_intervalli()

    async def applica(nuovo: list[dict[str, Any]]) -> None:
        voluto = {str(c.get("name")): c for c in nuovo if c.get("enabled", True) and c.get("ip") and c.get("name")}
        for nome in list(attive):
            if nome not in voluto or voluto[nome] != attive[nome][2]:
                log.info("[%s] tolta, disabilitata o cambiata nell'elenco: la fermo", nome)
                await ferma(nome)
        for nome, c in voluto.items():
            if nome not in attive:
                parti(c)
        if portale is not None:
            inviate = [m for m, _t, _c in attive.values() if m.asset_tag and not m.ombra]
            for m, _t, _c in attive.values():
                m.notifica = portale.accoda_stato if m in inviate else None
            portale.machines = inviate

    async def aggiorna_elenco() -> None:
        assert portale is not None
        while True:
            await asyncio.sleep(AGGIORNA_ELENCO)
            nuovo = await asyncio.to_thread(portale.scarica_macchine)
            if nuovo is not None:
                await applica(nuovo)
                if copia_path:
                    copia_path.write_text(json.dumps({"machines": nuovo}, indent=1), encoding="utf-8")

    await applica(elenco)
    log.info("collector avviato: %d macchine", len(attive))
    def tutte() -> list[Machine]:
        return [m for m, _t, _c in attive.values()]

    def battito_uscite() -> None:
        for m in tutte():
            m.scrivi_uscite()

    servizi = [status_printer(tutte), sorveglia_orologio(Orologio(log)),
               ripeti(SALUTE, lambda: log.info("%s", riga_salute(tutte(), db, portale)))]
    if uscite:
        servizi.append(ripeti(HEARTBEAT_USCITE, battito_uscite))
    if portale is not None:
        servizi += [portale.run(), aggiorna_elenco()]
    try:
        await asyncio.gather(*servizi)
    finally:
        for nome in list(attive):
            await ferma(nome)
        for uscita in uscite or []:
            uscita.close()
        log.info("%s", riga_salute([], db, portale))
        db.chiudi()
        log.info("collector fermato")


def configura_log(debug: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("asyncua", "asyncio", "pyLSV2", "LSV2 Client"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

if __name__ == "__main__":
    from cli import esegui   # sul PC dell'officina: la riga di comando sta in cli.py

    sys.exit(esegui())
