"""Indirizzi IP dal DHCP e dal DNS di Windows Server (``/assets/rete/indirizzi/``).

I dati li scrive lo schedule ``rete_windows_sync`` (``services.rete_windows``); la
pagina filtra, incrocia con switch, WatchGuard e Intune e mostra. La stessa vista
compare nel SOC (``/soc/dispositivi/rete/``, ``security.views_work.rete_indirizzi``):
il contesto lo prepara :func:`contesto_pagina`, le azioni sulla riga :func:`azione_riga`.

Azioni sulla riga: «Conferma» collega l'indirizzo all'asset proposto (la proposta si
ricalcola: si collega solo se punta ancora allo stesso asset), «Scollega» lo stacca.
Entrambe con il permesso di modifica dell'asset, come la riconciliazione dispositivi IT.
«Crea asset» apre il modulo del nuovo asset già compilato (``?da_rete=<id>``).
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


def _acl_consente(request, path: str) -> bool:
    from core.middleware import acl_allows_path

    try:
        return bool(acl_allows_path(path, django_user=request.user, request=request))
    except Exception:  # noqa: BLE001 - nel dubbio il pulsante non c'è (il server decide comunque)
        return False


def _puo_creare_asset(request) -> bool:
    return _acl_consente(request, reverse("assets:asset_create"))


def _puo_collegare(request) -> bool:
    """Pulsanti Conferma/Scollega: chi può modificare gli asset (l'azione ricontrolla l'asset preciso)."""
    from .models import Asset

    primo = Asset.objects.order_by("pk").values_list("pk", flat=True).first()
    return primo is not None and _acl_consente(request, reverse("assets:asset_edit", args=[primo]))


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


def azione_riga(request: HttpRequest) -> bool:
    """«Conferma» o «Scollega» su un indirizzo. Ritorna True se il POST era un'azione di riga."""
    from .models import IndirizzoRete
    from .views import AUDIT_OGGETTO_ASSET, _can_edit_asset

    azione = request.POST.get("azione") or ""
    if azione not in {"collega", "scollega"}:
        return False
    riga_id = request.POST.get("riga") or ""
    riga = IndirizzoRete.objects.select_related("asset").filter(pk=int(riga_id)).first() if riga_id.isdigit() else None
    if riga is None:
        messages.error(request, "Indirizzo non trovato: ricarica la pagina.")
        return True
    if azione == "collega":
        asset, _motivo = rete_windows.proponi(riga) if riga.asset_id is None else (None, "")
        if asset is None or str(asset.pk) != (request.POST.get("asset") or ""):
            messages.warning(request, f"{riga.ip}: la proposta è cambiata, ricarica la pagina.")
            return True
        if not _can_edit_asset(request, asset.pk):
            messages.error(request, f"Non hai il permesso di modificare l'asset {asset.asset_tag}.")
            return True
        riga.asset, riga.asset_proposto, riga.motivo_proposta = asset, None, ""
        riga.save(update_fields=["asset", "asset_proposto", "motivo_proposta", "aggiornato_il"])
        log_action(request, "rete_indirizzo_collegato", "assets",
                   {"ip": riga.ip, "mac": riga.mac, "asset_id": asset.pk, "asset_tag": asset.asset_tag},
                   oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
        messages.success(request, f"{riga.ip} collegato a {asset.asset_tag}.")
        return True
    asset = riga.asset
    if asset is None:
        return True
    if not _can_edit_asset(request, asset.pk):
        messages.error(request, f"Non hai il permesso di modificare l'asset {asset.asset_tag}.")
        return True
    riga.asset = None
    riga.save(update_fields=["asset", "aggiornato_il"])
    log_action(request, "rete_indirizzo_scollegato", "assets",
               {"ip": riga.ip, "mac": riga.mac, "asset_id": asset.pk, "asset_tag": asset.asset_tag},
               oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
    messages.success(request, f"{riga.ip} scollegato da {asset.asset_tag}: la proposta torna al prossimo giro.")
    return True


def contesto_pagina(request: HttpRequest) -> dict:
    """Filtri della richiesta e dati della pagina: uguali per Asset e SOC."""
    from .models import AmbitoDhcp

    codice = request.GET.get("f") or "tutti"
    codice = codice if codice in dict(rete_windows.FILTRI) else "tutti"
    q = (request.GET.get("q") or "").strip()[:100]
    ambito_id = request.GET.get("ambito") or ""
    ambito_id = int(ambito_id) if ambito_id.isdigit() and AmbitoDhcp.objects.filter(pk=int(ambito_id)).exists() else None
    return {
        **rete_windows.pagina(codice, q, ambito_id),
        "q": q,
        "filter_code": codice,
        "ambito_id": ambito_id,
        "puo_creare_asset": _puo_creare_asset(request),
        "puo_collegare": _puo_collegare(request),
    }


def export_excel(request: HttpRequest, data: dict) -> HttpResponse:
    from django.utils import timezone

    from core.excel_export import make_xlsx_response

    filtro = dict(rete_windows.FILTRI).get(data["filter_code"], "Tutti")
    etichetta = filtro + (f" · «{data['q']}»" if data["q"] else "")
    log_action(request, "rete_indirizzi_export", "assets", {"filtro": data["filter_code"], "righe": len(data["righe"])})
    return make_xlsx_response(
        filename=f"indirizzi_ip_{timezone.localdate():%Y%m%d}.xlsx", columns=rete_windows.COLONNE_EXCEL,
        rows=rete_windows.righe_excel(data["righe"]), sheet_title="Indirizzi IP", title="Indirizzi IP",
        subtitle="DHCP e DNS di Windows Server, con switch, antivirus e asset del registro", filters_label=etichetta,
    )


@login_required
def rete_indirizzi(request: HttpRequest) -> HttpResponse:
    from .views import _assets_shell_context

    puo_configurare = _puo_configurare(request)
    if request.method == "POST":
        if azione_riga(request):
            return redirect(request.get_full_path())
        if not puo_configurare:
            messages.error(request, "Solo gli amministratori del modulo Asset possono configurare i server DHCP e DNS.")
        else:
            _azione(request)
        return redirect(reverse("assets:rete_indirizzi") + "#config-rete")

    data = contesto_pagina(request)
    if request.GET.get("export") == "xlsx":
        return export_excel(request, data)
    return render(request, "assets/pages/rete_indirizzi.html", {
        **_assets_shell_context(request, search_placeholder="Cerca IP, MAC o nome"),
        "page_title": "Indirizzi IP",
        **data,
        "puo_configurare": puo_configurare,
        "guida_url": reverse("assets:guida") + "#rete-indirizzi",
        "soc_url": _url_soc(request),
    })


def _url_soc(request) -> str:
    """Link alla stessa vista nel SOC, solo per chi vede il Security Center."""
    try:
        from security.permissions import can_view_security_center

        return reverse("security:rete_indirizzi") if can_view_security_center(request.user) else ""
    except Exception:  # noqa: BLE001 - SOC non installato
        return ""
