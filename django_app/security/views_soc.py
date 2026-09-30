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
from security.services.vpn_history import vpn_history_summary


def assets_list(request):
    """Elenco dei SecurityAsset con l'eventuale Asset HUB collegato (fase D2)."""
    assets = (
        SecurityAsset.objects.select_related("source", "hub_asset").order_by("hostname")
    )
    n_tot = assets.count()
    n_linked = assets.exclude(hub_asset__isnull=True).count()
    return render(
        request,
        "security/soc_assets.html",
        {"assets": assets, "n_tot": n_tot, "n_linked": n_linked},
    )


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
    if filters["user"]:
        qs = qs.filter(username__icontains=filters["user"])
    if filters["ip"]:
        qs = qs.filter(source_ip__startswith=filters["ip"])
    if filters["action"] in (SecurityVpnAccess.ACTION_ALLOWED, SecurityVpnAccess.ACTION_DENIED):
        qs = qs.filter(action=filters["action"])
    day_from, day_to = _vpn_day(filters["from"]), _vpn_day(filters["to"])
    if day_from:
        qs = qs.filter(login_at__date__gte=day_from)
    if day_to:
        qs = qs.filter(login_at__date__lte=day_to)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(
        request,
        "security/vpn_history.html",
        {"page": page, "filters": filters, "summary": vpn_history_summary(qs), "query": query.urlencode()},
    )