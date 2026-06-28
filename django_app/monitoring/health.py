"""
monitoring/health.py — Liveness e readiness check runtime.

Distinzione k8s-style:
  /healthz  -> liveness:  il processo è vivo e in grado di rispondere HTTP
                          (no DB, no integrazioni, sempre 200 se Django è up).
  /readyz   -> readiness: i requisiti runtime sono OK per servire traffico
                          (DB, cache, Graph, LDAP, SMTP). 503 se un check
                          critical fallisce, 200 con status=degraded se solo
                          warning.

Per evitare che endpoint pubblici diventino vettore DoS sulle integrazioni
(token Graph, LDAP bind, SMTP), il risultato di /readyz è memoizzato per
``settings.READYZ_TTL_SECONDS`` (default 10s) tramite il backend cache Django.

Whitelist IP: entrambi gli endpoint accettano solo client da
``settings.HEALTHZ_ALLOWED_IPS`` (default loopback). IIS/Application Proxy
deve essere incluso nei trusted proxies se serve esporli all'esterno.
"""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from django.conf import settings
from django.core.cache import cache
from django.db import connections

logger = logging.getLogger(__name__)


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIPPED = "skipped"

# Soglie comportamento aggregato.
_SEVERITY_RANK = {STATUS_OK: 0, STATUS_SKIPPED: 0, STATUS_WARN: 1, STATUS_FAIL: 2}

# Cache key per il risultato memoizzato.
_READYZ_CACHE_KEY = "monitoring:readyz:result"
# Cache key per lo stato dell'ultimo alert AI (fingerprint dei check degradati):
# evita di rispammare la stessa mail finché il degrado non cambia (TTL = rate limit).
_AI_ALERT_STATE_KEY = "monitoring:ai-alert:fingerprint"


@dataclass
class CheckResult:
    name: str
    status: str
    latency_ms: int
    critical: bool = False
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReadyzReport:
    status: str
    checks: list[CheckResult]
    cached: bool = False
    generated_at: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cached": self.cached,
            "generated_at": self.generated_at,
            "checks": [asdict(check) for check in self.checks],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Whitelist IP
# ──────────────────────────────────────────────────────────────────────────────


def _client_ip(request) -> str:
    """Estrae l'IP client rispettando TRUSTED_PROXY_IPS (se richiesto in futuro).

    Per gli endpoint health non leggiamo X-Forwarded-For: chi vuole esporre
    healthz dietro proxy deve aggiungere l'IP del proxy a HEALTHZ_ALLOWED_IPS.
    Questo evita spoofing banale.
    """
    return (request.META.get("REMOTE_ADDR", "") or "").strip()


def is_ip_allowed(request) -> bool:
    allowed = set(getattr(settings, "HEALTHZ_ALLOWED_IPS", ()) or ())
    if not allowed:
        # Fail-closed: senza allowlist espongo solo loopback.
        allowed = {"127.0.0.1", "::1"}
    return _client_ip(request) in allowed


# ──────────────────────────────────────────────────────────────────────────────
# Singoli check
# ──────────────────────────────────────────────────────────────────────────────


def _timed(func: Callable[[], CheckResult]) -> CheckResult:
    """Esegue il check e popola latency_ms; cattura qualsiasi eccezione."""
    started = time.perf_counter()
    try:
        result = func()
    except Exception as exc:  # noqa: BLE001 - per design, ogni check è isolato
        logger.exception("Health check ha sollevato un'eccezione non gestita")
        result = CheckResult(
            name=getattr(func, "__name__", "unknown"),
            status=STATUS_FAIL,
            latency_ms=0,
            critical=True,
            message=f"{exc.__class__.__name__}: {exc}",
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if result.latency_ms == 0:
        result.latency_ms = elapsed_ms
    return result


def check_db_default() -> CheckResult:
    name = "db_default"
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=True,
            message=f"{exc.__class__.__name__}: {exc}",
        )
    return CheckResult(name=name, status=STATUS_OK, latency_ms=0, critical=True)


def check_db_legacy() -> CheckResult:
    """Verifica la connessione al DB legacy (alias 'legacy' o 'default' se unico)."""
    name = "db_legacy"
    alias = "legacy" if "legacy" in connections.databases else None
    if alias is None:
        return CheckResult(
            name=name,
            status=STATUS_SKIPPED,
            latency_ms=0,
            critical=False,
            message="Alias 'legacy' non configurato.",
        )
    try:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=True,
            message=f"{exc.__class__.__name__}: {exc}",
        )
    return CheckResult(name=name, status=STATUS_OK, latency_ms=0, critical=True)


def check_cache() -> CheckResult:
    name = "cache"
    key = "monitoring:readyz:probe"
    value = f"{time.time()}"
    try:
        cache.set(key, value, timeout=5)
        roundtrip = cache.get(key)
        cache.delete(key)
    except Exception as exc:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message=f"{exc.__class__.__name__}: {exc}",
        )
    if roundtrip != value:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message="Cache get non ha restituito il valore atteso.",
        )
    return CheckResult(name=name, status=STATUS_OK, latency_ms=0)


def check_graph_token() -> CheckResult:
    """Verifica acquisizione token Graph riusando la cache MSAL esistente.

    Se l'integrazione non è configurata, ritorna SKIPPED senza errore.
    """
    name = "graph_token"
    tenant = (
        getattr(settings, "GRAPH_TENANT_ID", "") or getattr(settings, "AZURE_TENANT_ID", "") or ""
    ).strip()
    client_id = (
        getattr(settings, "GRAPH_CLIENT_ID", "") or getattr(settings, "AZURE_CLIENT_ID", "") or ""
    ).strip()
    client_secret = (
        getattr(settings, "GRAPH_CLIENT_SECRET", "")
        or getattr(settings, "AZURE_CLIENT_SECRET", "")
        or ""
    ).strip()

    if not (tenant and client_id and client_secret):
        return CheckResult(
            name=name,
            status=STATUS_SKIPPED,
            latency_ms=0,
            message="Credenziali Graph non configurate.",
        )

    try:
        from core.graph_utils import acquire_graph_token

        token = acquire_graph_token(tenant, client_id, client_secret)
    except Exception as exc:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message=f"{exc.__class__.__name__}: {exc}",
        )
    if not token or not isinstance(token, str):
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message="Token Graph vuoto o tipo inatteso.",
        )
    return CheckResult(name=name, status=STATUS_OK, latency_ms=0)


def check_ldap() -> CheckResult:
    """Verifica raggiungibilità del server LDAP via TCP.

    Non esegue bind autenticato (richiederebbe credenziali di servizio nel
    payload del check); verifica solo che il socket si apra entro il timeout.
    """
    name = "ldap"
    if not bool(getattr(settings, "LDAP_ENABLED", False)):
        return CheckResult(
            name=name, status=STATUS_SKIPPED, latency_ms=0, message="LDAP disabilitato."
        )
    server = (getattr(settings, "LDAP_SERVER", "") or "").strip()
    if not server:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message="LDAP_SERVER non configurato.",
        )
    timeout = float(getattr(settings, "LDAP_TIMEOUT", 5) or 5)
    host, port = _split_ldap_url(server)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message=f"{exc.__class__.__name__}: {exc}",
            details={"host": host, "port": port},
        )
    return CheckResult(
        name=name, status=STATUS_OK, latency_ms=0, details={"host": host, "port": port}
    )


def check_smtp() -> CheckResult:
    """Apre la connessione SMTP e la chiude. No invio reale."""
    name = "smtp"
    backend = (getattr(settings, "EMAIL_BACKEND", "") or "").strip()
    if not backend.endswith(".smtp.EmailBackend"):
        return CheckResult(
            name=name,
            status=STATUS_SKIPPED,
            latency_ms=0,
            message=f"Backend email non SMTP ({backend or 'non configurato'}).",
        )
    host = (getattr(settings, "EMAIL_HOST", "") or "").strip()
    if not host:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message="EMAIL_HOST non configurato.",
        )
    try:
        from django.core.mail import get_connection

        connection = get_connection(backend=backend, fail_silently=False, timeout=5)
        connection.open()
        connection.close()
    except Exception as exc:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message=f"{exc.__class__.__name__}: {exc}",
            details={"host": host},
        )
    return CheckResult(name=name, status=STATUS_OK, latency_ms=0, details={"host": host})


def check_automation_queue() -> CheckResult:
    """Conteggio rapido dei job mancanti rilevati dal monitoring esistente."""
    name = "automation_queue"
    try:
        from monitoring.services import detect_missed_jobs

        missed = detect_missed_jobs(create_issues=False)
    except Exception as exc:
        return CheckResult(
            name=name,
            status=STATUS_FAIL,
            latency_ms=0,
            critical=False,
            message=f"{exc.__class__.__name__}: {exc}",
        )
    count = len(missed)
    status = STATUS_OK if count == 0 else STATUS_WARN
    return CheckResult(
        name=name,
        status=status,
        latency_ms=0,
        critical=False,
        details={"missing_jobs": count},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Check Assistente AI (Ollama / embeddings-TEI) — NON registrati nel readyz hot
# path: fanno chiamate di rete al box GPU, le esegue il monitoring schedulato
# (run_ai_readiness_alert) non ogni probe HTTP. critical=False: l'AI è fail-safe
# (degrada a BM25), un suo problema non deve mai mandare /readyz in 503.
# ──────────────────────────────────────────────────────────────────────────────


def _ai_checks_enabled() -> bool:
    return bool(getattr(settings, "MONITORING_AI_CHECKS_ENABLED", True))


def _ai_timeout() -> float:
    return float(getattr(settings, "MONITORING_AI_CHECK_TIMEOUT", 4) or 4)


def _ollama_model_names(base_url: str) -> list[str]:
    import json as _json
    import urllib.request

    req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=_ai_timeout()) as response:
        data = _json.loads(response.read().decode("utf-8", "replace"))
    return [str(m.get("name", "")) for m in (data.get("models") or [])]


def _model_present(names: list[str], model: str) -> bool:
    if not model:
        return True
    base = model.split(":")[0]
    return any(n == model or n.split(":")[0] == base for n in names)


def check_ollama_chat() -> CheckResult:
    name = "ollama_chat"
    if not _ai_checks_enabled() or not bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True)):
        return CheckResult(name=name, status=STATUS_SKIPPED, latency_ms=0, message="Chat AI disabilitata.")
    base = (getattr(settings, "OLLAMA_BASE_URL", "") or "http://127.0.0.1:11434").rstrip("/")
    model = (getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip()
    try:
        names = _ollama_model_names(base)
    except Exception as exc:
        return CheckResult(name=name, status=STATUS_FAIL, latency_ms=0, critical=False,
                           message=f"Ollama irraggiungibile: {exc.__class__.__name__}: {exc}",
                           details={"base_url": base})
    if not _model_present(names, model):
        return CheckResult(name=name, status=STATUS_WARN, latency_ms=0, critical=False,
                           message=f"Modello chat '{model}' non presente in Ollama.",
                           details={"base_url": base, "models": len(names)})
    return CheckResult(name=name, status=STATUS_OK, latency_ms=0,
                       details={"base_url": base, "model": model})


def check_embeddings() -> CheckResult:
    name = "ai_embeddings"
    if not _ai_checks_enabled():
        return CheckResult(name=name, status=STATUS_SKIPPED, latency_ms=0, message="Check AI disabilitati.")
    if not bool(getattr(settings, "OLLAMA_EMBED_ENABLED", False)):
        return CheckResult(name=name, status=STATUS_SKIPPED, latency_ms=0,
                           message="Embeddings disattivati (BM25-only).")
    backend = (getattr(settings, "RAG_EMBED_BACKEND", "ollama") or "ollama").strip().lower()
    if backend == "openai":  # TEI / endpoint OpenAI-compatibile
        base = (getattr(settings, "RAG_EMBED_OPENAI_BASE_URL", "") or "").rstrip("/")
        model = (getattr(settings, "RAG_EMBED_OPENAI_MODEL", "") or "").strip()
        if not base or not model:
            return CheckResult(name=name, status=STATUS_WARN, latency_ms=0, critical=False,
                               message="Backend TEI ma BASE_URL/MODEL non configurati.")
        try:
            import json as _json
            import urllib.request

            payload = _json.dumps({"model": model, "input": ["ping"]}).encode("utf-8")
            req = urllib.request.Request(f"{base}/v1/embeddings", data=payload, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=_ai_timeout()) as response:
                data = _json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:
            return CheckResult(name=name, status=STATUS_FAIL, latency_ms=0, critical=False,
                               message=f"TEI non risponde: {exc.__class__.__name__}: {exc}",
                               details={"backend": "tei", "base_url": base})
        dim = len((data.get("data") or [{}])[0].get("embedding") or [])
        if dim == 0:
            return CheckResult(name=name, status=STATUS_WARN, latency_ms=0, critical=False,
                               message="TEI ha risposto senza vettore.",
                               details={"backend": "tei", "base_url": base})
        return CheckResult(name=name, status=STATUS_OK, latency_ms=0,
                           details={"backend": "tei", "base_url": base, "dim": dim})
    # backend Ollama nativo: il modello embeddings deve essere caricato in Ollama
    base = (getattr(settings, "OLLAMA_BASE_URL", "") or "http://127.0.0.1:11434").rstrip("/")
    model = (getattr(settings, "OLLAMA_EMBED_MODEL", "") or "").strip()
    try:
        names = _ollama_model_names(base)
    except Exception as exc:
        return CheckResult(name=name, status=STATUS_FAIL, latency_ms=0, critical=False,
                           message=f"Ollama irraggiungibile: {exc.__class__.__name__}: {exc}",
                           details={"backend": "ollama", "base_url": base})
    if not _model_present(names, model) or not model:
        return CheckResult(name=name, status=STATUS_WARN, latency_ms=0, critical=False,
                           message=f"Modello embeddings '{model}' non presente in Ollama.",
                           details={"backend": "ollama", "base_url": base})
    return CheckResult(name=name, status=STATUS_OK, latency_ms=0,
                       details={"backend": "ollama", "model": model})


def run_ai_checks() -> list[CheckResult]:
    """Esegue i check AI con timing/isolamento eccezioni (come il readyz)."""
    return [_timed(check_ollama_chat), _timed(check_embeddings)]


# Registry: name -> nome attributo del modulo. La risoluzione avviene a
# runtime via getattr(modulo, ...) cosi' i test possono mock.patch.object i
# singoli check senza dover ricostruire il registry.
_CHECK_REGISTRY: dict[str, str] = {
    "db_default": "check_db_default",
    "db_legacy": "check_db_legacy",
    "cache": "check_cache",
    "graph_token": "check_graph_token",
    "ldap": "check_ldap",
    "smtp": "check_smtp",
    "automation_queue": "check_automation_queue",
}


def available_checks() -> list[str]:
    return list(_CHECK_REGISTRY.keys())


def _resolve_check(name: str) -> Callable[[], CheckResult]:
    import sys

    module = sys.modules[__name__]
    attr_name = _CHECK_REGISTRY[name]
    return getattr(module, attr_name)


def _split_ldap_url(url: str) -> tuple[str, int]:
    """Estrae host/porta da una URL LDAP/LDAPS, fallback su defaults standard."""
    raw = url.strip()
    is_ldaps = raw.lower().startswith("ldaps://")
    default_port = 636 if is_ldaps else 389
    cleaned = raw
    for scheme in ("ldaps://", "ldap://"):
        if cleaned.lower().startswith(scheme):
            cleaned = cleaned[len(scheme) :]
            break
    cleaned = cleaned.split("/", 1)[0]
    if ":" in cleaned and not cleaned.endswith("]"):
        host, _, port_text = cleaned.rpartition(":")
        try:
            return host or url, int(port_text)
        except ValueError:
            return cleaned, default_port
    return cleaned or url, default_port


# ──────────────────────────────────────────────────────────────────────────────
# Aggregazione
# ──────────────────────────────────────────────────────────────────────────────


def _enabled_check_names() -> list[str]:
    configured = getattr(settings, "READYZ_CHECKS_ENABLED", None)
    if configured is None:
        return available_checks()
    if isinstance(configured, str):
        items = [item.strip() for item in configured.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in configured if str(item).strip()]
    if not items:
        # Lista vuota = "default" = tutti i check abilitati.
        return available_checks()
    # Manteniamo l'ordine del registry per output stabile.
    return [name for name in available_checks() if name in items]


def _aggregate_status(results: list[CheckResult]) -> str:
    worst_critical = STATUS_OK
    worst_warning = STATUS_OK
    for result in results:
        rank = _SEVERITY_RANK.get(result.status, 0)
        if result.critical and rank > _SEVERITY_RANK[worst_critical]:
            worst_critical = result.status
        elif not result.critical and rank > _SEVERITY_RANK[worst_warning]:
            worst_warning = result.status
    if worst_critical == STATUS_FAIL:
        return STATUS_FAIL
    if worst_warning in {STATUS_FAIL, STATUS_WARN}:
        return STATUS_WARN
    if worst_critical == STATUS_WARN:
        return STATUS_WARN
    return STATUS_OK


def run_readyz_checks() -> ReadyzReport:
    """Esegue (o riusa dalla cache) tutti i check abilitati."""
    ttl = int(getattr(settings, "READYZ_TTL_SECONDS", 10) or 0)
    if ttl > 0:
        cached_payload = cache.get(_READYZ_CACHE_KEY)
        if isinstance(cached_payload, dict):
            return ReadyzReport(
                status=cached_payload["status"],
                checks=[CheckResult(**item) for item in cached_payload["checks"]],
                cached=True,
                generated_at=cached_payload.get("generated_at", 0.0),
            )

    results: list[CheckResult] = []
    for name in _enabled_check_names():
        func = _resolve_check(name)
        results.append(_timed(func))

    report = ReadyzReport(
        status=_aggregate_status(results),
        checks=results,
        cached=False,
        generated_at=time.time(),
    )
    if ttl > 0:
        # Memoizziamo il dict serializzabile, non l'istanza dataclass.
        cache.set(
            _READYZ_CACHE_KEY,
            {
                "status": report.status,
                "generated_at": report.generated_at,
                "checks": [asdict(item) for item in report.checks],
            },
            timeout=ttl,
        )
    return report


def http_status_for(report: ReadyzReport) -> int:
    """Mappa stato aggregato -> HTTP status code.

    - ok        -> 200
    - warn      -> 200 (degraded ma servibile)
    - fail      -> 503 (un check critical è giù)
    """
    if report.status == STATUS_FAIL:
        return 503
    return 200


# ──────────────────────────────────────────────────────────────────────────────
# Alert AI (+ servizi) schedulabile
# ──────────────────────────────────────────────────────────────────────────────


def emit_monitoring_alert(*, subject: str, body: str, fingerprint: str,
                          state_key: str, force: bool = False) -> bool:
    """Invia un'email agli admin del monitoring, riusando destinatari e rate-limit
    (``MONITORING_ADMIN_EMAILS`` / ``MONITORING_EMAIL_RATE_LIMIT_SECONDS``).

    Anti-spam: ``state_key`` memorizza il ``fingerprint`` del degrado con TTL = rate
    limit. Stesso fingerprint entro la finestra → soppresso (no invio, TTL non
    rinnovato → riallarma quando scade come reminder); fingerprint diverso o scaduto
    → invia. Ritorna True se la mail è stata inviata. Riusato da più alert (AI
    readiness, qualità RAG, …). Il chiamante azzera ``state_key`` al ritorno OK.
    """
    last = cache.get(state_key)
    if not force and last == fingerprint:
        return False
    sent = False
    if bool(getattr(settings, "MONITORING_NOTIFY_CRITICAL_BY_EMAIL", True)):
        try:
            from django.core.mail import send_mail

            from monitoring.services import _admin_recipients

            recipients = _admin_recipients()
            if recipients:
                from_email = (
                    getattr(settings, "DEFAULT_FROM_EMAIL", "")
                    or getattr(settings, "SERVER_EMAIL", "")
                    or "monitoring@localhost"
                )
                send_mail(subject, body, from_email, recipients, fail_silently=True)
                sent = True
        except Exception:
            logger.exception("Invio alert monitoring fallito")
    rate_limit = int(getattr(settings, "MONITORING_EMAIL_RATE_LIMIT_SECONDS", 1800) or 1800)
    cache.set(state_key, fingerprint, timeout=rate_limit)
    return sent


def _sync_check_issues(checks: list[CheckResult]) -> None:
    """Apre/risolve una Issue del monitoring per ogni check: FAIL→HIGH, WARN→MEDIUM,
    OK→risolta, SKIPPED→ignorato. Così gli alert AI confluiscono nella centrale
    (monitoring_admin/issues). Fail-safe: non solleva (non deve rompere l'alert)."""
    try:
        from monitoring.models import Issue
        from monitoring.services import (
            open_or_update_issue_from_health_check,
            resolve_health_check_issue,
        )
    except Exception:
        return
    severity_for = {STATUS_FAIL: Issue.Severity.HIGH, STATUS_WARN: Issue.Severity.MEDIUM}
    for c in checks:
        check_name = f"ai_{c.name}"
        try:
            if c.status in (STATUS_FAIL, STATUS_WARN):
                open_or_update_issue_from_health_check(
                    check_name=check_name,
                    title=f"AI · {c.name}: {c.status.upper()}"
                          + (f" — {c.message}" if c.message else ""),
                    message=c.message or "",
                    severity=severity_for[c.status],
                    category=Issue.Category.INTEGRATION,
                    module_name="ai_assistant",
                    extra_json={"check": c.name, "status": c.status, "details": c.details},
                    notify=False,  # il push email lo fa emit_monitoring_alert
                )
            elif c.status == STATUS_OK:
                resolve_health_check_issue(
                    check_name=check_name, category=Issue.Category.INTEGRATION,
                    summary=f"{c.name} tornato OK.",
                )
        except Exception:
            logger.exception("Sync Issue per check %s fallito", c.name)


def run_ai_readiness_alert(*, include_services: bool = False, force_email: bool = False) -> dict[str, Any]:
    """Esegue i check AI (+ opz. i check readyz dei servizi), aggrega e, su degrado
    (WARN/FAIL), invia un alert email agli admin del monitoring.

    Riusa i destinatari e il rate-limit del monitoring (``MONITORING_ADMIN_EMAILS``,
    ``MONITORING_EMAIL_RATE_LIMIT_SECONDS``) e invia SOLO quando il quadro di degrado
    cambia (fingerprint) o scade il rate-limit, così non rispamma. Al ritorno a OK
    azzera lo stato, così il prossimo degrado riallarma subito. Pensato per django-q.
    """
    checks = run_ai_checks()
    if include_services:
        checks = checks + run_readyz_checks().checks
    status = _aggregate_status(checks)
    degraded = status in (STATUS_WARN, STATUS_FAIL)
    payload: dict[str, Any] = {
        "status": status,
        "degraded": degraded,
        "emailed": False,
        "checks": [asdict(c) for c in checks],
    }

    # Centrale di comando: ogni check apre/risolve una Issue del monitoring.
    _sync_check_issues(checks)

    if not degraded:
        cache.delete(_AI_ALERT_STATE_KEY)
        return payload

    fingerprint = ";".join(
        f"{c.name}:{c.status}" for c in checks if c.status in (STATUS_WARN, STATUS_FAIL)
    )
    env_label = getattr(settings, "MONITORING_ENVIRONMENT", "") or ""
    subject = f"[AI {status.upper()}] Readiness assistente AI" + (f" — {env_label}" if env_label else "")
    body_lines = [f"Stato aggregato: {status.upper()}", ""]
    for c in checks:
        suffix = f" · {c.message}" if c.message else ""
        body_lines.append(f"- {c.name}: {c.status.upper()}{suffix}")
    body_lines += ["", "Alert generato da monitoring_ai_alert (rate-limited, solo al cambio stato)."]
    payload["emailed"] = emit_monitoring_alert(
        subject=subject,
        body="\n".join(body_lines),
        fingerprint=fingerprint,
        state_key=_AI_ALERT_STATE_KEY,
        force=force_email,
    )
    return payload
