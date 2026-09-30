"""Storico accessi VPN: salvataggio dei record dei report e statistiche per pagina/KPI."""
from datetime import timedelta

from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from security.models import SecurityVpnAccess
from security.parsers.watchguard.common import parse_datetime
from security.services.dedup import make_hash

_BATCH = 200


def _aware(value):
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return timezone.make_aware(parsed, timezone.get_current_timezone()) if timezone.is_naive(parsed) else parsed


def persist_vpn_accesses(source, report, payloads):
    """Salva gli accessi di un report, saltando quelli gia' noti. Ritorna quanti ne ha creati.

    Dedup in Python + un solo INSERT a blocchi: su SQL Server un singolo scarto per
    vincolo unico invaliderebbe l'intera transazione, quindi non si tenta e si ripara.
    """
    candidates = {}
    for payload in payloads:
        action = payload.get("action")
        if action not in (SecurityVpnAccess.ACTION_ALLOWED, SecurityVpnAccess.ACTION_DENIED):
            continue
        digest = make_hash(
            "vpn_access", action, payload.get("user"), payload.get("source_ip"),
            payload.get("login_time"), payload.get("logout_time"), payload.get("duration"),
        )
        if digest in candidates:
            continue
        candidates[digest] = SecurityVpnAccess(
            source=source,
            report=report,
            action=action,
            username=str(payload.get("user") or "")[:255],
            source_ip=str(payload.get("source_ip") or "")[:64],
            login_at=_aware(payload.get("login_time")),
            logout_at=_aware(payload.get("logout_time")),
            duration_seconds=max(int(payload.get("duration_seconds") or 0), 0),
            method=str(payload.get("method") or "")[:64],
            firebox_name=str(payload.get("firebox_name") or "")[:120],
            dedup_hash=digest,
        )
    if not candidates:
        return 0
    known = set()
    keys = list(candidates)
    for i in range(0, len(keys), _BATCH):
        known.update(
            SecurityVpnAccess.objects.filter(source=source, dedup_hash__in=keys[i:i + _BATCH]).values_list("dedup_hash", flat=True)
        )
    new_rows = [row for digest, row in candidates.items() if digest not in known]
    SecurityVpnAccess.objects.bulk_create(new_rows, batch_size=_BATCH)
    return len(new_rows)


def vpn_day_stats(day, source_id=None):
    """Metriche del giorno calcolate sullo storico (gli unici non si sommano tra report)."""
    start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
    qs = SecurityVpnAccess.objects.filter(login_at__gte=start, login_at__lt=start + timedelta(days=1))
    if source_id is not None:
        qs = qs.filter(source_id=source_id)
    allowed = qs.filter(action=SecurityVpnAccess.ACTION_ALLOWED)
    denied = qs.filter(action=SecurityVpnAccess.ACTION_DENIED)
    durations = allowed.exclude(duration_seconds=0).aggregate(avg=Avg("duration_seconds"), max=Max("duration_seconds"))
    return {
        "vpn_access_allowed": allowed.count(),
        "vpn_access_denied": denied.count(),
        "vpn_unique_users": qs.exclude(username="").values("username").distinct().count(),
        "vpn_unique_source_ips": qs.exclude(source_ip="").values("source_ip").distinct().count(),
        "vpn_session_avg_seconds": round(durations["avg"] or 0, 1),
        "vpn_session_max_seconds": durations["max"] or 0,
    }


def vpn_history_summary(qs):
    """Contatori e classifiche per la pagina storico, sul queryset gia' filtrato."""
    totals = qs.aggregate(
        total=Count("id"),
        allowed=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_ALLOWED)),
        denied=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_DENIED)),
        avg=Avg("duration_seconds", filter=Q(action=SecurityVpnAccess.ACTION_ALLOWED, duration_seconds__gt=0)),
    )
    top_users = list(
        qs.exclude(username="").order_by().values("username")
        .annotate(total=Count("id"), denied=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_DENIED)), last=Max("login_at"))
        .order_by("-total", "username")[:10]
    )
    top_ips = list(
        qs.exclude(source_ip="").order_by().values("source_ip")
        .annotate(total=Count("id"), denied=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_DENIED)))
        .order_by("-total", "source_ip")[:10]
    )
    users = qs.exclude(username="").order_by().values("username").distinct().count()
    return {**totals, "avg": round(totals["avg"] or 0), "unique_users": users, "top_users": top_users, "top_ips": top_ips}
