"""Storico accessi VPN: salvataggio dei record dei report e statistiche per pagina/KPI."""
from datetime import timedelta

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from security.models import SecurityVpnAccess
from security.parsers.watchguard.common import parse_datetime
from security.services.dedup import make_hash

_BATCH = 200

# Soglie dei segnali «Da controllare»: le stesse dei parser dove esistono.
DENIED_BURST = 10          # rifiuti dallo stesso IP
DENIED_THEN_OK = 5         # rifiuti seguiti da un accesso riuscito dallo stesso IP
MANY_IPS = 5               # IP distinti per lo stesso utente nel periodo
LONG_SESSION = 8 * 3600
NIGHT_HOURS = (22, 23, 0, 1, 2, 3, 4, 5)


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
    denied_pct = round(100 * totals["denied"] / totals["total"]) if totals["total"] else 0
    return {**totals, "avg": round(totals["avg"] or 0), "unique_users": users, "denied_pct": denied_pct, "top_users": top_users, "top_ips": top_ips}


def vpn_daily_series(qs, day_from=None, day_to=None, max_days=45):
    """Barre impilate consentiti/negati per giorno, gia' in coordinate SVG (niente calcoli nel template)."""
    day_to = day_to or timezone.localdate()
    day_from = max(day_from or (day_to - timedelta(days=29)), day_to - timedelta(days=max_days - 1))
    rows = (
        qs.filter(login_at__isnull=False).annotate(day=TruncDate("login_at")).filter(day__gte=day_from, day__lte=day_to)
        .order_by().values("day")
        .annotate(allowed=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_ALLOWED)), denied=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_DENIED)))
    )
    by_day = {row["day"]: row for row in rows}
    span = (day_to - day_from).days + 1
    width, height, top, left = 760, 170, 14, 34
    peak = max([r["allowed"] + r["denied"] for r in by_day.values()] or [1]) or 1
    slot = (width - left) / span
    bar = max(slot * 0.68, 3)
    baseline = top + height
    days = []
    for i in range(span):
        day = day_from + timedelta(days=i)
        row = by_day.get(day, {"allowed": 0, "denied": 0})
        h_allowed = height * row["allowed"] / peak
        h_denied = height * row["denied"] / peak
        days.append({
            "date": day,
            "x": round(left + i * slot + (slot - bar) / 2, 1),
            "w": round(bar, 1),
            "label_x": round(left + i * slot + slot / 2, 1),
            "y_allowed": round(baseline - h_allowed, 1), "h_allowed": round(h_allowed, 1),
            "y_denied": round(baseline - h_allowed - h_denied, 1), "h_denied": round(h_denied, 1),
            "allowed": row["allowed"], "denied": row["denied"],
            "show_label": i % max(span // 8, 1) == 0,
        })
    return {"days": days, "peak": peak, "width": width, "height": height + top + 24, "baseline": baseline, "top": top, "left": left,
            "empty": not by_day}


def vpn_hour_profile(qs):
    """Accessi consentiti per ora del giorno: fa risaltare l'attivita' notturna."""
    counts = {row["hour"]: row["n"] for row in (
        qs.filter(action=SecurityVpnAccess.ACTION_ALLOWED, login_at__isnull=False)
        .annotate(hour=ExtractHour("login_at")).order_by().values("hour").annotate(n=Count("id"))
    )}
    peak = max(counts.values() or [1]) or 1
    return [{"hour": h, "n": counts.get(h, 0), "pct": round(100 * counts.get(h, 0) / peak), "night": h in NIGHT_HOURS} for h in range(24)]


def vpn_findings(qs):
    """Segnali da verificare, dal piu' grave: ognuno ha un testo pronto e un filtro per approfondire."""
    findings = []
    denied = qs.filter(action=SecurityVpnAccess.ACTION_DENIED)
    ok = qs.filter(action=SecurityVpnAccess.ACTION_ALLOWED)
    ok_ips = set(ok.exclude(source_ip="").order_by().values_list("source_ip", flat=True).distinct())
    for row in denied.exclude(source_ip="").order_by().values("source_ip").annotate(n=Count("id"), users=Count("username", distinct=True)).filter(n__gte=DENIED_BURST).order_by("-n")[:5]:
        ip = row["source_ip"]
        if ip in ok_ips and row["n"] >= DENIED_THEN_OK:
            findings.append({"level": "high", "title": f"Accesso riuscito dopo {row['n']} rifiuti da {ip}",
                             "detail": "Lo stesso indirizzo ha prima fallito e poi ottenuto un accesso: verificare che l'utente sia legittimo.", "filter": f"ip={ip}"})
        else:
            findings.append({"level": "high" if row["n"] >= DENIED_BURST * 3 else "warning", "title": f"{row['n']} accessi negati da {ip}",
                             "detail": f"{row['users']} {'nome utente provato' if row['users'] == 1 else 'nomi utente provati'}: possibile tentativo di forza bruta.", "filter": f"ip={ip}&action=denied"})
    for row in ok.filter(login_at__isnull=False).annotate(hour=ExtractHour("login_at")).filter(hour__in=NIGHT_HOURS).exclude(username="").order_by().values("username").annotate(n=Count("id")).order_by("-n")[:3]:
        findings.append({"level": "warning", "title": f"{row['username']}: {row['n']} accessi in orario notturno",
                         "detail": "Tra le 22 e le 6. Normale per reperibilita' o account di servizio, altrimenti da verificare.", "filter": f"user={row['username']}"})
    for row in ok.exclude(username="").order_by().values("username").annotate(ips=Count("source_ip", distinct=True)).filter(ips__gte=MANY_IPS).order_by("-ips")[:3]:
        findings.append({"level": "warning", "title": f"{row['username']} da {row['ips']} indirizzi diversi",
                         "detail": "Molti IP di origine nel periodo: puo' indicare credenziali condivise o in uso da altri.", "filter": f"user={row['username']}"})
    long_n = ok.filter(duration_seconds__gt=LONG_SESSION).count()
    if long_n:
        findings.append({"level": "info", "title": f"{long_n} sessioni oltre 8 ore", "detail": "Sessioni rimaste aperte a lungo: utile per capire se si disconnettono.", "filter": "action=allowed"})
    order = {"high": 0, "warning": 1, "info": 2}
    return sorted(findings, key=lambda f: order[f["level"]])[:8]
