"""Indirizzi IP dal DHCP e dal DNS di Windows Server (``/assets/rete/indirizzi/``), in sola lettura.

I dati li scrive lo schedule ``rete_windows_sync`` (``services.rete_windows``); la
pagina filtra e mostra. Il collegamento di un indirizzo a un asset si conferma dalla
riconciliazione dispositivi IT, come per SNMP, SOC e Intune.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.acl import user_can_modulo_action
from core.audit import log_action

from .services import rete_windows


def _puo_configurare(request) -> bool:
    return bool(getattr(request.user, "is_superuser", False)) or user_can_modulo_action(request, "assets", "admin_assets")


def _azione(request: HttpRequest) -> None:
    azione = request.POST.get("azione") or ""
    if azione == "salva":
        errori = rete_windows.salva_config(request.POST.get("dhcp", ""), request.POST.get("dns", ""),
                                           request.POST.get("zone", ""), request.user)
        if errori:
            messages.error(request, " ".join(errori))
            return
        cfg = rete_windows.config()
        log_action(request, "rete_windows_config", "assets", {"dhcp": cfg["dhcp"], "dns": cfg["dns"], "zone": cfg["zone"]})
        messages.success(request, "Server DHCP e DNS salvati. Premi «Leggi adesso» per la prima lettura.")
    elif azione == "leggi":
        if not rete_windows.configurato():
            messages.error(request, "Scrivi prima almeno un server DHCP (o il server DNS con le zone).")
            return
        try:
            from security.services import letture

            ok, testo = letture.accoda("rete_windows", request.user)
        except ImportError:
            from django_q.tasks import async_task

            async_task("assets.tasks.run_rete_windows_sync")
            ok, testo = True, "Lettura in coda."
        (messages.success if ok else messages.error)(request, f"{testo} L'esito compare in cima a questa pagina.")


@login_required
def rete_indirizzi(request: HttpRequest) -> HttpResponse:
    from .models import AmbitoDhcp
    from .views import _assets_shell_context

    puo_configurare = _puo_configurare(request)
    if request.method == "POST":
        if not puo_configurare:
            messages.error(request, "Solo gli amministratori del modulo Asset possono configurare i server DHCP e DNS.")
        else:
            _azione(request)
        return redirect(reverse("assets:rete_indirizzi") + "#config-rete")

    codice = request.GET.get("f") or "tutti"
    codice = codice if codice in dict(rete_windows.FILTRI) else "tutti"
    q = (request.GET.get("q") or "").strip()[:100]
    ambito_id = request.GET.get("ambito") or ""
    ambito_id = int(ambito_id) if ambito_id.isdigit() and AmbitoDhcp.objects.filter(pk=int(ambito_id)).exists() else None
    data = rete_windows.pagina(codice, q, ambito_id)
    return render(request, "assets/pages/rete_indirizzi.html", {
        **_assets_shell_context(request, search_placeholder="Cerca IP, MAC o nome"),
        "page_title": "Indirizzi IP",
        **data,
        "q": q,
        "filter_code": codice,
        "ambito_id": ambito_id,
        "puo_configurare": puo_configurare,
    })
