"""
collector.py - Collector OPC UA per le macchine DMG MORI (IoTconnector)

SOLO LETTURA: legge valori e sfoglia l'albero. Non scrive valori e non
chiama metodi (nemmeno ConditionRefresh: gli allarmi sono letti a polling).

Gestisce i due modelli dati trovati in officina:
  - umati / OPC UA for Machine Tools (es. DM16, DM17)
  - DMG MORI BasicDataSet (es. DM6, DM9, DM10, DM11, DM12, DM13, DM15)

Uso:
  py collector.py                      # usa machines.json e machines.db
  py collector.py --config machines.json --db machines.db

Con il NOVICROM HUB (vedi portale.py e README.md): con le variabili d'ambiente PORTALE_URL e
PORTALE_TOKEN l'elenco delle macchine arriva dal portale (Asset › Configurazione › Macchine
collegate, riletto ogni 5 minuti: macchine aggiunte, tolte o cambiate senza riavviare) e lo
stato, gli allarmi e i contatori vanno al portale. Senza portale si usa machines.json.

Requisiti: pip install asyncua
"""
import argparse
import asyncio
import datetime as dt
import json
import logging
import sqlite3
from pathlib import Path

try:   # dentro il portale (manage.py collector_cnc)
    from .drivers import opcua
    from .drivers.opcua import CONNECT_TIMEOUT, DMG_MACHINE_URI, MODELS, UMATI_URI, text
    from .portale import AGGIORNA_ELENCO, Portale
except ImportError:   # sul PC dell'officina (py collector.py)
    from drivers import opcua
    from drivers.opcua import CONNECT_TIMEOUT, DMG_MACHINE_URI, MODELS, UMATI_URI, text
    from portale import AGGIORNA_ELENCO, Portale

__all__ = ["CONNECT_TIMEOUT", "DMG_MACHINE_URI", "MODELS", "UMATI_URI", "text"]   # usati da cerca.py e dai test

# ----------------------------------------------------------------------------
# Parametri
# ----------------------------------------------------------------------------
FAST_PERIOD = 2          # s - lettura stato (esecuzione, modo, emergenza...)
ALARM_PERIOD = 5         # s - lettura allarmi attivi
COUNTER_PERIOD = 60      # s - lettura contatori (ore, pezzi)
STATUS_PRINT_PERIOD = 300 # s - riepilogo a video (solo se qualcosa e' cambiato)
RETRY_MIN, RETRY_MAX = 10, 120  # s - attesa tra i tentativi di riconnessione
ALARM_SEVERITY = 801     # da questa severita' un messaggio e' un allarme vero
# condition "segnaposto" senza significato (es. 0/0000-0000 su DM13): ignorate
IGNORE_CODES = {"0/0000-0000"}
# a video si stampano solo i messaggi da questa severita' in su (nel database finiscono tutti)
PRINT_MIN_SEVERITY = 401

# Stati comuni (ordine = priorita' di valutazione, vedi compute_state)
OFFLINE, EMERGENZA, ALLARME, LAVORO, SETUP, INTERROTTA, FERMA = (
    "OFFLINE", "EMERGENZA", "ALLARME", "LAVORO", "SETUP", "INTERROTTA", "FERMA")

log = logging.getLogger("collector")


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def ts(d):
    return d.strftime("%Y-%m-%d %H:%M:%S")


def local_hms(d):
    return d.replace(tzinfo=dt.timezone.utc).astimezone().strftime("%H:%M:%S")


def prog_name(path):
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
# Database
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    name TEXT PRIMARY KEY, ip TEXT, serial TEXT, model TEXT, department TEXT,
    data_model TEXT, server_version TEXT, last_seen_utc TEXT
);
-- Intervalli di stato: una riga per ogni periodo continuo nello stesso stato
CREATE TABLE IF NOT EXISTS state_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine TEXT NOT NULL, state TEXT NOT NULL,
    start_utc TEXT NOT NULL, end_utc TEXT,
    program TEXT, mode TEXT, exec TEXT, alarm_code TEXT
);
CREATE INDEX IF NOT EXISTS ix_state ON state_log(machine, start_utc);
-- Ogni cambio di valore dei segnali (per analisi e debug)
CREATE TABLE IF NOT EXISTS signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine TEXT NOT NULL, ts_utc TEXT NOT NULL, signal TEXT NOT NULL, value TEXT
);
CREATE INDEX IF NOT EXISTS ix_signal ON signal_log(machine, ts_utc);
-- Allarmi e messaggi: comparsa e rientro
CREATE TABLE IF NOT EXISTS alarm_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine TEXT NOT NULL, code TEXT NOT NULL, message TEXT, severity INTEGER,
    start_utc TEXT NOT NULL, end_utc TEXT, machine_time_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_alarm ON alarm_log(machine, start_utc);
-- Contatori, una riga al minuto
CREATE TABLE IF NOT EXISTS counter_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine TEXT NOT NULL, ts_utc TEXT NOT NULL,
    run_time INTEGER, part_counter INTEGER, parts_overall INTEGER,
    operation_time INTEGER, power_on_time INTEGER
);
CREATE INDEX IF NOT EXISTS ix_counter ON counter_log(machine, ts_utc);
"""


class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def x(self, sql, args=()):
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur

    def close_dangling(self):
        """All'avvio: chiude intervalli e allarmi rimasti aperti dall'ultima
        esecuzione, all'ultimo istante in cui la macchina era stata vista.
        Il periodo in cui il collector era spento resta 'senza dati'."""
        for (name, last_seen) in self.x("SELECT name, last_seen_utc FROM machines").fetchall():
            if not last_seen:
                continue
            self.x("UPDATE state_log SET end_utc=? WHERE machine=? AND end_utc IS NULL",
                   (last_seen, name))
            self.x("UPDATE alarm_log SET end_utc=? WHERE machine=? AND end_utc IS NULL",
                   (last_seen, name))
        # righe di macchine mai viste: chiuse sul proprio inizio
        self.x("UPDATE state_log SET end_utc=start_utc WHERE end_utc IS NULL")
        self.x("UPDATE alarm_log SET end_utc=start_utc WHERE end_utc IS NULL")


# ----------------------------------------------------------------------------
# Macchina
# ----------------------------------------------------------------------------
class Machine:
    def __init__(self, cfg, db):
        self.name = cfg["name"]
        self.ip = cfg["ip"]
        self.port = cfg.get("port", 4840)
        self.serial = cfg.get("serial", "")
        self.model_name = cfg.get("model", "")
        self.department = cfg.get("department", "")
        self.asset_tag = cfg.get("asset_tag", "")   # codice dell'asset nel portale (vuoto = non inviata)
        self.hours_unit = cfg.get("hours_unit") or ""  # unita' delle ore scelta nel portale (h | min | s), vuoto = dal modello
        self.found_serial = ""      # matricola letta dal namespace DMG MORI del server
        # credenziali OPC UA opzionali (per server che rifiutano l'accesso anonimo)
        self.username = cfg.get("username") or None
        self.password = cfg.get("password") or None
        self.ignored = set()        # condition segnaposto da non registrare
        self.url = f"opc.tcp://{self.ip}:{self.port}"
        self.db = db

        self.data_model = None      # "umati" | "bds"
        self.spec = None
        self.values = {}            # segnale -> ultimo valore
        self.colors = {}            # light1..4 -> nome colore
        self.alarms = {}            # nodeid condition -> dict(code, message, severity, row)
        self.state = None
        self.state_row = None
        self.state_key = None
        self.state_since = None     # inizio dello stato attuale (UTC), per il portale
        self.portale_cambiata = False
        self.counters_at = None     # ultima lettura dei contatori (UTC)
        self.last_seen = None

        db.x("""INSERT INTO machines(name, ip, serial, model, department) VALUES(?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET ip=excluded.ip, serial=excluded.serial,
                model=excluded.model, department=excluded.department""",
             (self.name, self.ip, self.serial, self.model_name, self.department))

    # ---------------- stato comune ----------------
    def compute_state(self, online=True):
        if not online:
            return OFFLINE, None
        v, spec = self.values, self.spec
        if v.get("estop") is True:
            return EMERGENZA, None
        hard = [a for a in self.alarms.values() if (a["severity"] or 0) >= ALARM_SEVERITY]
        if hard:
            return ALLARME, hard[0]["code"]
        if self.data_model == "bds" and (v.get("n_alarms") or 0) > 0:
            return ALLARME, None
        ex = spec["exec_map"].get(v.get("exec"))
        md = spec["mode_map"].get(v.get("mode"))
        if ex == "RUNNING":
            return (LAVORO if md == "AUTO" else SETUP), None
        if ex == "INTERRUPTED":
            return INTERROTTA, None
        return FERMA, None

    def update_state(self, online=True):
        now = utcnow()
        state, alarm_code = self.compute_state(online)
        spec = self.spec or {}
        program = prog_name(self.values.get("program")) if online else ""
        mode = spec.get("mode_map", {}).get(self.values.get("mode"), "") if online else ""
        ex = spec.get("exec_map", {}).get(self.values.get("exec"), "") if online else ""
        key = (state, program, alarm_code)
        if key == self.state_key:
            return
        if self.state_row is not None:
            self.db.x("UPDATE state_log SET end_utc=? WHERE id=?", (ts(now), self.state_row))
        cur = self.db.x("""INSERT INTO state_log(machine, state, start_utc, program, mode, exec, alarm_code)
                           VALUES(?,?,?,?,?,?,?)""",
                        (self.name, state, ts(now), program, mode, ex, alarm_code))
        self.portale_cambiata = True
        if state != self.state:
            self.state_since = now
            extra = f"  prog={program}" if program else ""
            extra += f"  allarme={alarm_code}" if alarm_code else ""
            print(f"{local_hms(now)}  {self.name:<5} {self.state or '-':>10} -> {state:<10}{extra}")
        self.state_row, self.state_key, self.state = cur.lastrowid, key, state

    def touch(self):
        self.last_seen = utcnow()

    def flush_last_seen(self):
        if self.last_seen:
            self.db.x("UPDATE machines SET last_seen_utc=? WHERE name=?",
                      (ts(self.last_seen), self.name))

    # ---------------- connessione ----------------
    async def run(self):
        delay = RETRY_MIN
        while True:
            try:
                async with opcua.sessione(self.url, self.username, self.password, self.name) as client:
                    await self.session(await opcua.DriverOpcUa.rileva(client, self.name))
                delay = RETRY_MIN
                self.last_err = None
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - qualunque errore OPC UA = macchina offline, si ritenta
                log.debug("%s: %s", self.name, e)
                err = type(e).__name__
                if self.state != OFFLINE or err != getattr(self, "last_err", None):
                    self.last_err = err
                    if "Identity" in err or "UserAccessDenied" in err:
                        log.warning("%s rifiuta l'accesso %s (%s): servono utente e password OPC UA validi "
                                    "(portale: Macchine collegate > Modifica; senza portale: machines.json)",
                                    self.name, "con queste credenziali" if self.username else "anonimo", err)
                    else:
                        log.warning("%s non raggiungibile (%s), ritento ogni %ss",
                                    self.name, err, delay)
            # fuori sessione: macchina offline
            self.alarms_close_all()
            self.update_state(online=False)
            self.flush_last_seen()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX)

    async def session(self, drv):
        """Una sessione aperta: ``drv`` è il ``DriverOpcUa`` (solo letture), qui stato e database."""
        self.data_model = drv.data_model
        self.spec = drv.spec
        found_serial = drv.found_serial
        self.found_serial = found_serial
        if self.serial and found_serial != self.serial:
            log.warning("%s: matricola attesa %s ma il server riporta %s (IP cambiato?)",
                        self.name, self.serial, found_serial)

        fast = await drv.resolve(self.spec["fast"])
        counters = await drv.resolve(self.spec["counters"])
        static = await drv.resolve(self.spec["static"])
        if "exec" not in fast:
            raise RuntimeError("nodo di stato canale assente: serve opcua_browse.py")

        version = await drv.server_version()
        self.db.x("UPDATE machines SET data_model=?, server_version=? WHERE name=?",
                  (self.data_model, version, self.name))

        # colori del semaforo (configurazione statica)
        self.colors.update(await drv.colors(static))

        alarm_folder = drv.node(self.spec["alarm_folder"])
        print(f"{local_hms(utcnow())}  {self.name:<5} connessa ({self.data_model}"
              f"{', v' + version if version else ''}) - {len(fast)} segnali")

        t_alarm = t_counter = 0.0
        loop = asyncio.get_running_loop()
        while True:
            t0 = loop.time()
            await self.read_fast(drv, fast)
            if t0 >= t_alarm:
                await self.read_alarms(drv, alarm_folder)
                t_alarm = t0 + ALARM_PERIOD
            self.touch()
            self.update_state()
            if t0 >= t_counter:
                await self.read_counters(drv, counters)
                self.flush_last_seen()
                t_counter = t0 + COUNTER_PERIOD
            await asyncio.sleep(max(0.2, FAST_PERIOD - (loop.time() - t0)))

    # ---------------- letture ----------------
    async def read_fast(self, drv, fast):
        letti = await drv.read_fast(fast)
        now = ts(utcnow())
        for name, val in letti:
            if self.values.get(name, "__nuovo__") != val:
                self.values[name] = val
                self.db.conn.execute(
                    "INSERT INTO signal_log(machine, ts_utc, signal, value) VALUES(?,?,?,?)",
                    (self.name, now, name, None if val is None else str(val)))
        self.db.conn.commit()

    async def read_counters(self, drv, counters):
        if not counters:
            return
        row = await drv.read_counters(counters)
        self.values.update({f"cnt_{k}": v for k, v in row.items()})
        self.counters_at = utcnow()
        self.db.x("""INSERT INTO counter_log(machine, ts_utc, run_time, part_counter,
                     parts_overall, operation_time, power_on_time) VALUES(?,?,?,?,?,?,?)""",
                  (self.name, ts(utcnow()), row.get("run_time"), row.get("part_counter"),
                   row.get("parts_overall"), row.get("operation_time"), row.get("power_on_time")))

    async def read_alarms(self, drv, folder):
        conds = await drv.conditions(folder)
        if not conds:
            return
        now = utcnow()
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
                mtime = ts(mtime.astimezone(dt.timezone.utc).replace(tzinfo=None))                     if isinstance(mtime, dt.datetime) and mtime.tzinfo else (ts(mtime) if isinstance(mtime, dt.datetime) else None)
                cur = self.db.x("""INSERT INTO alarm_log(machine, code, message, severity,
                                   start_utc, machine_time_utc) VALUES(?,?,?,?,?,?)""",
                                (self.name, code, msg, sev, ts(now), mtime))
                self.alarms[key] = {"code": code, "message": msg, "severity": sev, "row": cur.lastrowid, "since": now}
                self.portale_cambiata = True
                if (sev or 0) >= PRINT_MIN_SEVERITY:
                    print(f"{local_hms(now)}  {self.name:<5} + msg {code} (sev {sev}) {msg}")
            elif not active and key in self.alarms:
                a = self.alarms.pop(key)
                self.portale_cambiata = True
                self.db.x("UPDATE alarm_log SET end_utc=? WHERE id=?", (ts(now), a["row"]))
                if (a["severity"] or 0) >= PRINT_MIN_SEVERITY:
                    print(f"{local_hms(now)}  {self.name:<5} - msg {a['code']} rientrato")

    def alarms_close_all(self):
        now = ts(utcnow())
        for a in self.alarms.values():
            self.db.x("UPDATE alarm_log SET end_utc=? WHERE id=?", (now, a["row"]))
        self.alarms.clear()
        self.ignored.clear()


# ----------------------------------------------------------------------------
# Riepilogo a video
# ----------------------------------------------------------------------------
async def status_printer(elenco):
    last = None
    while True:
        await asyncio.sleep(STATUS_PRINT_PERIOD)
        rows = []
        for m in elenco():
            v = m.values
            lights = ",".join(m.colors.get(k, "?") for k in ("light1", "light2", "light3", "light4")
                              if v.get(k) not in (None, False)) or "-"
            pezzi = v.get("cnt_part_counter")
            rows.append(f"{m.name:<9}{(m.state or '-'):<12}{prog_name(v.get('program'))[:25]:<26}"
                        f"{'' if pezzi is None else pezzi:>7}{len(m.alarms):>9}  {lights}")
        if rows == last:
            continue
        last = rows
        print("\n" + "-" * 79)
        print(f"{'Macchina':<9}{'Stato':<12}{'Programma':<26}{'Pezzi':>7}{'Messaggi':>9}  Semaforo")
        print("\n".join(rows))
        print("-" * 79 + "\n")


async def avvia(portale, db_path, config_path=None, copia_path=None):
    """Legge le macchine finché non viene fermato.

    ``portale``: dove prendere l'elenco e mandare stato e contatori (``Portale`` via HTTP dal PC
    dell'officina, ``PortaleDiretto`` dentro il portale) oppure None (solo machines.json, nessun invio).
    ``copia_path``: dove tenere l'ultimo elenco scaricato, per ripartire se il portale non risponde.
    """
    db = DB(db_path)
    db.close_dangling()
    elenco = None
    if portale is not None:
        elenco = await asyncio.to_thread(portale.scarica_macchine)
        if elenco is not None:
            if copia_path:
                copia_path.write_text(json.dumps({"machines": elenco}, indent=1), encoding="utf-8")
            print(f"Elenco delle macchine dal portale: {len(elenco)}.")
        elif copia_path and copia_path.exists():
            elenco = json.loads(copia_path.read_text(encoding="utf-8"))["machines"]
            print(f"Portale non raggiungibile: uso l'ultimo elenco scaricato ({len(elenco)} macchine).")
    if elenco is None:
        elenco = json.loads(config_path.read_text(encoding="utf-8"))["machines"] if config_path and config_path.exists() else []
        print(f"Elenco delle macchine da {config_path.name if config_path else '(nessun file)'}: {len(elenco)}.")
    if portale is None:
        print("Invio al portale spento (mancano PORTALE_URL e PORTALE_TOKEN).")

    attive = {}   # nome -> (Machine, task, configurazione)

    def parti(c):
        m = Machine(c, db)
        attive[m.name] = (m, asyncio.create_task(m.run(), name=m.name), dict(c))

    def ferma(nome):
        m, task, _cfg = attive.pop(nome)
        task.cancel()
        now = ts(utcnow())
        if m.state_row:
            db.x("UPDATE state_log SET end_utc=? WHERE id=?", (now, m.state_row))
        for a in m.alarms.values():
            db.x("UPDATE alarm_log SET end_utc=? WHERE id=?", (now, a["row"]))
        m.flush_last_seen()

    def applica(nuovo):
        voluto = {str(c.get("name")): c for c in nuovo if c.get("enabled", True) and c.get("ip") and c.get("name")}
        for nome in list(attive):
            if nome not in voluto or voluto[nome] != attive[nome][2]:
                print(f"{local_hms(utcnow())}  {nome:<5} tolta o cambiata nel portale: la fermo")
                ferma(nome)
        for nome, c in voluto.items():
            if nome not in attive:
                parti(c)
        if portale is not None:
            portale.machines = [m for m, _t, _c in attive.values() if m.asset_tag]

    async def aggiorna_elenco():
        while True:
            await asyncio.sleep(AGGIORNA_ELENCO)
            nuovo = await asyncio.to_thread(portale.scarica_macchine)
            if nuovo is not None:
                applica(nuovo)
                if copia_path:
                    copia_path.write_text(json.dumps({"machines": nuovo}, indent=1), encoding="utf-8")

    applica(elenco)
    print(f"Collector avviato: {len(attive)} macchine, database {Path(db_path).resolve()}.\n")
    servizi = [status_printer(lambda: [m for m, _t, _c in attive.values()])]
    if portale is not None:
        servizi += [portale.run(), aggiorna_elenco()]
    try:
        await asyncio.gather(*servizi)
    finally:
        for nome in list(attive):
            ferma(nome)


def configura_log(debug=False):
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("asyncua", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


async def main():
    """Avvio dal PC dell'officina: py collector.py [--config machines.json] [--db machines.db]."""
    ap = argparse.ArgumentParser(description="Collector OPC UA DMG MORI (sola lettura)")
    here = Path(__file__).resolve().parent   # file accanto allo script, da qualunque cartella lo lanci
    ap.add_argument("--config", default=str(here / "machines.json"))
    ap.add_argument("--db", default=str(here / "machines.db"))
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    configura_log(args.debug)
    config = Path(args.config)
    await avvia(Portale.da_ambiente([], prog_name), args.db, config, config.with_name("machines.portale.json"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCollector fermato.")
