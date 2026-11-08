"""Riconciliazione dispositivi IT: proposte di collegamento SNMP, MFC, SOC, Intune e rete (DHCP) in una pagina.

Le proposte vengono dall'abbinatore unico (``services.identity_match``). Ogni riga
si conferma solo con il permesso del modulo che possiede il dispositivo: pagina di
modifica della centrale SNMP per dispositivi e MFC, configurazione del Security
Center per i dispositivi SOC, modifica dell'asset di destinazione per i PC di
Microsoft Intune, per gli indirizzi DHCP e per i PC dell'inventario software. Alla conferma la proposta viene ricalcolata: si
collega solo se punta ancora allo stesso asset.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from core.audit import log_action

from .models import Asset, AssetSenzaInventario
from .services.identity_match import AMBIGUOUS_REASONS, match_hub_asset
from .services.it_monitoring import can_view_monitoring

ROW_LIMIT = 300


@dataclass
class _Riga:
    pk: int


# PC e server: dove ci si aspetta un inventario software.
TIPI_CON_INVENTARIO = (Asset.TYPE_PC, Asset.TYPE_NOTEBOOK, Asset.TYPE_SERVER)


def _senza_inventario() -> tuple[list[Asset], list[AssetSenzaInventario]]:
    """(da spiegare, spiegati): PC e server senza software rilevato. I dismessi non chiedono niente."""
    from security.models import SoftwareInstallation

    con_software = set(SoftwareInstallation.objects.filter(still_detected=True, hub_asset__isnull=False).values_list("hub_asset_id", flat=True).distinct())
    spiegati = {r.asset_id: r for r in AssetSenzaInventario.objects.select_related("asset")}
    da_spiegare, gia = [], []
    for asset in Asset.objects.filter(asset_type__in=TIPI_CON_INVENTARIO).exclude(status=Asset.STATUS_RETIRED).order_by("name"):
        if asset.pk in con_software:
            continue
        if asset.pk in spiegati:
            gia.append(spiegati[asset.pk])
        else:
            da_spiegare.append(asset)
    return da_spiegare, gia


def _azione_senza_inventario(request: HttpRequest) -> HttpResponse:
    from .views import AUDIT_OGGETTO_ASSET, _can_edit_asset

    url = f"{reverse('assets:it_reconciliation')}?vista=inventario"
    valore = request.POST.get("asset") or ""
    asset = Asset.objects.filter(pk=valore if valore.isdigit() else 0).first()
    if asset is None or not _can_edit_asset(request, asset.pk):
        messages.error(request, "Asset non trovato o permesso mancante.")
        return redirect(url)
    if request.POST.get("azione") == "togli_motivo":
        AssetSenzaInventario.objects.filter(asset=asset).delete()
        log_action(request, "it_senza_inventario_tolto", "assets", {"asset_id": asset.pk}, oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
        messages.success(request, f"«{asset.name}» torna tra quelli da spiegare.")
        return redirect(url)
    motivo = request.POST.get("motivo") or ""
    if motivo not in dict(AssetSenzaInventario.MOTIVO_CHOICES):
        messages.error(request, "Scegli il motivo.")
        return redirect(url)
    AssetSenzaInventario.objects.update_or_create(asset=asset, defaults={
        "motivo": motivo, "nota": (request.POST.get("nota") or "").strip()[:255], "creato_da": request.user})
    log_action(request, "it_senza_inventario", "assets", {"asset_id": asset.pk, "motivo": motivo}, oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
    messages.success(request, f"«{asset.name}» segnato: {dict(AssetSenzaInventario.MOTIVO_CHOICES)[motivo]}.")
    return redirect(url)


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
            "module": {"snmp": "Centrale SNMP", "mfc": "MFC", "soc": "SOC", "intune": "Intune", "rete": "Rete (DHCP)", "inv": "Inventario software"}[kind],
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
    from .models import DispositivoIntune

    for device in DispositivoIntune.objects.filter(asset__isnull=True, presente=True).order_by("nome")[:ROW_LIMIT]:
        asset, reason = match_hub_asset(serial=device.seriale, hostname=device.nome)
        ident = " · ".join(x for x in (device.seriale, device.utente_nome or device.utente_upn) if x)
        add("intune", device, device.nome or device.seriale, ident, asset, reason,
            reverse("assets:asset_view", args=[asset.pk]) if asset else reverse("assets:it_reconciliation"))
    from django.db.models import Min, Q

    from security.models import SoftwareInstallation

    # PC con software nell'inventario e nessun asset: una riga per PC, proposta dal nome.
    for riga in (SoftwareInstallation.objects.filter(still_detected=True, hub_asset__isnull=True).exclude(source_kind="snmp_firmware")
                 .values("host").annotate(primo=Min("id"), n=Count("id")).order_by("host")[:ROW_LIMIT]):
        asset, reason = match_hub_asset(hostname=riga["host"])
        add("inv", _Riga(riga["primo"]), riga["host"], f"{riga['n']} programmi rilevati", asset, reason,
            reverse("assets:asset_view", args=[asset.pk]) if asset else reverse("assets:it_reconciliation") + "?vista=senza")

    from .models import IndirizzoRete
    from .services.rete_windows import proponi

    # Lease DHCP con MAC, più gli IP fissi del DNS solo se il nome trova un asset: senza
    # proposta un record solo-DNS non dice a che dispositivo appartiene.
    for addr in (IndirizzoRete.objects.filter(asset__isnull=True)
                 .filter(Q(nel_dhcp=True) & ~Q(mac="") | Q(nel_dhcp=False, nel_dns=True, asset_proposto__isnull=False))
                 .order_by("ip")[:ROW_LIMIT]):
        asset, reason = proponi(addr)
        if asset is None and not addr.nel_dhcp:
            continue
        add("rete", addr, addr.nome or addr.ip, " · ".join(x for x in (addr.ip, addr.mac) if x), asset, reason,
            reverse("assets:asset_view", args=[asset.pk]) if asset else reverse("assets:rete_indirizzi") + "?f=non_censiti")
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
    if kind == "intune":
        from .models import DispositivoIntune
        from .services.intune import completa_asset
        from .views import _can_edit_asset

        device = DispositivoIntune.objects.filter(pk=obj_id, asset__isnull=True).first()
        if device is None:
            return None
        asset, _reason = match_hub_asset(serial=device.seriale, hostname=device.nome)
        if asset is None or asset.pk != asset_id or not _can_edit_asset(request, asset.pk):
            return None
        device.asset = asset
        device.save(update_fields=["asset", "aggiornato_il"])
        completa_asset(device)
        log_action(request, "it_reconcile_link", "assets",
                   {"module": "intune", "device_id": device.pk, "asset_id": asset.pk, "asset_tag": asset.asset_tag},
                   oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
        return str(device)
    if kind == "inv":
        from security.models import SecurityCveImpact, SoftwareInstallation

        from .views import _can_edit_asset

        riga = SoftwareInstallation.objects.filter(pk=obj_id, hub_asset__isnull=True).first()
        if riga is None:
            return None
        asset, _reason = match_hub_asset(hostname=riga.host)
        if asset is None or asset.pk != asset_id or not _can_edit_asset(request, asset.pk):
            return None
        SoftwareInstallation.objects.filter(host=riga.host, hub_asset__isnull=True).update(hub_asset=asset)
        SecurityCveImpact.objects.filter(host=riga.host, hub_asset__isnull=True).update(hub_asset=asset)
        log_action(request, "it_reconcile_link", "assets",
                   {"module": "inventario", "host": riga.host, "asset_id": asset.pk, "asset_tag": asset.asset_tag},
                   oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
        return riga.host
    if kind == "rete":
        from .models import IndirizzoRete
        from .services.rete_windows import proponi
        from .views import _can_edit_asset

        addr = IndirizzoRete.objects.filter(pk=obj_id, asset__isnull=True).first()
        if addr is None:
            return None
        asset, _reason = proponi(addr)
        if asset is None or asset.pk != asset_id or not _can_edit_asset(request, asset.pk):
            return None
        addr.asset = asset
        addr.save(update_fields=["asset", "aggiornato_il"])
        log_action(request, "it_reconcile_link", "assets",
                   {"module": "rete", "device_id": addr.pk, "asset_id": asset.pk, "asset_tag": asset.asset_tag, "ip": addr.ip},
                   oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
        return str(addr)
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
        if request.POST.get("azione") in {"motivo", "togli_motivo"}:
            return _azione_senza_inventario(request)
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
    da_spiegare, spiegati = _senza_inventario()
    from .services import hardware_vita
    from .views import _assets_shell_context

    fine_vita = hardware_vita.elenco()
    fine_vita_conteggi = hardware_vita.conteggi(fine_vita)
    giudizio = request.GET.get("giudizio") or ""
    fine_vita_mostrati = hardware_vita.filtra(fine_vita, giudizio)
    for r in fine_vita_mostrati:
        r["eta_pct"] = hardware_vita.eta_percento(r["eta"])
    return render(request, "assets/pages/it_reconciliation.html", {
        **_assets_shell_context(request),
        "page_title": "Riconciliazione dispositivi IT",
        "rows": shown,
        "counts": counts,
        "view": view,
        "da_spiegare": da_spiegare,
        "spiegati": spiegati,
        "motivi": AssetSenzaInventario.MOTIVO_CHOICES,
        "fine_vita": fine_vita_mostrati,
        "fine_vita_totale": len(fine_vita),
        "fine_vita_giudizio": giudizio if giudizio in hardware_vita.ETICHETTE else "",
        "fine_vita_conteggi": fine_vita_conteggi,
        "fine_vita_soglie": {"sostituzione": hardware_vita.ETA_SOSTITUZIONE, "pianifica": hardware_vita.ETA_PIANIFICA,
                             "ram": hardware_vita.RAM_MINIMA_GB, "disco": hardware_vita.DISCO_PIENO_PCT, "guasti": hardware_vita.GUASTI_SOGLIA,
                             "scala": hardware_vita.ETA_SCALA,
                             "segno_pianifica": round(100 * hardware_vita.ETA_PIANIFICA / hardware_vita.ETA_SCALA),
                             "segno_sostituzione": round(100 * hardware_vita.ETA_SOSTITUZIONE / hardware_vita.ETA_SCALA)},
    })
