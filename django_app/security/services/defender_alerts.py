"""Alert di Microsoft Defender nel SOC (Microsoft Graph, ``security/alerts_v2``).

Ogni giro del ``security_cycle`` (15 minuti), se acceso da ``/soc/impostazioni/``:

1. legge da Graph gli alert aggiornati dopo l'ultimo giro (al primo giro: gli
   ultimi N giorni), seguendo la paginazione;
2. per ogni alert nuovo o cambiato (stato o severità) crea un evento
   ``defender_alert`` sulla sorgente «Microsoft Defender (Graph Security)», con
   dedup sull'id dell'alert di Defender: lo stesso alert non duplica mai l'alert
   del SOC, lo aggiorna;
3. il motore regole (``rule_engine._evaluate_defender_alert``) apre l'alert del
   SOC sopra la severità minima scelta e lo chiude quando Defender lo dà risolto.

Dati minimi: del contenuto di Defender si tengono titolo, severità, stato,
categoria, prodotto che l'ha rilevato, tecniche MITRE, nomi dei dispositivi
coinvolti e il link al portale Defender. Degli utenti coinvolti solo il
numero: chi indaga apre l'alert in Defender.

Prerequisito: permesso applicativo Graph ``SecurityAlert.Read.All`` con consenso
amministratore sull'app del portale (``GRAPH_TENANT_ID`` / ``GRAPH_CLIENT_ID`` /
``GRAPH_CLIENT_SECRET``). Senza, il giro registra l'errore e non fa altro.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.models import SecurityAsset, SecurityCenterSetting, SecurityEventRecord, SecuritySource, Severity, SourceType
from security.services import soc_settings
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

EVENT_TYPE = "defender_alert"
EVENT_INCIDENT = "defender_incident"
INCIDENTS_URL = "https://graph.microsoft.com/v1.0/security/incidents"
CURSOR_INCIDENTS_KEY = "defender.cursore_incidenti"
SOURCE_NAME = "Microsoft Defender (Graph Security)"
GRAPH_ALERTS_URL = "https://graph.microsoft.com/v1.0/security/alerts_v2"
PAGE_SIZE = 100
MAX_PAGES = 20
TIMEOUT_SECONDS = 30

CURSOR_KEY = "defender.cursore"
LAST_RUN_KEY = "defender.ultimo_giro"

# Severità Defender → SOC. «informational» resta informativo (evento, mai alert).
SEVERITY_MAP = {
    "informational": Severity.INFO,
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "unknown": Severity.MEDIUM,
}
SEVERITY_RANK = {Severity.INFO: 0, Severity.LOW: 1, Severity.MEDIUM: 2, Severity.WARNING: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}
RESOLVED_STATUSES = {"resolved"}


class DefenderError(RuntimeError):
    pass


def defender_source():
    source, _ = SecuritySource.objects.get_or_create(
        name=SOURCE_NAME, defaults={"source_type": SourceType.API, "vendor": "microsoft"},
    )
    return source


def _graph_credentials() -> tuple[str, str, str]:
    from security.services.mailbox_providers import _required_graph_setting

    return (
        _required_graph_setting("GRAPH_TENANT_ID"),
        _required_graph_setting("GRAPH_CLIENT_ID"),
        _required_graph_setting("GRAPH_CLIENT_SECRET"),
    )


def _token() -> str:
    from core.graph_utils import acquire_graph_token

    return acquire_graph_token(*_graph_credentials())


def _get(url: str, token: str, params: dict | None = None) -> dict:
    import requests

    resp = requests.get(
        url, params=params, timeout=TIMEOUT_SECONDS,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if resp.status_code in (401, 403):
        try:
            from core.graph_utils import invalidate_graph_token_cache

            invalidate_graph_token_cache(*_graph_credentials())
        except Exception:  # noqa: BLE001 - l'errore vero è quello sotto
            pass
        raise DefenderError(
            f"Graph ha risposto {resp.status_code}: manca il permesso SecurityAlert.Read.All "
            "(con consenso amministratore) sull'app del portale, oppure le credenziali non sono valide."
        )
    if resp.status_code >= 400:
        raise DefenderError(f"Graph ha risposto {resp.status_code} sugli alert di Defender.")
    return resp.json()


def fetch_alerts(since: datetime, token: str | None = None) -> list[dict]:
    """Alert aggiornati dopo ``since`` (UTC), tutte le pagine fino a MAX_PAGES."""
    token = token or _token()
    if timezone.is_aware(since):
        since = since.astimezone(dt_timezone.utc)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"$filter": f"lastUpdateDateTime ge {since_iso}", "$top": str(PAGE_SIZE)}
    url = GRAPH_ALERTS_URL
    out: list[dict] = []
    for _ in range(MAX_PAGES):
        data = _get(url, token, params)
        out.extend(item for item in data.get("value") or [] if isinstance(item, dict))
        url = data.get("@odata.nextLink") or ""
        params = None  # il nextLink contiene già filtro e paginazione
        if not url:
            break
        if not url.startswith("https://graph.microsoft.com/"):
            raise DefenderError("Link di paginazione inatteso da Graph: interrotto.")
    return out


def _devices(alert: dict) -> list[str]:
    names = []
    for ev in alert.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("@odata.type", "")).endswith("deviceEvidence"):
            name = str(ev.get("deviceDnsName") or ev.get("hostName") or "").strip()
            if name and name.lower() not in {n.lower() for n in names}:
                names.append(name)
    return names[:50]


def _users_count(alert: dict) -> int:
    return sum(
        1 for ev in alert.get("evidence") or []
        if isinstance(ev, dict) and str(ev.get("@odata.type", "")).endswith("userEvidence")
    )


def normalize(alert: dict) -> dict:
    """Payload minimo dell'evento: niente nomi di utenti, niente descrizioni lunghe."""
    severity_raw = str(alert.get("severity") or "unknown").strip().lower()
    status_raw = str(alert.get("status") or "").strip().lower()
    web_url = str(alert.get("alertWebUrl") or "")
    if web_url and not web_url.startswith("https://"):
        web_url = ""
    return {
        "defender_id": str(alert.get("id") or ""),
        "title": str(alert.get("title") or "Alert di Microsoft Defender")[:255],
        "severity_defender": severity_raw,
        "status_defender": status_raw,
        "classification": str(alert.get("classification") or ""),
        "category": str(alert.get("category") or ""),
        "service_source": str(alert.get("serviceSource") or ""),
        "detection_source": str(alert.get("detectionSource") or ""),
        "incident_id": str(alert.get("incidentId") or ""),
        "created": str(alert.get("createdDateTime") or ""),
        "last_update": str(alert.get("lastUpdateDateTime") or ""),
        "first_activity": str(alert.get("firstActivityDateTime") or ""),
        "mitre": [str(t) for t in (alert.get("mitreTechniques") or [])][:20],
        "devices": _devices(alert),
        "users_count": _users_count(alert),
        "web_url": web_url[:500],
        "alert_candidate": True,
    }


def _last_payload(source, dedup):
    return (
        SecurityEventRecord.objects.filter(source=source, event_type=EVENT_TYPE, dedup_hash=dedup)
        .order_by("-occurred_at", "-id").values_list("payload", flat=True).first()
    ) or {}


def _changed(prev: dict, cur: dict) -> bool:
    if not prev:
        return True
    return (prev.get("status_defender"), prev.get("severity_defender")) != (cur.get("status_defender"), cur.get("severity_defender"))


def _asset_for(source, devices: list[str]):
    if not devices:
        return None
    asset, _ = SecurityAsset.objects.get_or_create(source=source, hostname=devices[0][:255], defaults={"asset_type": "endpoint"})
    return asset


def record_events(alerts: list[dict]) -> list[SecurityEventRecord]:
    """Un evento per alert nuovo o cambiato. Ritorna gli eventi creati."""
    source = defender_source()
    created = []
    for raw in alerts:
        payload = normalize(raw)
        if not payload["defender_id"]:
            continue
        dedup = make_hash(source.pk, EVENT_TYPE, payload["defender_id"])
        if not _changed(_last_payload(source, dedup), payload):
            continue
        occurred = parse_datetime(payload["last_update"] or "") or timezone.now()
        if timezone.is_naive(occurred):
            occurred = timezone.make_aware(occurred, dt_timezone.utc)
        created.append(SecurityEventRecord.objects.create(
            source=source, asset=_asset_for(source, payload["devices"]), event_type=EVENT_TYPE,
            severity=SEVERITY_MAP.get(payload["severity_defender"], Severity.MEDIUM), occurred_at=occurred,
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        ))
    return created


def normalize_incident(inc: dict) -> dict:
    web_url = str(inc.get("incidentWebUrl") or "")
    return {
        "incident_id": str(inc.get("id") or ""),
        "title": str(inc.get("displayName") or "Incidente di Microsoft Defender")[:255],
        "severity_defender": str(inc.get("severity") or "unknown").strip().lower(),
        "status_defender": str(inc.get("status") or "").strip().lower(),
        "classification": str(inc.get("classification") or ""),
        "determination": str(inc.get("determination") or ""),
        "last_update": str(inc.get("lastUpdateDateTime") or ""),
        "web_url": web_url[:500] if web_url.startswith("https://") else "",
        "alert_candidate": True,
    }


def record_incidents(incidents: list[dict]) -> list[SecurityEventRecord]:
    """Un evento per incidente nuovo o cambiato (stato o severità), dedup sull'id dell'incidente."""
    source = defender_source()
    created = []
    for raw in incidents:
        payload = normalize_incident(raw)
        if not payload["incident_id"]:
            continue
        dedup = make_hash(source.pk, EVENT_INCIDENT, payload["incident_id"])
        prev = (SecurityEventRecord.objects.filter(source=source, event_type=EVENT_INCIDENT, dedup_hash=dedup)
                .order_by("-occurred_at", "-id").values_list("payload", flat=True).first()) or {}
        if not _changed(prev, payload):
            continue
        occurred = parse_datetime(payload["last_update"] or "") or timezone.now()
        if timezone.is_naive(occurred):
            occurred = timezone.make_aware(occurred, dt_timezone.utc)
        created.append(SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_INCIDENT, occurred_at=occurred,
            severity=SEVERITY_MAP.get(payload["severity_defender"], Severity.MEDIUM),
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        ))
    return created


def fetch_incidents(since: datetime) -> list[dict]:
    from core import m365_graph

    since_iso = since.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return m365_graph.get_all(INCIDENTS_URL, permesso="SecurityIncident.Read.All",
                              params={"$filter": f"lastUpdateDateTime ge {since_iso}", "$top": "50"}, max_pages=20)


def _incidents_cursor(now: datetime) -> datetime:
    from security.services.configuration import get_setting

    parsed = parse_datetime(str(get_setting(CURSOR_INCIDENTS_KEY, "") or ""))
    if parsed is None:
        return now - timedelta(days=soc_settings.value("defender.primo_giro_giorni"))
    return parsed - timedelta(minutes=1)


def _save_state(key: str, value) -> None:
    # Scrittura diretta, non set_setting: stato tecnico del giro (ogni 15 minuti), non
    # una scelta di configurazione da tracciare nell'audit delle impostazioni.
    SecurityCenterSetting.objects.update_or_create(
        key=key,
        defaults={"value": value, "value_type": "json" if isinstance(value, (dict, list)) else "string",
                  "category": "defender"},
    )


def _cursor(now: datetime) -> datetime:
    from security.services.configuration import get_setting

    raw = get_setting(CURSOR_KEY, "")
    parsed = parse_datetime(str(raw or "")) if raw else None
    if parsed is None:
        return now - timedelta(days=soc_settings.value("defender.primo_giro_giorni"))
    # Un minuto di sovrapposizione: gli alert aggiornati al confine non si perdono
    # (i doppioni li ferma il confronto con l'ultimo stato).
    return parsed - timedelta(minutes=1)


def run(now: datetime | None = None) -> dict:
    """Giro completo. Non solleva: l'esito finisce in ``defender.ultimo_giro``."""
    if not soc_settings.value("defender.alert.attivo"):
        return {"attivo": False}
    now = now or timezone.now()
    esito = {"attivo": True, "at": now.isoformat()}
    try:
        alerts = fetch_alerts(_cursor(now))
        events = record_events(alerts)
        esito.update({"ok": True, "letti": len(alerts), "eventi": len(events)})
        _save_state(CURSOR_KEY, now.isoformat())
        if soc_settings.value("defender.incidenti.attivo"):
            incidenti = fetch_incidents(_incidents_cursor(now))
            nuovi = record_incidents(incidenti)
            esito.update({"incidenti_letti": len(incidenti), "eventi_incidenti": len(nuovi)})
            events = [*events, *nuovi]
            _save_state(CURSOR_INCIDENTS_KEY, now.isoformat())
        if events:
            from security.services.rule_engine import evaluate_security_rules

            evaluate_security_rules()
    except Exception as exc:  # noqa: BLE001 - il ciclo SOC prosegue con gli altri passi
        logger.warning("Defender: giro non riuscito: %s", exc)
        esito.update({"ok": False, "errore": str(exc)[:300]})
    _save_state(LAST_RUN_KEY, esito)
    return esito


def last_run() -> dict:
    from security.services.configuration import get_setting

    value = get_setting(LAST_RUN_KEY, {})
    return value if isinstance(value, dict) else {}


def meets_threshold(severity: str) -> bool:
    minimum = soc_settings.value("defender.severita_minima")
    return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(minimum, 2)
