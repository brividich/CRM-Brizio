"""Lettura delle timbrature dal database Solari (sola lettura).

Porting della query di ``report_presenze.py`` (script del diskstation che generava
CN-PRESENZE.pdf): un dipendente è **presente** se la sua ultima timbratura del
giorno ha verso ``E`` (entrata). Il turno «N» (normale) viene da ``ASSELEMGEN``
con l'elemento ``SOLARI_TURNO_NORMALE_ELEM`` (34013 sul gestionale Novicrom).

Connessione da ``.env``: ``SOLARI_DB_SERVER``, ``SOLARI_DB_USER``,
``SOLARI_DB_PASSWORD``, ``SOLARI_DB_DRIVER``, ``SOLARI_DB_ANAGRAFICO``,
``SOLARI_DB_TIMBRATURE``, ``SOLARI_DB_ENCRYPT``, ``SOLARI_DB_TRUST_CERT``. Usare un login con il solo ``db_datareader``: il portale
non scrive mai su Solari. Il server è SQL Server 2016: niente ``STRING_AGG``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

DRIVER_PREDEFINITO = "{ODBC Driver 17 for SQL Server}"
_NOME_DB = re.compile(r"^[A-Za-z0-9_]+$")


class SolariNonConfigurato(RuntimeError):
    """Mancano le chiavi ``SOLARI_DB_*`` nel ``.env``."""


@dataclass(frozen=True)
class Configurazione:
    server: str
    user: str
    password: str
    driver: str
    db_anagrafico: str
    db_timbrature: str
    turno_elem: int
    encrypt: str = ""
    trust_cert: str = ""

    def connection_string(self) -> str:
        if self.user:
            auth = f"UID={self.user};PWD={self.password};"
        else:
            auth = "Trusted_Connection=yes;"
        # ODBC Driver 18 cifra per default e rifiuta i certificati autofirmati dei server
        # SQL più vecchi: SOLARI_DB_ENCRYPT / SOLARI_DB_TRUST_CERT lo regolano.
        extra = ""
        if self.encrypt:
            extra += f"Encrypt={self.encrypt};"
        if self.trust_cert:
            extra += f"TrustServerCertificate={self.trust_cert};"
        return f"DRIVER={self.driver};SERVER={self.server};{auth}{extra}"


def configurazione() -> Configurazione:
    from config.env_config import get_first_env_value

    server = get_first_env_value("SOLARI_DB_SERVER")
    if not server:
        raise SolariNonConfigurato("Database timbrature Solari non configurato (SOLARI_DB_SERVER nel .env).")
    db_ana = get_first_env_value("SOLARI_DB_ANAGRAFICO", default="dbstartPRV")
    db_tim = get_first_env_value("SOLARI_DB_TIMBRATURE", default="dbstartBIZ")
    for nome in (db_ana, db_tim):
        # I nomi dei database finiscono nella query fra parentesi quadre: solo caratteri sicuri.
        if not _NOME_DB.match(nome):
            raise SolariNonConfigurato(f"Nome database Solari non valido: {nome!r}")
    try:
        turno = int(get_first_env_value("SOLARI_TURNO_NORMALE_ELEM", default="34013"))
    except ValueError:
        turno = 34013
    return Configurazione(
        server=server,
        user=get_first_env_value("SOLARI_DB_USER"),
        password=get_first_env_value("SOLARI_DB_PASSWORD"),
        driver=get_first_env_value("SOLARI_DB_DRIVER", default=DRIVER_PREDEFINITO),
        db_anagrafico=db_ana,
        db_timbrature=db_tim,
        turno_elem=turno,
        encrypt=_si_no(get_first_env_value("SOLARI_DB_ENCRYPT")),
        trust_cert=_si_no(get_first_env_value("SOLARI_DB_TRUST_CERT")),
    )


def _si_no(valore: str) -> str:
    """'1/true/yes/si' -> 'yes', '0/false/no' -> 'no', vuoto -> '' (default del driver)."""
    v = (valore or "").strip().lower()
    if v in {"1", "true", "yes", "si", "sì", "on"}:
        return "yes"
    if v in {"0", "false", "no", "off"}:
        return "no"
    return ""


def configurato() -> bool:
    try:
        configurazione()
    except SolariNonConfigurato:
        return False
    return True


def _connetti(cfg: Configurazione):
    import pyodbc

    return pyodbc.connect(cfg.connection_string(), timeout=10, readonly=True)


def _pulisci(valore) -> str:
    return str(valore or "").strip()


def _matricola(valore) -> str:
    """Matricola come la mostrava il report: senza zeri iniziali."""
    return _pulisci(valore).lstrip("0") or ("0" if _pulisci(valore) else "")


def leggi_presenti(giorno: date | None = None) -> list[dict]:
    """Dipendenti con ultima timbratura del giorno in entrata.

    ``[{solari_id, matricola, cognome, nome, codice_fiscale, entrata, badge, turno}]``,
    con ``entrata`` = ora dell'ultima timbratura (un'entrata).
    """
    cfg = configurazione()
    giorno = giorno or date.today()
    inizio = datetime.combine(giorno, time.min)
    fine = inizio + timedelta(days=1)
    ana, tim = cfg.db_anagrafico, cfg.db_timbrature
    query = f"""
        SELECT a.ID, a.MATRICOLA, a.COGNOME, a.NOME, a.CODFISC,
               t.DATAV, t.BADGE,
               CASE WHEN turno.IDDIP IS NOT NULL THEN 'N' ELSE '' END AS TURNO
        FROM [{ana}].[dbo].[ANAGRAFICO_DATI] a
        INNER JOIN (
            SELECT t1.IDDIP, t1.DATAV, t1.VERSOV, t1.BADGE
            FROM [{tim}].[dbo].[TIMBRATURE] t1
            INNER JOIN (
                SELECT IDDIP, MAX(DATAV) AS MAX_DATAV
                FROM [{tim}].[dbo].[TIMBRATURE]
                WHERE DATAV >= ? AND DATAV < ?
                GROUP BY IDDIP
            ) t2 ON t1.IDDIP = t2.IDDIP AND t1.DATAV = t2.MAX_DATAV
        ) t ON a.ID = t.IDDIP
        LEFT JOIN (
            SELECT DISTINCT IDDIP FROM [{tim}].[dbo].[ASSELEMGEN]
            WHERE IDELEM = ? AND DATAINIZIO <= ? AND (DATAFINE IS NULL OR DATAFINE >= ?)
        ) turno ON a.ID = turno.IDDIP
        WHERE t.VERSOV = 'E'
        ORDER BY a.COGNOME, a.NOME
    """
    conn = _connetti(cfg)
    try:
        cur = conn.cursor()
        cur.execute(query, (inizio, fine, cfg.turno_elem, inizio, inizio))
        righe = cur.fetchall()
    finally:
        conn.close()
    visti: set[int] = set()
    risultato = []
    for r in righe:
        # Due timbrature allo stesso istante darebbero due righe: ne teniamo una.
        if int(r[0]) in visti:
            continue
        visti.add(int(r[0]))
        risultato.append({
            "solari_id": int(r[0]),
            "matricola": _matricola(r[1]),
            "cognome": _pulisci(r[2]),
            "nome": _pulisci(r[3]),
            "codice_fiscale": _pulisci(r[4]).upper(),
            "entrata": r[5],
            "badge": _pulisci(r[6]),
            "turno": _pulisci(r[7]),
        })
    return risultato


def leggi_uscite_mancanti(dal: date, al: date) -> list[dict]:
    """Giorni chiusi con l'ultima timbratura in entrata: uscita dimenticata.

    Cerca fra ``dal`` e ``al`` compresi (giorni passati: oggi non è ancora chiuso).
    ``[{solari_id, matricola, cognome, nome, codice_fiscale, giorno, entrata}]``.
    """
    cfg = configurazione()
    inizio = datetime.combine(dal, time.min)
    fine = datetime.combine(al, time.min) + timedelta(days=1)
    ana, tim = cfg.db_anagrafico, cfg.db_timbrature
    query = f"""
        SELECT a.ID, a.MATRICOLA, a.COGNOME, a.NOME, a.CODFISC, t1.DATAV
        FROM [{tim}].[dbo].[TIMBRATURE] t1
        INNER JOIN (
            SELECT IDDIP, CAST(DATAV AS date) AS GIORNO, MAX(DATAV) AS MAX_DATAV
            FROM [{tim}].[dbo].[TIMBRATURE]
            WHERE DATAV >= ? AND DATAV < ?
            GROUP BY IDDIP, CAST(DATAV AS date)
        ) t2 ON t1.IDDIP = t2.IDDIP AND t1.DATAV = t2.MAX_DATAV
        INNER JOIN [{ana}].[dbo].[ANAGRAFICO_DATI] a ON a.ID = t1.IDDIP
        WHERE t1.VERSOV = 'E'
        ORDER BY t1.DATAV DESC, a.COGNOME, a.NOME
    """
    conn = _connetti(cfg)
    try:
        cur = conn.cursor()
        cur.execute(query, (inizio, fine))
        righe = cur.fetchall()
    finally:
        conn.close()
    visti: set[tuple[int, date]] = set()
    risultato = []
    for r in righe:
        chiave = (int(r[0]), r[5].date())
        if chiave in visti:
            continue
        visti.add(chiave)
        risultato.append({
            "solari_id": int(r[0]),
            "matricola": _matricola(r[1]),
            "cognome": _pulisci(r[2]),
            "nome": _pulisci(r[3]),
            "codice_fiscale": _pulisci(r[4]).upper(),
            "giorno": r[5].date(),
            "entrata": r[5],
        })
    return risultato


def leggi_matricole() -> dict[str, str]:
    """{matricola senza zeri iniziali, maiuscola: codice fiscale} di tutta l'anagrafica Solari.

    Serve all'import degli incarichi dal vecchio ``config.ini`` (chiave = matricola).
    """
    cfg = configurazione()
    conn = _connetti(cfg)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT MATRICOLA, CODFISC FROM [{cfg.db_anagrafico}].[dbo].[ANAGRAFICO_DATI]")
        righe = cur.fetchall()
    finally:
        conn.close()
    return {_matricola(m).upper(): _pulisci(cf).upper() for m, cf in righe if _pulisci(m)}
