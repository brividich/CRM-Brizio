"""Indirizzi IP dal DHCP e dal DNS di Windows Server (``/assets/rete/indirizzi/``), in sola lettura.

I dati li scrive lo schedule ``rete_windows_sync`` (``services.rete_windows``); la
pagina filtra e mostra. Il collegamento di un indirizzo a un asset si conferma dalla
riconciliazione dispositivi IT, come per SNMP, SOC e Intune.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .services import rete_windows


@login_required
def rete_indirizzi(request: HttpRequest) -> HttpResponse:
    from .models import AmbitoDhcp
    from .views import _assets_shell_context

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
    })
