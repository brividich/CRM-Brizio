"""machines.db: registro locale del collector (stati, segnali, allarmi, contatori) e coda verso il portale.

Scritture robuste a un database bloccato (un altro processo che lo legge, un antivirus, un backup):
ogni scrittura entra in una coda in memoria e la coda si svuota in un'unica transazione; se SQLite
risponde «database is locked» la transazione si annulla e si riprova alla scrittura successiva, nello
stesso ordine. Nessuna scrittura dipende da ``lastrowid``: gli intervalli aperti si chiudono per
macchina (e per condition, negli allarmi).

``outbox``: i record per il portale (eventi di stato, letture dei contatori) restano qui finché il
portale non li ha ricevuti, poi si cancellano. L'``id`` crescente e l'``istanza`` del database
formano la chiave dell'evento (``istanza:id``) con cui il portale scarta i doppioni.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any

try:
    from .stati import LogLimitato
except ImportError:   # sul PC dell'officina
    from stati import LogLimitato  # type: ignore[no-redef]

TIMEOUT_DB = 2.0             # s di attesa di SQLite su un database bloccato, per ogni tentativo
MAX_IN_ATTESA = 200_000      # scritture tenute in memoria con il database bloccato
MAX_OUTBOX = 500_000         # record in coda per il portale (oltre: si scartano i più vecchi, con log)

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
-- Contatori
CREATE TABLE IF NOT EXISTS counter_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine TEXT NOT NULL, ts_utc TEXT NOT NULL,
    run_time INTEGER, part_counter INTEGER, parts_overall INTEGER,
    operation_time INTEGER, power_on_time INTEGER
);
CREATE INDEX IF NOT EXISTS ix_counter ON counter_log(machine, ts_utc);
-- Coda verso il portale (store-and-forward)
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL, machine TEXT NOT NULL, corpo TEXT NOT NULL, creato_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (chiave TEXT PRIMARY KEY, valore TEXT);
"""

log = logging.getLogger("collector")


class DB:
    """machines.db con scritture in coda (resistenti al blocco del file) e outbox per il portale."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, timeout=TIMEOUT_DB, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        colonne = {r[1] for r in self.conn.execute("PRAGMA table_info(alarm_log)")}
        if "cond_key" not in colonne:   # machines.db creati dalle versioni precedenti
            self.conn.execute("ALTER TABLE alarm_log ADD COLUMN cond_key TEXT")
        self.conn.commit()
        self.in_attesa: list[tuple[str, tuple[Any, ...]]] = []
        self.avvisi = LogLimitato(log, 60.0)
        self.bloccato = False
        self.scartate = 0
        riga = self.conn.execute("SELECT valore FROM meta WHERE chiave='istanza'").fetchone()
        if riga:
            self.istanza = str(riga[0])
        else:
            self.istanza = uuid.uuid4().hex[:12]
            self.conn.execute("INSERT INTO meta(chiave, valore) VALUES('istanza', ?)", (self.istanza,))
            self.conn.commit()

    # ---------------- scritture e letture ----------------
    def x(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> bool:
        """Accoda una scrittura e prova a scaricare la coda; False se il database è bloccato (si riprova dopo)."""
        self.in_attesa.append((sql, tuple(args)))
        if len(self.in_attesa) > MAX_IN_ATTESA:
            del self.in_attesa[0]
            self.scartate += 1
            self.avvisi.warning("scartate", "machines.db bloccato da troppo tempo: scartate le scritture più vecchie")
        return self.scarica()

    def scarica(self) -> bool:
        if not self.in_attesa:
            return True
        try:
            for sql, args in self.in_attesa:
                self.conn.execute(sql, args)
            self.conn.commit()
        except sqlite3.OperationalError as e:
            try:
                self.conn.rollback()
            except sqlite3.Error as e2:
                log.debug("rollback di machines.db non riuscito: %s", e2)
            if not self.bloccato:
                self.bloccato = True
            self.avvisi.warning("bloccato", "machines.db non scrivibile (%s): %d scritture in attesa, riprovo",
                                e, len(self.in_attesa))
            return False
        self.in_attesa.clear()
        if self.bloccato:
            self.bloccato = False
            log.info("machines.db di nuovo scrivibile")
        return True

    def q(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        """Lettura; con il database bloccato ritorna una lista vuota (e lo dice nel log)."""
        self.scarica()
        try:
            return list(self.conn.execute(sql, args).fetchall())
        except sqlite3.OperationalError as e:
            self.avvisi.warning("lettura", "machines.db non leggibile (%s): riprovo al prossimo giro", e)
            return []

    def chiudi(self) -> None:
        self.scarica()
        self.conn.close()

    # ---------------- avvio ----------------
    def close_dangling(self) -> None:
        """All'avvio: chiude intervalli e allarmi rimasti aperti dall'ultima
        esecuzione, all'ultimo istante in cui la macchina era stata vista.
        Il periodo in cui il collector era spento resta 'senza dati'."""
        for (name, last_seen) in self.q("SELECT name, last_seen_utc FROM machines"):
            if not last_seen:
                continue
            self.x("UPDATE state_log SET end_utc=? WHERE machine=? AND end_utc IS NULL", (last_seen, name))
            self.x("UPDATE alarm_log SET end_utc=? WHERE machine=? AND end_utc IS NULL", (last_seen, name))
        # righe di macchine mai viste: chiuse sul proprio inizio
        self.x("UPDATE state_log SET end_utc=start_utc WHERE end_utc IS NULL")
        self.x("UPDATE alarm_log SET end_utc=start_utc WHERE end_utc IS NULL")

    def ultimi_contatori(self, macchina: str) -> tuple[int | None, int | None]:
        """``(part_counter, parts_overall)`` dell'ultima riga dei contatori della macchina."""
        righe = self.q("SELECT part_counter, parts_overall FROM counter_log WHERE machine=? ORDER BY id DESC LIMIT 1",
                       (macchina,))
        if not righe:
            return None, None
        return righe[0][0], righe[0][1]

    # ---------------- meta ----------------
    def meta(self, chiave: str) -> str | None:
        righe = self.q("SELECT valore FROM meta WHERE chiave=?", (chiave,))
        return str(righe[0][0]) if righe else None

    def imposta_meta(self, chiave: str, valore: str) -> None:
        self.x("INSERT INTO meta(chiave, valore) VALUES(?, ?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
               (chiave, valore))

    # ---------------- outbox ----------------
    def accoda(self, path: str, macchina: str, corpo: str, creato_utc: str) -> None:
        self.x("INSERT INTO outbox(path, machine, corpo, creato_utc) VALUES(?,?,?,?)", (path, macchina, corpo, creato_utc))

    def da_inviare(self, limite: int = 200) -> list[tuple[int, str, str, str]]:
        """I record più vecchi della coda, in ordine: ``(id, path, macchina, corpo)``."""
        return [(int(r[0]), str(r[1]), str(r[2]), str(r[3]))
                for r in self.q("SELECT id, path, machine, corpo FROM outbox ORDER BY id LIMIT ?", (limite,))]

    def inviati(self, fino_a: int) -> None:
        self.x("DELETE FROM outbox WHERE id <= ?", (fino_a,))

    def in_coda(self) -> int:
        righe = self.q("SELECT COUNT(*) FROM outbox")
        return int(righe[0][0]) if righe else 0

    def pota_outbox(self) -> int:
        """Oltre ``MAX_OUTBOX`` record si scartano i più vecchi; ritorna quanti."""
        n = self.in_coda()
        if n <= MAX_OUTBOX:
            return 0
        togli = n - MAX_OUTBOX
        self.x("DELETE FROM outbox WHERE id IN (SELECT id FROM outbox ORDER BY id LIMIT ?)", (togli,))
        log.error("coda verso il portale oltre %d record: scartati i %d più vecchi", MAX_OUTBOX, togli)
        return togli
