"""Viste aggiuntive dell'innesto SOC IT - CN (non presenti nell'app SC-AI originale).

Tenute separate dal grande `views.py` di SC-AI per isolamento dell'innesto.
"""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from django.core.paginator import Paginator
from django.utils import timezone

from security.models import SecurityAsset, SecurityMailboxSource, SecurityVpnAccess
from security.permissions import can_view_security_center
from security.services.vpn_history import vpn_daily_series, vpn_findings, vpn_history_summary, vpn_hour_profile


def assets_list(request):
    """Dispositivi citati dai report, con l'asset HUB collegato o proposto (conferma manuale)."""
    from django.db.models import Count, Max

    from security.services.asset_signals import link, suggest_hub_asset
    from security.services.configuration import can_manage_security_config

    can_manage = can_manage_security_config(request.user)
    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Serve il permesso di configurazione del Security Center.")
            return redirect("security:assets")
        _assets_post(request, link, suggest_hub_asset)
        return redirect(request.get_full_path())

    base = SecurityAsset.objects.select_related("source", "hub_asset")
    n_tot = base.count()
    n_linked = base.exclude(hub_asset__isnull=True).count()
    view = request.GET.get("stato") or ("da_collegare" if n_tot - n_linked else "tutti")
    qs = base.annotate(n_signals=Count("signals"), last_signal=Max("signals__occurred_at")).order_by("hostname")
    if view == "da_collegare":
        qs = qs.filter(hub_asset__isnull=True)
    elif view == "collegati":
        qs = qs.exclude(hub_asset__isnull=True)
    rows = []
    for asset in qs[:500]:
        suggestion, reason = (None, "") if asset.hub_asset_id else suggest_hub_asset(asset)
        rows.append({"asset": asset, "suggestion": suggestion, "reason": reason})
    return render(
        request,
        "security/soc_assets.html",
        {"rows": rows, "n_tot": n_tot, "n_linked": n_linked, "view": view, "can_manage": can_manage,
         "n_suggested": sum(1 for r in rows if r["suggestion"])},
    )


def _assets_post(request, link, suggest_hub_asset):
    from assets.models import Asset

    action = request.POST.get("action")
    if action == "confirm":
        asset = SecurityAsset.objects.filter(pk=request.POST.get("asset") or 0).first()
        hub = Asset.objects.filter(pk=request.POST.get("hub") or 0).first()
        if not asset or not hub:
            messages.error(request, "Dispositivo o asset non trovato.")
            return
        link(asset, hub, actor=request.user, request=request)
        messages.success(request, f"«{asset.hostname}» collegato a «{hub.name}».")
    elif action == "confirm_all":
        done = 0
        for asset in SecurityAsset.objects.filter(hub_asset__isnull=True):
            suggestion, _reason = suggest_hub_asset(asset)
            if suggestion:
                link(asset, suggestion, actor=request.user, request=request)
                done += 1
        messages.success(request, f"{done} dispositivi collegati alle proposte univoche (IP o nome).")
    elif action == "unlink":
        asset = SecurityAsset.objects.filter(pk=request.POST.get("asset") or 0).first()
        if asset and asset.hub_asset_id:
            link(asset, None, actor=request.user, request=request)
            messages.success(request, f"«{asset.hostname}» scollegato.")


@require_POST
def run_mailbox_ingestion_view(request):
    """Esegue (sincrono) l'ingestione delle sorgenti mailbox graph/imap abilitate.

    Le credenziali (Graph/IMAP) vanno configurate nella Configuration Studio
    (`/soc/admin/config/general/`) come SecurityCenterSetting: qui non si toccano.
    Per esecuzioni pianificate usare il task django-q2 `ingest_security_mailboxes_task`.
    """
    from security.services.configuration import can_manage_security_config

    if not can_manage_security_config(request.user):
        messages.error(request, "Serve il permesso di configurazione del Security Center.")
        return redirect("security:admin_mailbox_sources_list")
    from security.services.mailbox_ingestion import run_mailbox_ingestion

    sources = list(
        SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual")
    )
    if not sources:
        messages.info(
            request,
            "Nessuna sorgente mailbox Graph/IMAP abilitata. Creane una e imposta le "
            "credenziali nella Configurazione (config generale).",
        )
        return redirect("security:admin_mailbox_sources_list")

    from security.services.mailbox_setup import run_summary

    # run_mailbox_ingestion NON solleva: l'esito sta nel run. Prima il try/except qui
    # non scattava mai e un errore di credenziali veniva riportato come «ok».
    ok = err = 0
    for src in sources:
        level, text = run_summary(run_mailbox_ingestion(src))
        if level == "error":
            err += 1
            messages.warning(request, f"«{src.name}»: {text}")
        else:
            ok += 1
    messages.success(request, f"Lettura caselle eseguita: {ok} ok, {err} in errore.")
    return redirect("security:admin_mailbox_sources_list")

def _vpn_day(value):
    try:
        return timezone.datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except ValueError:
        return None


def vpn_history(request):
    """Storico accessi VPN (consentiti/negati) letto dai report Firebox, con filtri e classifiche."""
    if not can_view_security_center(request.user):
        from security.views import _security_center_denied

        return _security_center_denied(request)
    qs = SecurityVpnAccess.objects.select_related("source")
    filters = {key: (request.GET.get(key) or "").strip() for key in ("user", "ip", "action", "from", "to")}
    # Di default solo le VPN: il report Authentication contiene anche i login «Firewall».
    filters["kind"] = (request.GET.get("kind") or "vpn").strip()
    if filters["kind"] in ("vpn", "firewall", "guest", "other"):
        qs = qs.filter(kind=filters["kind"])
    if filters["user"]:
        qs = qs.filter(username__icontains=filters["user"])
    if filters["ip"]:
        qs = qs.filter(source_ip__startswith=filters["ip"])
    if filters["action"] in (SecurityVpnAccess.ACTION_ALLOWED, SecurityVpnAccess.ACTION_DENIED):
        qs = qs.filter(action=filters["action"])
    # Periodo: date esplicite se date, altrimenti gli ultimi N giorni (pulsanti 7/30/90).
    try:
        days = int(request.GET.get("giorni") or 30)
    except ValueError:
        days = 30
    days = days if days in (7, 30, 90) else 30
    day_from, day_to = _vpn_day(filters["from"]), _vpn_day(filters["to"])
    custom = bool(day_from or day_to)
    if not custom:
        day_to = timezone.localdate()
        day_from = day_to - timezone.timedelta(days=days - 1)
    base = qs
    if day_from:
        qs = qs.filter(login_at__date__gte=day_from)
    if day_to:
        qs = qs.filter(login_at__date__lte=day_to)
    daily = vpn_daily_series(qs, day_from, day_to, max_days=120)
    # Giorno scelto cliccando una barra: il grafico resta sul periodo, il resto della pagina va sul giorno.
    selected_day = _vpn_day(request.GET.get("giorno"))
    if selected_day and day_from and day_to and not (day_from <= selected_day <= day_to):
        selected_day = None
    if selected_day:
        day_from_eff = day_to_eff = selected_day
        qs = qs.filter(login_at__date=selected_day)
    else:
        day_from_eff, day_to_eff = day_from, day_to
    previous = None
    if day_from_eff and day_to_eff:
        span = (day_to_eff - day_from_eff).days + 1
        prev_to = day_from_eff - timezone.timedelta(days=1)
        previous = vpn_history_summary(base.filter(login_at__date__gte=prev_to - timezone.timedelta(days=span - 1), login_at__date__lte=prev_to))
    summary = vpn_history_summary(qs)
    for day in daily.get("days", []):
        day["selected"] = day["date"] == selected_day
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    day_query = query.copy()
    day_query.pop("giorno", None)
    chip_query = request.GET.copy()
    for key in ("page", "giorni", "from", "to", "giorno"):
        chip_query.pop(key, None)
    return render(
        request,
        "security/vpn_history.html",
        {
            "page": page,
            "filters": filters,
            "summary": summary,
            "tiles": _vpn_tiles(summary, previous, daily),
            "top_users": _with_share(summary["top_users"][:8]),
            "top_ips": _with_share(summary["top_ips"][:8]),
            "daily": daily,
            "hours": vpn_hour_profile(qs),
            "findings": vpn_findings(qs),
            "has_method": True,
            "query": query.urlencode(),
            "day_query": day_query.urlencode(),
            "selected_day": selected_day,
            "chip_query": chip_query.urlencode(),
            "days": days,
            "custom": custom,
            "day_from": day_from,
            "day_to": day_to,
        },
    )


def _with_share(rows):
    peak = max([row["total"] for row in rows] or [1]) or 1
    return [{**row, "share": round(100 * row["total"] / peak)} for row in rows]


def _vpn_tiles(summary, previous, daily):
    from security.services.kpi_dashboard import _sparkline

    days = daily.get("days", [])
    series = {
        "total": [d["allowed"] + d["denied"] for d in days],
        "allowed": [d["allowed"] for d in days],
        "denied": [d["denied"] for d in days],
    }
    tiles = []
    for key, label, spark in (
        ("total", "Accessi", "total"), ("allowed", "Consentiti", "allowed"), ("denied", "Negati", "denied"),
        ("unique_users", "Utenti distinti", None), ("avg", "Durata media sessione", None),
    ):
        value = summary.get(key) or 0
        before = (previous or {}).get(key)
        tiles.append({
            "label": label, "key": key, "value": value,
            "delta": None if before is None else value - before,
            "spark": _sparkline(series[spark]) if spark else "",
            "warn": key == "denied" and summary.get("denied_pct", 0) >= 20,
        })
    return tiles