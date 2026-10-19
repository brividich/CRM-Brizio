"""Segnali di Microsoft Entra ID nel SOC (Microsoft Graph, licenza Entra ID P1).

Passo ``entra`` del ``security_cycle`` (15 minuti), con due controlli che si
accendono separatamente da ``/soc/impostazioni/``:

1. **Account di ex dipendenti ancora attivi** (al massimo ogni 6 ore): il
   confronto account ↔ anagrafica di ``core.account_m365``; per ogni account
   abilitato di una persona cessata nasce un evento ``m365_account_cessato`` e un
   alert del SOC, che si chiude da solo quando l'account risulta disattivato.
2. **Modifiche amministrative in Entra** (``auditLogs/directoryAudits``, dal
   giro precedente): solo le attività di ``ATTIVITA_SORVEGLIATE`` (ruoli di
   amministratore, consensi e credenziali delle app, accesso condizionale,
   metodi MFA, federazione dei domini) diventano un evento ``entra_audit`` e un
   alert; le altre righe dell'audit non vengono salvate.
3. **Accessi sospetti** (``auditLogs/signIns``, dal giro precedente): tentativi
   falliti a raffica sullo stesso account, accessi riusciti da Paesi non ammessi,
   accessi riusciti con protocolli vecchi (IMAP, POP, SMTP autenticato, ActiveSync,
   altri client). Nasce un evento ``entra_accesso`` per anomalia, al massimo uno al
   giorno per account e motivo; i singoli accessi non vengono salvati.

Dati minimi: chi ha fatto la modifica, su cosa, quando, esito. Permessi
applicativi: ``User.Read.All`` e ``AuditLog.Read.All`` (consenso amministratore).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.models import SecurityCenterSetting, SecurityEventRecord, SecuritySource, Severity, SourceType
from security.services import soc_settings
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

SOURCE_NAME = "Microsoft Entra ID (Graph)"
EVENT_ACCOUNT = "m365_account_cessato"
EVENT_AUDIT = "entra_audit"
EVENT_ACCESSO = "entra_accesso"
AUDIT_URL = "https://graph.microsoft.com/v1.0/auditLogs/directoryAudits"
SIGNINS_URL = "https://graph.microsoft.com/v1.0/auditLogs/signIns"
CURSOR_ACCESSI_KEY = "entra.cursore_accessi"
# clientAppUsed dei protocolli senza autenticazione moderna (niente MFA).
PROTOCOLLI_VECCHI = {"imap4", "pop3", "authenticated smtp", "exchange activesync", "other clients",
                     "autodiscover", "exchange online powershell", "offline address book",
                     "outlook anywhere (rpc over http)", "exchange web services"}
ACCOUNT_OGNI_ORE = 6

CURSOR_KEY = "entra.cursore_audit"
ACCOUNT_LAST_KEY = "entra.ultimo_controllo_account"
LAST_RUN_KEY = "entra.ultimo_giro"

# (frammento del nome dell'attività in minuscolo, etichetta, severità)
ATTIVITA_SORVEGLIATE: tuple[tuple[str, str, str], ...] = (
    ("set domain authentication", "Autenticazione di un dominio cambiata", Severity.CRITICAL),
    ("set federation settings on domain", "Federazione di un dominio cambiata", Severity.CRITICAL),
    ("add member to role", "Ruolo di amministratore assegnato", Severity.HIGH),
    ("add eligible member to role", "Ruolo di amministratore assegnabile", Severity.HIGH),
    ("conditional access policy", "Criterio di accesso condizionale modificato", Severity.HIGH),
    ("add service principal credentials", "Credenziali aggiunte a un'app", Severity.HIGH),
    ("certificates and secrets management", "Segreti/certificati di un'app modificati", Severity.HIGH),
    ("disable strong authentication", "MFA disattivata per un utente", Severity.HIGH),
    ("consent to application", "Consenso a un'app", Severity.MEDIUM),
    ("add app role assignment to service principal", "Permesso applicativo concesso a un'app", Severity.MEDIUM),
    ("add delegated permission grant", "Permesso delegato concesso a un'app", Severity.MEDIUM),
    ("add owner to application", "Proprietario aggiunto a un'app", Severity.MEDIUM),
    ("security info", "Metodi di autenticazione (MFA) modificati", Severity.MEDIUM),
)


def entra_source():
    source, _ = SecuritySource.objects.get_or_create(
        name=SOURCE_NAME, defaults={"source_type": SourceType.API, "vendor": "microsoft"},
    )
    return source


def _save_state(key: str, value) -> None:
    # Stato tecnico del giro, non una scelta di configurazione: niente audit delle impostazioni.
    SecurityCenterSetting.objects.update_or_create(
        key=key,
        defaults={"value": value, "value_type": "json" if isinstance(value, (dict, list)) else "string",
                  "category": "entra"},
    )


def _state(key: str, default=None):
    from security.services.configuration import get_setting

    return get_setting(key, default)


def classifica(attivita: str) -> tuple[str, str] | None:
    nome = (attivita or "").strip().lower()
    for frammento, etichetta, severita in ATTIVITA_SORVEGLIATE:
        if frammento in nome:
            return etichetta, severita
    return None


# ── 1. Account di ex dipendenti ──────────────────────────────────────────────


def controlla_account(now: datetime) -> dict:
    from core import account_m365

    ultimo = parse_datetime(str(_state(ACCOUNT_LAST_KEY, "") or ""))
    if ultimo and now - ultimo < timedelta(hours=ACCOUNT_OGNI_ORE):
        return {"saltato": True}
    dati = account_m365.esegui(forza=True)
    source = entra_source()
    attivi = {}
    for r in dati["righe"]:
        if r["esito"] != "cessato_attivo" or not r["entra_id"]:
            continue
        dedup = make_hash(source.pk, EVENT_ACCOUNT, r["entra_id"])
        attivi[dedup] = r
    from security.services.rule_engine import _active_alert

    eventi = 0
    for dedup, r in attivi.items():
        if _active_alert(source, dedup):
            continue
        SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_ACCOUNT, severity=Severity.HIGH, occurred_at=now,
            fingerprint=dedup, dedup_hash=dedup,
            payload={"persona": r["persona"], "upn": r["upn"], "account": r["nome_account"],
                     "cessato_il": r["cessato_il"], "ultimo_accesso": r["ultimo_accesso"], "alert_candidate": True},
        )
        eventi += 1
    chiusi = _chiudi_account_disattivati(source, set(attivi))
    _save_state(ACCOUNT_LAST_KEY, now.isoformat())
    return {"cessati_attivi": len(attivi), "eventi": eventi, "chiusi": chiusi}


def _chiudi_account_disattivati(source, ancora_attivi: set[str]) -> int:
    from security.models import SecurityAlert
    from security.services.auto_resolution import resolve_alert
    from security.services.rule_engine import ACTIVE_ALERT_STATUSES

    chiusi = 0
    aperti = SecurityAlert.objects.filter(source=source, status__in=ACTIVE_ALERT_STATUSES, event__event_type=EVENT_ACCOUNT)
    for alert in aperti:
        if alert.dedup_hash not in ancora_attivi:
            resolve_alert(alert, "Account disattivato in Microsoft 365", rule_code=EVENT_ACCOUNT)
            chiusi += 1
    return chiusi


# ── 2. Modifiche amministrative ──────────────────────────────────────────────


def _cursor(now: datetime) -> datetime:
    parsed = parse_datetime(str(_state(CURSOR_KEY, "") or ""))
    if parsed is None:
        return now - timedelta(days=soc_settings.value("entra.primo_giro_giorni"))
    return parsed - timedelta(minutes=1)  # sovrapposizione: i doppioni li ferma il dedup


def _nomi_target(riga: dict) -> list[str]:
    out = []
    for t in riga.get("targetResources") or []:
        if isinstance(t, dict):
            nome = str(t.get("userPrincipalName") or t.get("displayName") or "").strip()
            if nome:
                out.append(nome[:120])
    return out[:5]


def _autore(riga: dict) -> str:
    chi = riga.get("initiatedBy") or {}
    utente = chi.get("user") or {}
    app = chi.get("app") or {}
    return str(utente.get("userPrincipalName") or utente.get("displayName") or app.get("displayName") or "sconosciuto")[:200]


def normalizza_audit(riga: dict) -> dict | None:
    attivita = str(riga.get("activityDisplayName") or "")
    trovata = classifica(attivita)
    if trovata is None:
        return None
    etichetta, severita = trovata
    return {
        "audit_id": str(riga.get("id") or ""),
        "attivita": attivita[:200],
        "etichetta": etichetta,
        "severita": severita,
        "categoria": str(riga.get("category") or "")[:80],
        "esito": str(riga.get("result") or "")[:40],
        "autore": _autore(riga),
        "target": _nomi_target(riga),
        "quando": str(riga.get("activityDateTime") or ""),
        "alert_candidate": True,
    }


def leggi_audit(now: datetime) -> dict:
    from core import m365_graph

    since = _cursor(now).astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    righe = m365_graph.get_all(
        AUDIT_URL, permesso="AuditLog.Read.All",
        params={"$filter": f"activityDateTime ge {since}", "$top": "500"}, max_pages=20,
    )
    source = entra_source()
    eventi = 0
    for riga in righe:
        payload = normalizza_audit(riga)
        if not payload or not payload["audit_id"]:
            continue
        dedup = make_hash(source.pk, EVENT_AUDIT, payload["audit_id"])
        if SecurityEventRecord.objects.filter(source=source, event_type=EVENT_AUDIT, dedup_hash=dedup).exists():
            continue
        quando = parse_datetime(payload["quando"]) or now
        if timezone.is_naive(quando):
            quando = timezone.make_aware(quando, dt_timezone.utc)
        SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_AUDIT, severity=payload["severita"], occurred_at=quando,
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        )
        eventi += 1
    _save_state(CURSOR_KEY, now.isoformat())
    return {"lette": len(righe), "eventi": eventi}


# ── 3. Accessi sospetti ──────────────────────────────────────────────────────


def _paesi_ammessi() -> set[str]:
    grezzo = str(soc_settings.value("entra.paesi_ammessi") or "IT")
    return {p.strip().upper() for p in grezzo.replace(";", ",").split(",") if p.strip()}


def anomalie_accessi(righe: list[dict], *, soglia_falliti: int, paesi: set[str]) -> list[dict]:
    """Dagli accessi grezzi le anomalie: ``[{motivo, upn, severita, dettaglio, quando, app, ip}]``."""
    falliti: dict[str, list[dict]] = {}
    out: list[dict] = []
    visti: set[tuple] = set()
    for r in righe:
        upn = str(r.get("userPrincipalName") or "").lower()
        if not upn:
            continue
        stato = r.get("status") or {}
        riuscito = int(stato.get("errorCode") or 0) == 0
        luogo = r.get("location") or {}
        paese = str(luogo.get("countryOrRegion") or "").upper()
        app = str(r.get("clientAppUsed") or "")
        quando = str(r.get("createdDateTime") or "")
        if not riuscito:
            falliti.setdefault(upn, []).append(r)
            continue
        if paese and paesi and paese not in paesi and (upn, "estero", paese) not in visti:
            visti.add((upn, "estero", paese))
            out.append({"motivo": "estero", "upn": upn, "severita": Severity.HIGH, "quando": quando,
                        "dettaglio": paese + (f" ({luogo.get('city')})" if luogo.get("city") else ""),
                        "app": str(r.get("appDisplayName") or "")[:80], "ip": str(r.get("ipAddress") or "")[:60]})
        if app.lower() in PROTOCOLLI_VECCHI and (upn, "protocollo", app.lower()) not in visti:
            visti.add((upn, "protocollo", app.lower()))
            out.append({"motivo": "protocollo", "upn": upn, "severita": Severity.MEDIUM, "quando": quando,
                        "dettaglio": app[:60], "app": str(r.get("appDisplayName") or "")[:80],
                        "ip": str(r.get("ipAddress") or "")[:60]})
    for upn, lista in falliti.items():
        if len(lista) >= soglia_falliti:
            ips = sorted({str(x.get("ipAddress") or "") for x in lista if x.get("ipAddress")})
            out.append({"motivo": "falliti", "upn": upn, "severita": Severity.MEDIUM,
                        "quando": max(str(x.get("createdDateTime") or "") for x in lista),
                        "dettaglio": f"{len(lista)} tentativi falliti", "app": "", "ip": ", ".join(ips[:5])})
    return out


MOTIVI = {
    "falliti": "Tentativi di accesso falliti a raffica",
    "estero": "Accesso a Microsoft 365 da un Paese non ammesso",
    "protocollo": "Accesso con un protocollo vecchio (senza MFA)",
}


def leggi_accessi(now: datetime) -> dict:
    from core import m365_graph

    parsed = parse_datetime(str(_state(CURSOR_ACCESSI_KEY, "") or ""))
    inizio = parsed - timedelta(minutes=1) if parsed else now - timedelta(hours=1)
    since = inizio.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    righe = m365_graph.get_all(
        SIGNINS_URL, permesso="AuditLog.Read.All",
        params={"$filter": f"createdDateTime ge {since}", "$top": "1000"}, max_pages=20,
    )
    anomalie = anomalie_accessi(righe, soglia_falliti=int(soc_settings.value("entra.falliti_soglia")),
                                paesi=_paesi_ammessi())
    source = entra_source()
    giorno = timezone.localdate(now).isoformat()
    eventi = 0
    for a in anomalie:
        # Uno al giorno per account, motivo e dettaglio (Paese o protocollo).
        chiave = a["dettaglio"] if a["motivo"] != "falliti" else ""
        dedup = make_hash(source.pk, EVENT_ACCESSO, a["upn"], a["motivo"], chiave, giorno)
        if SecurityEventRecord.objects.filter(source=source, event_type=EVENT_ACCESSO, dedup_hash=dedup).exists():
            continue
        quando = parse_datetime(a["quando"]) or now
        if timezone.is_naive(quando):
            quando = timezone.make_aware(quando, dt_timezone.utc)
        SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_ACCESSO, severity=a["severita"], occurred_at=quando,
            fingerprint=dedup, dedup_hash=dedup,
            payload={**a, "etichetta": MOTIVI[a["motivo"]], "alert_candidate": True},
        )
        eventi += 1
    _save_state(CURSOR_ACCESSI_KEY, now.isoformat())
    return {"letti": len(righe), "anomalie": len(anomalie), "eventi": eventi}


# ── Giro ─────────────────────────────────────────────────────────────────────


def run(now: datetime | None = None) -> dict:
    """Passo del ciclo SOC. Non solleva: l'esito finisce in ``entra.ultimo_giro``."""
    account_on = soc_settings.value("entra.account_cessati.attivo")
    audit_on = soc_settings.value("entra.audit.attivo")
    accessi_on = soc_settings.value("entra.accessi.attivo")
    if not (account_on or audit_on or accessi_on):
        return {"attivo": False}
    now = now or timezone.now()
    esito: dict = {"attivo": True, "at": now.isoformat()}
    nuovi = False
    for nome, acceso, passo in (("account", account_on, controlla_account), ("audit", audit_on, leggi_audit),
                                ("accessi", accessi_on, leggi_accessi)):
        if not acceso:
            continue
        try:
            esito[nome] = passo(now)
            nuovi = nuovi or bool(esito[nome].get("eventi"))
        except Exception as exc:  # noqa: BLE001 - il ciclo SOC prosegue con gli altri passi
            logger.warning("Entra: %s non riuscito: %s", nome, exc)
            esito[nome] = {"errore": str(exc)[:300]}
    if nuovi:
        from security.services.rule_engine import evaluate_security_rules

        evaluate_security_rules()
    _save_state(LAST_RUN_KEY, esito)
    return esito


def last_run() -> dict:
    value = _state(LAST_RUN_KEY, {})
    return value if isinstance(value, dict) else {}
