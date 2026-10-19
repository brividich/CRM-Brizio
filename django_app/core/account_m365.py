"""Account Microsoft 365 confrontati con l'anagrafica (riesame degli accessi).

Legge gli utenti di Entra ID (``GET /users`` con ``signInActivity``) e li collega
alle persone dell'anagrafica per indirizzo email (aziendale o di notifica) o per
nome di accesso (la parte prima della @ coincide con il login AD del portale).

Esiti, dal più grave:
- ``cessato_attivo``: la persona ha una data di cessazione passata e l'account è
  ancora abilitato (ISO/IEC 27001 A.5.18, A.8.2);
- ``inattivo``: account abilitato senza accessi da oltre N giorni (o mai);
- ``non_collegato``: account abilitato con licenza che non corrisponde a nessuna
  persona (caselle condivise, account di servizio, esterni: da confermare);
- ``ok``.

Permessi applicativi: ``User.Read.All`` e, per l'ultimo accesso, ``AuditLog.Read.All``
(Entra ID P1, incluso in Business Premium). Senza ``AuditLog.Read.All`` il confronto
funziona lo stesso, senza la data dell'ultimo accesso. Sola lettura.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core import m365_graph

logger = logging.getLogger(__name__)

CACHE_KEY = "account_m365:riconciliazione"
CACHE_SECONDI = 3600
INATTIVO_GIORNI = 90
PERMESSO = "User.Read.All"
PERMESSO_ACCESSI = "AuditLog.Read.All"
_SELECT = "id,displayName,userPrincipalName,mail,accountEnabled,userType,createdDateTime,assignedLicenses"

ESITI = {
    "cessato_attivo": "Ex dipendente con account attivo",
    "inattivo": "Inattivo",
    "non_collegato": "Non collegato all'anagrafica",
    "ok": "In regola",
}
ORDINE = {"cessato_attivo": 0, "inattivo": 1, "non_collegato": 2, "ok": 3}


@dataclass
class Riga:
    entra_id: str
    nome_account: str
    upn: str
    abilitato: bool
    licenze: int
    ultimo_accesso: str  # ISO o ""
    esito: str
    persona: str = ""
    persona_id: int | None = None
    cessato_il: str = ""
    giorni_senza_accesso: int | None = None
    note: list[str] = field(default_factory=list)


def leggi_utenti() -> tuple[list[dict], bool]:
    """Utenti membri di Entra. Ritorna (utenti, con_ultimo_accesso)."""
    url = f"{m365_graph.GRAPH}/users"
    try:
        utenti = m365_graph.get_all(
            url, permesso=f"{PERMESSO} + {PERMESSO_ACCESSI}",
            params={"$select": _SELECT + ",signInActivity", "$top": "999"},
        )
        con_accessi = True
    except m365_graph.GraphError as exc:
        if exc.status != 403:
            raise
        # Senza AuditLog.Read.All Graph rifiuta signInActivity: si legge il resto.
        utenti = m365_graph.get_all(url, permesso=PERMESSO, params={"$select": _SELECT, "$top": "999"})
        con_accessi = False
    return [u for u in utenti if str(u.get("userType") or "Member").lower() == "member"], con_accessi


def _persone() -> list[dict]:
    """Persone dell'anagrafica con le chiavi di confronto (email e login, minuscole)."""
    from anagrafica.models import DipendenteAnagraficaAziendale
    from core.legacy_models import AnagraficaDipendente
    from core.naming import nome_completo

    aziendali = {
        a.legacy_anagrafica_id: a
        for a in DipendenteAnagraficaAziendale.objects.only("legacy_anagrafica_id", "email_aziendale", "data_cessazione")
    }
    out = []
    for p in AnagraficaDipendente.objects.select_related("utente").all():
        az = aziendali.get(p.id)
        chiavi = set()
        for email in (getattr(az, "email_aziendale", ""), p.email_notifica):
            email = str(email or "").strip().lower()
            if "@" in email:
                chiavi.add(email)
        for login in (p.aliasusername, p.email, getattr(p.utente, "email", "") if p.utente_id else ""):
            login = str(login or "").strip().lower()
            if login:
                chiavi.add(login if "@" in login else f"login:{login}")
        out.append({
            "id": p.id,
            "nome": nome_completo(p.nome, p.cognome) or p.aliasusername or f"anagrafica:{p.id}",
            "cessato_il": getattr(az, "data_cessazione", None),
            "chiavi": chiavi,
        })
    return out


def _indice(persone: list[dict]) -> dict[str, dict]:
    indice: dict[str, dict] = {}
    for p in persone:
        for k in p["chiavi"]:
            indice.setdefault(k, p)
    return indice


def _trova(utente: dict, indice: dict[str, dict]) -> dict | None:
    for campo in ("mail", "userPrincipalName"):
        valore = str(utente.get(campo) or "").strip().lower()
        if valore and valore in indice:
            return indice[valore]
    upn = str(utente.get("userPrincipalName") or "").lower()
    if "@" in upn:
        return indice.get(f"login:{upn.split('@', 1)[0]}")
    return None


def _ultimo_accesso(utente: dict) -> datetime | None:
    attivita = utente.get("signInActivity") or {}
    date_iso = [attivita.get(k) for k in ("lastSuccessfulSignInDateTime", "lastSignInDateTime", "lastNonInteractiveSignInDateTime")]
    valori = [d for d in (parse_datetime(str(v)) for v in date_iso if v) if d]
    return max(valori) if valori else None


def riconcilia(utenti: list[dict], persone: list[dict], *, con_accessi: bool, oggi: date | None = None,
               inattivo_giorni: int = INATTIVO_GIORNI) -> list[Riga]:
    oggi = oggi or timezone.localdate()
    indice = _indice(persone)
    righe = []
    for u in utenti:
        abilitato = bool(u.get("accountEnabled"))
        licenze = len(u.get("assignedLicenses") or [])
        persona = _trova(u, indice)
        ultimo = _ultimo_accesso(u) if con_accessi else None
        creato = parse_datetime(str(u.get("createdDateTime") or "")) if u.get("createdDateTime") else None
        riferimento = ultimo or creato
        giorni = (oggi - riferimento.date()).days if riferimento else None
        riga = Riga(
            entra_id=str(u.get("id") or ""), nome_account=str(u.get("displayName") or ""),
            upn=str(u.get("userPrincipalName") or ""), abilitato=abilitato, licenze=licenze,
            ultimo_accesso=ultimo.isoformat() if ultimo else "", esito="ok",
            persona=persona["nome"] if persona else "", persona_id=persona["id"] if persona else None,
            cessato_il=persona["cessato_il"].isoformat() if persona and persona["cessato_il"] else "",
            giorni_senza_accesso=giorni if con_accessi else None,
        )
        if abilitato and persona and persona["cessato_il"] and persona["cessato_il"] <= oggi:
            riga.esito = "cessato_attivo"
        elif abilitato and con_accessi and licenze and (giorni is None or giorni > inattivo_giorni):
            riga.esito = "inattivo"
            riga.note.append("mai entrato" if ultimo is None else f"ultimo accesso {giorni} giorni fa")
        elif abilitato and licenze and persona is None:
            riga.esito = "non_collegato"
        righe.append(riga)
    righe.sort(key=lambda r: (ORDINE[r.esito], r.persona or r.nome_account))
    return righe


def esegui(*, forza: bool = False) -> dict:
    """Confronto completo, memorizzato un'ora. Ritorna un dizionario serializzabile."""
    if not forza:
        dati = cache.get(CACHE_KEY)
        if dati:
            return dati
    utenti, con_accessi = leggi_utenti()
    righe = riconcilia(utenti, _persone(), con_accessi=con_accessi)
    conteggi = {k: 0 for k in ESITI}
    for r in righe:
        conteggi[r.esito] += 1
    dati = {
        "letto_alle": timezone.now().isoformat(),
        "con_accessi": con_accessi,
        "inattivo_giorni": INATTIVO_GIORNI,
        "conteggi": conteggi,
        "righe": [asdict(r) for r in righe],
    }
    cache.set(CACHE_KEY, dati, CACHE_SECONDI)
    return dati


def ultimo_esito() -> dict | None:
    return cache.get(CACHE_KEY)
