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
