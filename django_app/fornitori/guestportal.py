"""Collegamento con il GuestPortal (portale accessi visitatori, PHP + MySQL su IIS).

Il GuestPortal resta un'applicazione separata: l'HUB

- legge in SOLA LETTURA le visite dal suo database MySQL (``GuestManagement``)
  con un utente dedicato che ha solo SELECT sulle tabelle necessarie;
- non copia i dati delle visite nelle proprie tabelle: il GuestPortal cancella le
  visite chiuse con la sua pulizia GDPR e una copia nell'HUB le farebbe
  sopravvivere;
- apre il pannello admin del GuestPortal con un token firmato a uso singolo
  (``sso.php``), così chi è già entrato nell'HUB non ridigita la password.
  Chi può entrare nel pannello lo decide sempre il GuestPortal (tabella
  ``AdminUsers``).

Configurazione (``.env``):

- ``GUESTPORTAL_ADMIN_URL``: pagina di login del pannello (fallback senza SSO);
- ``GUESTPORTAL_SSO_URL``: indirizzo di ``public/admin/sso.php``;
- ``GUESTPORTAL_SSO_SECRET``: segreto condiviso con ``config/sso.php`` del
  GuestPortal (almeno 32 caratteri);
- ``GUESTPORTAL_DB_HOST`` / ``_PORT`` / ``_NAME`` / ``_USER`` / ``_PASSWORD``:
  connessione MySQL in sola lettura.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.conf import settings

logger = logging.getLogger(__name__)

SSO_TTL_SECONDI = 60
SSO_SEGRETO_MIN = 32
DB_TIMEOUT_SECONDI = 5
STORICO_MAX_RIGHE = 500

STATI = {
    "CHECKEDIN": "Presente",
    "CHECKEDOUT": "Uscito",
    "PREREGISTERED": "Preregistrato",
    "NOSHOW": "Non presentato",
}
TIPI = {
    "NORMAL": "Visitatore",
    "PREREG": "Preregistrato",
    "SUPPLIER": "Fornitore / consulente",
}


class GuestPortalNonConfigurato(Exception):
    """Manca la configurazione nel .env."""


class GuestPortalNonRaggiungibile(Exception):
    """Il database del GuestPortal non risponde o rifiuta la query."""


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

def _cfg(nome: str, default: str = "") -> str:
    return str(getattr(settings, nome, "") or default).strip()


def admin_url() -> str:
    return _cfg("GUESTPORTAL_ADMIN_URL")


def sso_url() -> str:
    return _cfg("GUESTPORTAL_SSO_URL")


def sso_configurato() -> bool:
    return bool(_cfg("GUESTPORTAL_SSO_URL")) and len(_cfg("GUESTPORTAL_SSO_SECRET")) >= SSO_SEGRETO_MIN


def db_configurato() -> bool:
    return all(_cfg(n) for n in ("GUESTPORTAL_DB_HOST", "GUESTPORTAL_DB_NAME", "GUESTPORTAL_DB_USER"))


# ---------------------------------------------------------------------------
# SSO: token firmato a uso singolo
# ---------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def username_dominio(username: str) -> str:
    """Riduce ``DOMINIO\\nome`` o ``nome@dominio`` al solo nome di dominio, minuscolo,
    come lo salva il GuestPortal in ``AdminUsers.Username``."""
    valore = (username or "").strip()
    if "\\" in valore:
        valore = valore.rsplit("\\", 1)[1]
    if "@" in valore:
        valore = valore.split("@", 1)[0]
    return valore.lower()


def firma_token(username: str, *, adesso: int | None = None, nonce: str | None = None) -> str:
    """Token ``payload.firma`` (base64url, HMAC-SHA256) letto da ``sso.php``.

    Il payload contiene solo il nome utente, l'emissione, la scadenza (60 s) e un
    codice casuale che il GuestPortal accetta una volta sola.
    """
    segreto = _cfg("GUESTPORTAL_SSO_SECRET")
    if len(segreto) < SSO_SEGRETO_MIN:
        raise GuestPortalNonConfigurato("GUESTPORTAL_SSO_SECRET mancante o troppo corto")
    utente = username_dominio(username)
    if not utente:
        raise ValueError("username vuoto")
    iat = int(adesso if adesso is not None else time.time())
    payload = {
        "u": utente,
        "iat": iat,
        "exp": iat + SSO_TTL_SECONDI,
        "n": nonce or secrets.token_hex(16),
        "iss": "novicrom-hub",
    }
    corpo = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    firma = _b64(hmac.new(segreto.encode("utf-8"), corpo.encode("ascii"), hashlib.sha256).digest())
    return f"{corpo}.{firma}"


# ---------------------------------------------------------------------------
# Lettura visite (MySQL, sola lettura)
# ---------------------------------------------------------------------------

@dataclass
class Accesso:
    visita_id: int
    stato: str
    tipo: str
    nome: str
    azienda: str
    referente: str
    motivo: str
    badge: str
    ingresso: datetime | None
    uscita: datetime | None
    fornitore_id: int | None = None  # scheda fornitore HUB con la stessa ragione sociale

    @property
    def stato_label(self) -> str:
        return STATI.get(self.stato, self.stato or "—")

    @property
    def tipo_label(self) -> str:
        return TIPI.get(self.tipo, self.tipo or "—")

    @property
    def presente(self) -> bool:
        return self.stato == "CHECKEDIN"

    @property
    def durata_minuti(self) -> int | None:
        if not self.ingresso:
            return None
        fine = self.uscita or datetime.now()
        return max(0, int((fine - self.ingresso).total_seconds() // 60))

    @property
    def durata_label(self) -> str:
        minuti = self.durata_minuti
        if minuti is None:
            return "—"
        if minuti < 60:
            return f"{minuti} min"
        return f"{minuti // 60} h {minuti % 60:02d} min"


def _connessione():
    if not db_configurato():
        raise GuestPortalNonConfigurato("connessione al database del GuestPortal non configurata")
    try:
        import pymysql
        import pymysql.cursors
    except ImportError as exc:  # pragma: no cover - dipendenza installata da requirements
        raise GuestPortalNonConfigurato("libreria PyMySQL non installata") from exc
    try:
        conn = pymysql.connect(
            host=_cfg("GUESTPORTAL_DB_HOST"),
            port=int(_cfg("GUESTPORTAL_DB_PORT", "3306") or 3306),
            user=_cfg("GUESTPORTAL_DB_USER"),
            password=_cfg("GUESTPORTAL_DB_PASSWORD"),
            database=_cfg("GUESTPORTAL_DB_NAME"),
            charset="utf8mb4",
            connect_timeout=DB_TIMEOUT_SECONDI,
            read_timeout=DB_TIMEOUT_SECONDI * 2,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    except Exception as exc:
        logger.warning("GuestPortal: connessione MySQL fallita (%s)", type(exc).__name__)
        raise GuestPortalNonRaggiungibile(str(exc)) from exc
    try:
        with conn.cursor() as cur:
            # Difesa in profondità: anche se l'utente avesse più permessi del
            # previsto, la sessione HUB non può scrivere.
            cur.execute("SET SESSION TRANSACTION READ ONLY")
    except Exception:
        logger.debug("GuestPortal: SET SESSION TRANSACTION READ ONLY non applicato", exc_info=True)
    return conn


_SELECT = """
    SELECT v.VisitID, v.Status, v.VisitType, v.BadgeNumber, v.HostEmployee, v.Purpose,
           v.CheckInTime, v.CheckOutTime,
           g.FirstName, g.LastName, g.Company, g.IsAnonymized,
           s.CompanyName AS SupplierName
    FROM Visits v
    JOIN Guests g ON g.GuestID = v.GuestID
    LEFT JOIN Suppliers s ON s.SupplierID = v.SupplierID
"""


def _riga_in_accesso(r: dict) -> Accesso:
    anonimo = bool(r.get("IsAnonymized"))
    nome = "Ospite anonimizzato" if anonimo else " ".join(
        p for p in ((r.get("FirstName") or "").strip(), (r.get("LastName") or "").strip()) if p
    )
    azienda = (r.get("SupplierName") or r.get("Company") or "").strip()
    return Accesso(
        visita_id=int(r.get("VisitID") or 0),
        stato=(r.get("Status") or "").strip(),
        tipo=(r.get("VisitType") or "NORMAL").strip(),
        nome=nome or "—",
        azienda="" if anonimo else azienda,
        referente=(r.get("HostEmployee") or "").strip(),
        motivo=(r.get("Purpose") or "").strip(),
        badge=(r.get("BadgeNumber") or "").strip(),
        ingresso=r.get("CheckInTime"),
        uscita=r.get("CheckOutTime"),
    )


def _esegui(sql: str, params: list) -> list[dict]:
    conn = _connessione()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    except GuestPortalNonConfigurato:
        raise
    except Exception as exc:
        logger.warning("GuestPortal: query fallita (%s)", type(exc).__name__)
        raise GuestPortalNonRaggiungibile(str(exc)) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def presenti_ora() -> list[Accesso]:
    """Esterni con check-in aperto, dal più vecchio (chi è dentro da più tempo)."""
    righe = _esegui(_SELECT + " WHERE v.Status = 'CHECKEDIN' ORDER BY v.CheckInTime ASC", [])
    return [_riga_in_accesso(r) for r in righe]


def storico(
    *,
    dal: date,
    al: date,
    testo: str = "",
    tipo: str = "",
    limite: int = STORICO_MAX_RIGHE,
) -> tuple[list[Accesso], bool]:
    """Visite con ingresso tra ``dal`` e ``al`` (compresi), dalla più recente.

    Ritorna ``(righe, troncato)``: ``troncato`` è vero se le visite trovate sono
    più di ``limite`` (la pagina lo dice, niente tagli muti).
    """
    where = ["v.CheckInTime >= %s", "v.CheckInTime < %s"]
    params: list = [datetime.combine(dal, datetime.min.time()),
                    datetime.combine(al + timedelta(days=1), datetime.min.time())]
    if tipo in TIPI:
        where.append("v.VisitType = %s")
        params.append(tipo)
    testo = (testo or "").strip()
    if testo:
        like = f"%{testo}%"
        where.append(
            "(g.IsAnonymized = 0 AND (g.FirstName LIKE %s OR g.LastName LIKE %s OR g.Company LIKE %s"
            " OR s.CompanyName LIKE %s) OR v.HostEmployee LIKE %s OR v.Purpose LIKE %s)"
        )
        params.extend([like] * 6)
    sql = _SELECT + " WHERE " + " AND ".join(where) + " ORDER BY v.CheckInTime DESC LIMIT %s"
    params.append(int(limite) + 1)
    righe = [_riga_in_accesso(r) for r in _esegui(sql, params)]
    troncato = len(righe) > limite
    return righe[:limite], troncato
