"""Controlli dell'infrastruttura del server: qcluster, coda, disco, certificato https.

Registrati nel registro di ``monitoring.health`` (Centrale di comando, /readyz) con
``critical=False``: avvisano, non tolgono il sito dal bilanciamento. L'allarme
pianificato ``infra_health_alert`` apre/chiude le segnalazioni nella Centrale e
manda una mail agli amministratori per i soli guasti (come i check di backup).

- **qcluster**: l'ultimo task completato da django-q. Con ``security_cycle`` ogni 15
  minuti, nessun task finito da oltre ``MONITORING_QCLUSTER_STALE_MINUTES`` (40)
  vuol dire qcluster fermo: le automazioni, le mail pianificate e il SOC non girano.
- **coda**: task in attesa (``OrmQ``) oltre soglia e task falliti nelle ultime 24 ore.
- **disco**: spazio libero dei dischi che ospitano log, file caricati, archivi
  privati e area di lavoro dei backup (sotto 15% avviso, sotto 5% guasto).
- **certificato**: giorni alla scadenza del certificato https di ``SITE_URL``
  (30 avviso, 7 guasto). Memorizzato 6 ore: una connessione per giro, non per probe.
"""
from __future__ import annotations

import logging
import shutil
import socket
import ssl
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

_TLS_CACHE_KEY = "monitoring:tls-cert:result"


def _result(name, status, message="", details=None):
    from monitoring.health import CheckResult

    return CheckResult(name=name, status=status, latency_ms=0, critical=False, message=message, details=details or {})


def check_qcluster():
    from monitoring.health import STATUS_FAIL, STATUS_OK, STATUS_SKIPPED

    name = "qcluster"
    try:
        from django_q.models import Schedule, Task
    except Exception:
        return _result(name, STATUS_SKIPPED, "django-q non installato.")
    if not Schedule.objects.exists():
        return _result(name, STATUS_SKIPPED, "Nessun task pianificato registrato.")
    soglia = int(getattr(settings, "MONITORING_QCLUSTER_STALE_MINUTES", 40) or 40)
    ultimo = Task.objects.exclude(stopped__isnull=True).order_by("-stopped").values_list("stopped", flat=True).first()
    if ultimo is None:
        return _result(name, STATUS_FAIL, "Il qcluster non ha mai completato un task: probabilmente non è avviato.")
    minuti = int((timezone.now() - ultimo).total_seconds() // 60)
    details = {"ultimo_task": ultimo.isoformat(), "minuti_fa": minuti, "soglia_minuti": soglia}
    if minuti > soglia:
        return _result(name, STATUS_FAIL,
                       f"Nessun task completato da {minuti} minuti: il qcluster sembra fermo (va riavviato).", details)
    return _result(name, STATUS_OK, f"Ultimo task completato {minuti} minuti fa.", details)


def check_qcluster_coda():
    from monitoring.health import STATUS_OK, STATUS_SKIPPED, STATUS_WARN

    name = "qcluster_coda"
    try:
        from django_q.models import OrmQ, Task
    except Exception:
        return _result(name, STATUS_SKIPPED, "django-q non installato.")
    soglia = int(getattr(settings, "MONITORING_QUEUE_WARN", 50) or 50)
    in_coda = OrmQ.objects.count()
    falliti = list(
        Task.objects.filter(success=False, stopped__gte=timezone.now() - timedelta(hours=24))
        .values_list("func", flat=True)[:200]
    )
    nomi = sorted({str(f).rsplit(".", 1)[-1] for f in falliti})
    details = {"in_coda": in_coda, "falliti_24h": len(falliti), "funzioni_fallite": nomi[:10]}
    problemi = []
    if in_coda > soglia:
        problemi.append(f"{in_coda} task in attesa (soglia {soglia})")
    if falliti:
        problemi.append(f"{len(falliti)} task falliti nelle ultime 24 ore ({', '.join(nomi[:5])})")
    if problemi:
        return _result(name, STATUS_WARN, "; ".join(problemi) + ".", details)
    return _result(name, STATUS_OK, f"{in_coda} task in attesa, nessun fallimento nelle ultime 24 ore.", details)


def _cartelle_da_controllare() -> dict[str, Path]:
    cartelle: dict[str, Path] = {}
    for etichetta, valore in (
        ("log", getattr(settings, "LOG_DIR", "")),
        ("file caricati", getattr(settings, "MEDIA_ROOT", "")),
        ("backup (area di lavoro)", getattr(settings, "BACKUP_STAGING_DIR", "")),
    ):
        if valore:
            cartelle[etichetta] = Path(valore)
    try:
        from core.backup_engine import files

        for chiave, percorso in files.private_roots().items():
            cartelle[f"archivio privato {chiave}"] = Path(percorso)
    except Exception:
        logger.debug("Check disco: cartelle private non lette", exc_info=True)
    return cartelle


def check_disk_space():
    from monitoring.health import STATUS_FAIL, STATUS_OK, STATUS_SKIPPED, STATUS_WARN

    name = "disk_space"
    warn_pct = float(getattr(settings, "MONITORING_DISK_WARN_PCT", 15) or 15)
    fail_pct = float(getattr(settings, "MONITORING_DISK_FAIL_PCT", 5) or 5)
    dischi: dict[str, dict] = {}
    for etichetta, percorso in _cartelle_da_controllare().items():
        p = percorso
        while not p.exists() and p.parent != p:
            p = p.parent
        if not p.exists():
            continue
        try:
            uso = shutil.disk_usage(p)
        except OSError:
            continue
        radice = p.anchor or str(p)
        voce = dischi.setdefault(radice, {
            "libero_gb": round(uso.free / 1024 ** 3, 1),
            "libero_pct": round(uso.free * 100 / uso.total, 1) if uso.total else 0.0,
            "cartelle": [],
        })
        voce["cartelle"].append(etichetta)
    if not dischi:
        return _result(name, STATUS_SKIPPED, "Nessuna cartella da controllare.")
    peggiore = min(dischi.items(), key=lambda kv: kv[1]["libero_pct"])
    radice, voce = peggiore
    msg = f"Disco {radice}: {voce['libero_gb']} GB liberi ({voce['libero_pct']}%), usato da {', '.join(voce['cartelle'])}."
    if voce["libero_pct"] < fail_pct:
        return _result(name, STATUS_FAIL, msg, {"dischi": dischi})
    if voce["libero_pct"] < warn_pct:
        return _result(name, STATUS_WARN, msg, {"dischi": dischi})
    return _result(name, STATUS_OK, msg, {"dischi": dischi})


def _scadenza_certificato(host: str, porta: int, timeout: float = 5.0):
    """Data di scadenza del certificato presentato da host:porta (anche se la CA è
    interna: si legge il certificato, non si valida la catena)."""
    from cryptography import x509

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, porta), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    cert = x509.load_der_x509_certificate(der)
    scadenza = getattr(cert, "not_valid_after_utc", None) or timezone.make_aware(cert.not_valid_after, timezone.utc)
    return scadenza


def check_tls_cert():
    from monitoring.health import STATUS_FAIL, STATUS_OK, STATUS_SKIPPED, STATUS_WARN

    name = "tls_cert"
    cached = cache.get(_TLS_CACHE_KEY)
    if isinstance(cached, dict):
        from monitoring.health import CheckResult

        return CheckResult(**cached)
    url = str(getattr(settings, "SITE_URL", "") or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return _result(name, STATUS_SKIPPED, "SITE_URL non è https: nessun certificato da controllare.")
    try:
        scadenza = _scadenza_certificato(parts.hostname, parts.port or 443)
    except Exception as exc:  # noqa: BLE001 - rete, DNS, handshake
        result = _result(name, STATUS_WARN, f"Certificato di {parts.hostname} non leggibile: {exc.__class__.__name__}.")
    else:
        giorni = (scadenza - timezone.now()).days
        details = {"host": parts.hostname, "scade_il": scadenza.date().isoformat(), "giorni": giorni}
        if giorni < 0:
            result = _result(name, STATUS_FAIL, f"Il certificato https di {parts.hostname} è SCADUTO il {scadenza:%d/%m/%Y}.", details)
        elif giorni <= int(getattr(settings, "MONITORING_TLS_FAIL_DAYS", 7) or 7):
            result = _result(name, STATUS_FAIL, f"Il certificato https di {parts.hostname} scade tra {giorni} giorni ({scadenza:%d/%m/%Y}).", details)
        elif giorni <= int(getattr(settings, "MONITORING_TLS_WARN_DAYS", 30) or 30):
            result = _result(name, STATUS_WARN, f"Il certificato https di {parts.hostname} scade tra {giorni} giorni ({scadenza:%d/%m/%Y}).", details)
        else:
            result = _result(name, STATUS_OK, f"Certificato https valido fino al {scadenza:%d/%m/%Y} ({giorni} giorni).", details)
    from dataclasses import asdict

    cache.set(_TLS_CACHE_KEY, asdict(result), 6 * 3600)
    return result
