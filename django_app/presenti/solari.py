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
    """Chi è in azienda: si guardano tutte le timbrature di oggi, non solo l'ultima.

    Presente = ultima timbratura in entrata, **oppure** le ultime due sono uscite di fila
    (E · U · U): la seconda è il rientro timbrato col tasto sbagliato, e in un'evacuazione è
    meglio cercare una persona in più che dimenticarne una. Questi casi hanno ``verifica``.
    Turno di notte: chi è entrato ieri sera (dalle 18) e non ha ancora timbrato oggi resta
    presente per ``ORE_MAX_TURNO`` ore dall'entrata.

    ``[{solari_id, matricola, cognome, nome, codice_fiscale, entrata, badge, turno, verifica}]``,
    con ``entrata`` = ora dell'ultima timbratura.
    """
    cfg = configurazione()
    oggi_reale = date.today()
    giorno = giorno or oggi_reale
    inizio = datetime.combine(giorno, time.min)
    fine = inizio + timedelta(days=1)
    da_ieri_sera = inizio - timedelta(hours=6)
    ana, tim = cfg.db_anagrafico, cfg.db_timbrature
    query = f"""
        SELECT a.ID, a.MATRICOLA, a.COGNOME, a.NOME, a.CODFISC,
               t.DATAV, t.BADGE, t.VERSOV,
               CASE WHEN turno.IDDIP IS NOT NULL THEN 'N' ELSE '' END AS TURNO
        FROM [{tim}].[dbo].[TIMBRATURE] t
        INNER JOIN [{ana}].[dbo].[ANAGRAFICO_DATI] a ON a.ID = t.IDDIP
        LEFT JOIN (
            SELECT DISTINCT IDDIP FROM [{tim}].[dbo].[ASSELEMGEN]
            WHERE IDELEM = ? AND DATAINIZIO <= ? AND (DATAFINE IS NULL OR DATAFINE >= ?)
        ) turno ON a.ID = turno.IDDIP
        WHERE t.DATAV >= ? AND t.DATAV < ? AND t.VERSOV IN ('E', 'U')
        ORDER BY a.ID, t.DATAV
    """
    conn = _connetti(cfg)
    try:
        cur = conn.cursor()
        cur.execute(query, (cfg.turno_elem, inizio, inizio, da_ieri_sera, fine))
        righe = cur.fetchall()
    finally:
        conn.close()
    per_persona: dict[int, list] = {}
    for r in righe:
        lista = per_persona.setdefault(int(r[0]), [])
        if lista and lista[-1][5] == r[5]:
            continue  # due timbrature nello stesso istante: una sola
        lista.append(r)
    adesso = datetime.now()
    risultato = []
    for sid, tutte in per_persona.items():
        seq = [x for x in tutte if x[5] >= inizio]
        verifica = ""
        if not seq:
            # Nessuna timbratura oggi: presente solo se ieri sera è entrato per il turno di notte.
            ultima = tutte[-1]
            if (_pulisci(ultima[7]).upper() != "E" or giorno != oggi_reale
                    or adesso - ultima[5] > timedelta(hours=ORE_MAX_TURNO)):
                continue
            seq = [ultima]
            verifica = f"entrato ieri alle {_hm(ultima[5])} (turno di notte), non ha ancora timbrato oggi"
        ultima = seq[-1]
        versi = [_pulisci(x[7]).upper() for x in seq]
        if versi[-1] != "E":
            if len(versi) >= 3 and versi[-2:] == ["U", "U"] and "E" in versi:
                verifica = (f"risulta uscita alle {_hm(seq[-2][5])} e di nuovo alle {_hm(ultima[5])}: "
                            "probabile rientro timbrato come uscita")
            else:
                continue
        risultato.append({
            "solari_id": sid,
            "matricola": _matricola(ultima[1]),
            "cognome": _pulisci(ultima[2]),
            "nome": _pulisci(ultima[3]),
            "codice_fiscale": _pulisci(ultima[4]).upper(),
            "entrata": ultima[5],
            "badge": _pulisci(ultima[6]),
            "turno": _pulisci(ultima[8]),
            "verifica": verifica,
        })
    risultato.sort(key=lambda x: (x["cognome"], x["nome"]))
    return risultato


def leggi_timbrature_giorno(giorno: date | None = None) -> dict[int, dict]:
    """Tutte le timbrature E/U di un giorno per persona: ``{solari_id: {codice_fiscale, seq}}``.

    ``seq`` = ``[(istante, 'E'|'U')]`` in ordine. Serve al cruscotto per reparto (numeri
    aggregati, nessun nome in pagina).
    """
    cfg = configurazione()
    giorno = giorno or date.today()
    inizio = datetime.combine(giorno, time.min)
    fine = inizio + timedelta(days=1)
    ana, tim = cfg.db_anagrafico, cfg.db_timbrature
    query = f"""
        SELECT a.ID, a.CODFISC, t.DATAV, t.VERSOV
        FROM [{tim}].[dbo].[TIMBRATURE] t
        INNER JOIN [{ana}].[dbo].[ANAGRAFICO_DATI] a ON a.ID = t.IDDIP
        WHERE t.DATAV >= ? AND t.DATAV < ? AND t.VERSOV IN ('E', 'U')
        ORDER BY a.ID, t.DATAV
    """
    conn = _connetti(cfg)
    try:
        cur = conn.cursor()
        cur.execute(query, (inizio, fine))
        righe = cur.fetchall()
    finally:
        conn.close()
    risultato: dict[int, dict] = {}
    for sid, cf, quando, verso in righe:
        voce = risultato.setdefault(int(sid), {"codice_fiscale": _pulisci(cf).upper(), "seq": []})
        if voce["seq"] and voce["seq"][-1][0] == quando:
            continue
        voce["seq"].append((quando, _pulisci(verso).upper()))
    return risultato


# Un turno che passa la mezzanotte (entrata la sera, uscita il mattino dopo) non è un'uscita
# mancante: l'uscita del giorno dopo entro queste ore chiude l'entrata della sera.
ORE_MAX_TURNO = 16


_GIRO = {"U": ("uscita", "un rientro"), "E": ("entrata", "un'uscita")}


def _hm(d: datetime) -> str:
    return d.strftime("%H:%M")


def analizza_giornata(timbrature: list[tuple[datetime, str]], *, precedente: tuple[datetime, str] | None = None,
                      successiva: tuple[datetime, str] | None = None) -> dict | None:
    """Controlla tutte le timbrature di una giornata, non solo l'ultima.

    ``timbrature`` = ``[(istante, 'E'|'U')]`` in ordine; ``precedente`` è l'ultima del giorno
    prima, ``successiva`` la prima del giorno dopo (per i turni a cavallo della mezzanotte).
    Ritorna ``None`` se la giornata è a posto, altrimenti
    ``{tipo, problema, entrata}`` con ``tipo`` fra:

    - ``uscita_mancante``: entrate e uscite alternate, ma l'ultima è un'entrata;
    - ``verso_errato``: le ultime due sono entrate: l'ultima è quasi certamente l'uscita
      timbrata col tasto sbagliato;
    - ``sequenza_irregolare``: due entrate o due uscite di fila durante il giorno, o la
      giornata inizia con un'uscita.
    """
    seq = list(timbrature)
    if not seq:
        return None
    # Uscita al mattino che chiude il turno iniziato ieri sera: appartiene a ieri.
    if (seq[0][1] == "U" and precedente and precedente[1] == "E"
            and seq[0][0] - precedente[0] <= timedelta(hours=ORE_MAX_TURNO)):
        seq = seq[1:]
    # Entrata la sera chiusa dall'uscita di domattina: turno a cavallo della mezzanotte.
    if (seq and seq[-1][1] == "E" and successiva and successiva[1] == "U"
            and successiva[0] - seq[-1][0] <= timedelta(hours=ORE_MAX_TURNO)):
        seq = seq[:-1]
    if not seq:
        return None

    irregolari = []
    invertite = []  # timbrature singole col tasto sbagliato: girandole la sequenza torna
    atteso = "E"
    for k, (quando, verso) in enumerate(seq):
        if verso != atteso:
            if 0 < k < len(seq) - 1 and seq[k + 1][1] == verso:
                # E · U · U · U: la seconda uscita era il rientro col tasto sbagliato.
                invertite.append((k, quando, verso))
                atteso = "U" if atteso == "E" else "E"  # contata come se fosse del verso giusto
                continue
            irregolari.append((k, quando, verso))
        atteso = "U" if verso == "E" else "E"
    finisce_con_entrata = seq[-1][1] == "E"
    if not irregolari and not invertite and not finisce_con_entrata:
        return None

    ultima_e = next((q for q, v in reversed(seq) if v == "E"), None)
    if not invertite and irregolari == [(len(seq) - 1, seq[-1][0], "E")] and len(seq) >= 2:
        return {"tipo": "verso_errato", "entrata": ultima_e,
                "problema": f"l'uscita delle {_hm(seq[-1][0])} risulta timbrata come entrata: va corretto il verso"}
    if invertite and not irregolari and not finisce_con_entrata:
        return {"tipo": "verso_errato", "entrata": ultima_e, "problema": "; ".join(
            f"la timbratura delle {_hm(q)} risulta {_GIRO[v][0]} ma è {_GIRO[v][1]}: va corretto il verso"
            for _k, q, v in invertite)}
    if not irregolari and not invertite:
        return {"tipo": "uscita_mancante", "entrata": ultima_e,
                "problema": f"manca l'uscita dopo l'entrata delle {_hm(seq[-1][0])}"}
    parti = [f"la timbratura delle {_hm(q)} ha il verso sbagliato" for _k, q, _v in invertite]
    for k, quando, verso in irregolari:
        if k == 0 and verso == "U":
            parti.append(f"manca l'entrata prima dell'uscita delle {_hm(quando)}")
        elif verso == "E":
            parti.append(f"due entrate di fila ({_hm(seq[k - 1][0])} e {_hm(quando)}): manca un'uscita in mezzo")
        else:
            parti.append(f"due uscite di fila ({_hm(seq[k - 1][0])} e {_hm(quando)}): manca un'entrata in mezzo")
    if finisce_con_entrata and irregolari[-1][0] != len(seq) - 1:
        parti.append(f"manca l'uscita dopo l'entrata delle {_hm(seq[-1][0])}")
    return {"tipo": "sequenza_irregolare", "entrata": ultima_e, "problema": "; ".join(parti)}


def leggi_uscite_mancanti(dal: date, al: date) -> list[dict]:
    """Giornate con timbrature da sistemare, controllando **tutte** le timbrature del giorno.

    Cerca fra ``dal`` e ``al`` compresi (giorni passati: oggi non è ancora chiuso); legge
    anche il giorno prima e quello dopo per riconoscere i turni a cavallo della mezzanotte.
    ``[{solari_id, matricola, cognome, nome, codice_fiscale, giorno, entrata, tipo, problema,
    timbrature}]``; ``timbrature`` = sequenza del giorno, es. «E 07:45 · U 12:00 · E 12:50».
    """
    cfg = configurazione()
    inizio = datetime.combine(dal - timedelta(days=1), time.min)
    fine = datetime.combine(al, time.min) + timedelta(days=2)
    ana, tim = cfg.db_anagrafico, cfg.db_timbrature
    query = f"""
        SELECT a.ID, a.MATRICOLA, a.COGNOME, a.NOME, a.CODFISC, t.DATAV, t.VERSOV
        FROM [{tim}].[dbo].[TIMBRATURE] t
        INNER JOIN [{ana}].[dbo].[ANAGRAFICO_DATI] a ON a.ID = t.IDDIP
        WHERE t.DATAV >= ? AND t.DATAV < ? AND t.VERSOV IN ('E', 'U')
        ORDER BY a.ID, t.DATAV
    """
    conn = _connetti(cfg)
    try:
        cur = conn.cursor()
        cur.execute(query, (inizio, fine))
        righe = cur.fetchall()
    finally:
        conn.close()

    persone: dict[int, tuple] = {}
    giorni: dict[tuple[int, date], list[tuple[datetime, str]]] = {}
    for r in righe:
        sid = int(r[0])
        persone.setdefault(sid, r)
        voce = (r[5], _pulisci(r[6]).upper())
        lista = giorni.setdefault((sid, r[5].date()), [])
        if lista and lista[-1][0] == voce[0]:
            continue  # due timbrature nello stesso istante: una sola
        lista.append(voce)

    risultato = []
    for (sid, giorno), seq in giorni.items():
        if giorno < dal or giorno > al:
            continue
        ieri = giorni.get((sid, giorno - timedelta(days=1)))
        domani = giorni.get((sid, giorno + timedelta(days=1)))
        esito = analizza_giornata(seq, precedente=ieri[-1] if ieri else None, successiva=domani[0] if domani else None)
        if not esito:
            continue
        r = persone[sid]
        risultato.append({
            "solari_id": sid,
            "matricola": _matricola(r[1]),
            "cognome": _pulisci(r[2]),
            "nome": _pulisci(r[3]),
            "codice_fiscale": _pulisci(r[4]).upper(),
            "giorno": giorno,
            "entrata": esito["entrata"] or seq[-1][0],
            "tipo": esito["tipo"],
            "problema": esito["problema"],
            "timbrature": " · ".join(f"{v} {_hm(q)}" for q, v in seq),
        })
    risultato.sort(key=lambda x: (-x["giorno"].toordinal(), x["cognome"], x["nome"]))
    return risultato


def leggi_badge() -> dict[str, str]:
    """{codice fiscale: ultimo badge con cui la persona ha timbrato}. Serve all'import dei badge."""
    cfg = configurazione()
    query = f"""
        SELECT a.CODFISC, x.BADGE
        FROM (
            SELECT IDDIP, BADGE, ROW_NUMBER() OVER (PARTITION BY IDDIP ORDER BY DATAV DESC) AS riga
            FROM [{cfg.db_timbrature}].[dbo].[TIMBRATURE]
            WHERE BADGE IS NOT NULL
        ) x
        INNER JOIN [{cfg.db_anagrafico}].[dbo].[ANAGRAFICO_DATI] a ON a.ID = x.IDDIP
        WHERE x.riga = 1
    """
    conn = _connetti(cfg)
    try:
        cur = conn.cursor()
        cur.execute(query)
        righe = cur.fetchall()
    finally:
        conn.close()
    return {_pulisci(cf).upper(): _pulisci(b) for cf, b in righe if _pulisci(cf) and _pulisci(b)}


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
