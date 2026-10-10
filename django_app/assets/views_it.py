"""Riconciliazione dispositivi IT: proposte di collegamento SNMP, MFC e SOC in una pagina.

Le proposte vengono dall'abbinatore unico (``services.identity_match``). Ogni riga
si conferma solo con il permesso del modulo che possiede il dispositivo: pagina di
modifica della centrale SNMP per dispositivi e MFC, configurazione del Security
Center per i dispositivi SOC. Alla conferma la proposta viene ricalcolata: si
collega solo se punta ancora allo stesso asset.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from core.audit import log_action

from .services.identity_match import AMBIGUOUS_REASONS, match_hub_asset
from .services.it_monitoring import can_view_monitoring

ROW_LIMIT = 300


def _rows(request: HttpRequest) -> tuple[list[dict], dict[str, int]]:
    from contatori.models import DispositivoSNMP, Macchina
    from security.models import SecurityAsset
    from security.services.asset_signals import suggest_hub_asset
    from security.services.configuration import can_manage_security_config

    rows: list[dict] = []
    counts = {"proposte": 0, "ambigue": 0, "senza": 0}

    def add(kind, obj, label, ident, asset, reason, edit_url):
        if asset is not None:
            counts["proposte"] += 1
        elif reason in AMBIGUOUS_REASONS:
            counts["ambigue"] += 1
        else:
            counts["senza"] += 1
        rows.append({
            "key": f"{kind}:{obj.pk}:{asset.pk if asset else 0}",
            "kind": kind,
            "module": {"snmp": "Centrale SNMP", "mfc": "MFC", "soc": "SOC"}[kind],
            "label": label,
            "ident": ident,
            "asset": asset,
            "reason": reason,
            "url": edit_url,
        })

    for device in DispositivoSNMP.objects.filter(asset__isnull=True).order_by("nome")[:ROW_LIMIT]:
        url = reverse("contatori:snmp_dispositivo_edit", args=[device.pk])
        if not can_view_monitoring(request, url):
            continue
        asset, reason = match_hub_asset(serial=device.matricola, ip=device.host, hostname=device.sys_name)
        add("snmp", device, device.nome, " · ".join(x for x in (device.host, device.matricola) if x), asset, reason, url)
    for machine in Macchina.objects.filter(asset__isnull=True).order_by("reparto")[:ROW_LIMIT]:
        url = reverse("contatori:macchina_edit", args=[machine.pk])
        if not can_view_monitoring(request, url):
            continue
        asset, reason = match_hub_asset(serial=machine.matricola, ip=machine.host or "")
        add("mfc", machine, f"MFC {machine.reparto}", " · ".join(x for x in (machine.host or "", machine.matricola) if x), asset, reason, url)
    if can_manage_security_config(request.user):
        for device in SecurityAsset.objects.filter(hub_asset__isnull=True).select_related("source").order_by("hostname")[:ROW_LIMIT]:
            asset, reason = suggest_hub_asset(device)
            add("soc", device, device.hostname, device.ip_address or (device.source.name if device.source_id else ""), asset, reason,
                reverse("security:assets"))
    rows.sort(key=lambda row: (row["asset"] is None, row["module"], row["label"].lower()))
    return rows, counts


def _link(request: HttpRequest, key: str) -> str | None:
    """Collega una riga ``tipo:id:asset``; ritorna il nome del dispositivo o ``None``."""
    from contatori.models import DispositivoSNMP, Macchina
    from security.models import SecurityAsset
    from security.services.asset_signals import link, suggest_hub_asset
    from security.services.configuration import can_manage_security_config

    from .views import AUDIT_OGGETTO_ASSET

    try:
        kind, obj_id, asset_id = key.split(":")
        obj_id, asset_id = int(obj_id), int(asset_id)
    except ValueError:
        return None
    if kind == "soc":
        device = SecurityAsset.objects.filter(pk=obj_id, hub_asset__isnull=True).first()
        if device is None or not can_manage_security_config(request.user):
            return None
        asset, _reason = suggest_hub_asset(device)
        if asset is None or asset.pk != asset_id:
            return None
        link(device, asset, actor=request.user, request=request)
        return device.hostname
    model, url_name = {"snmp": (DispositivoSNMP, "contatori:snmp_dispositivo_edit"),
                       "mfc": (Macchina, "contatori:macchina_edit")}.get(kind, (None, None))
    if model is None:
        return None
    obj = model.objects.filter(pk=obj_id, asset__isnull=True).first()
    if obj is None or not can_view_monitoring(request, reverse(url_name, args=[obj.pk])):
        return None
    if kind == "snmp":
        asset, _reason = match_hub_asset(serial=obj.matricola, ip=obj.host, hostname=obj.sys_name)
    else:
        asset, _reason = match_hub_asset(serial=obj.matricola, ip=obj.host or "")
    if asset is None or asset.pk != asset_id:
        return None
    obj.asset = asset
    obj.save(update_fields=["asset", "aggiornato_il"] if kind == "snmp" else ["asset"])
    log_action(request, "it_reconcile_link", "assets",
               {"module": kind, "device_id": obj.pk, "asset_id": asset.pk, "asset_tag": asset.asset_tag},
               oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
    return str(obj)


@login_required
def it_reconciliation(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        keys = request.POST.getlist("row")
        linked = [name for name in (_link(request, key) for key in keys[:ROW_LIMIT]) if name]
        skipped = len(keys) - len(linked)
        if linked:
            messages.success(request, f"{len(linked)} dispositivi collegati.")
        if skipped:
            messages.warning(request, f"{skipped} righe non collegate: proposta cambiata o permesso mancante.")
        # «Collega» dalla scheda asset: si torna alla scheda (solo URL interni).
        target = request.POST.get("next") or ""
        if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(target)
        return redirect("assets:it_reconciliation")
    rows, counts = _rows(request)
    view = request.GET.get("vista") or "proposte"
    shown = [r for r in rows if (r["asset"] is not None) == (view == "proposte")]
    from .views import _assets_shell_context

    return render(request, "assets/pages/it_reconciliation.html", {
        **_assets_shell_context(request),
        "page_title": "Riconciliazione dispositivi IT",
        "rows": shown,
        "counts": counts,
        "view": view,
    })
