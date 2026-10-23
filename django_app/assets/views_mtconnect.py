"""Macchine collegate via MTConnect (``/assets/work-machines/mtconnect/``): elenco, prova, collegamento.

La pagina si apre con il permesso del binding ACL (migrazione ``assets 0148``); creare,
modificare, sospendere o togliere il collegamento di una macchina richiede il permesso di
modificare quell'asset. La «Prova» legge ``/probe`` e ``/current`` dall'agent senza salvare.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.audit import log_action

from .services import mtconnect as svc


def _macchine():
    from .models import Asset

    return (Asset.objects.filter(work_machine__isnull=False).exclude(status=Asset.STATUS_RETIRED)
            .select_related("work_machine").order_by("-work_machine__cnc_controlled", "name", "asset_tag"))


def _contatore(asset, tipo):
    return asset.meters.filter(meter_type=tipo).order_by("id").first()


def _salva(request: HttpRequest) -> None:
    from .models import AssetMeter, CollegamentoMTConnect
    from .views import AUDIT_OGGETTO_ASSET, _can_edit_asset

    asset_id = request.POST.get("asset") or ""
    asset = _macchine().filter(pk=int(asset_id)).first() if asset_id.isdigit() else None
    if asset is None:
        messages.error(request, "Scegli una macchina dell'elenco.")
        return
    if not _can_edit_asset(request, asset.pk):
        messages.error(request, "Per collegare questa macchina serve il permesso di modificarla.")
        return
    dispositivo = (request.POST.get("dispositivo") or "").strip()[:120]
    try:
        url = svc.valida_url(request.POST.get("url_agent") or "")
        svc._percorso(dispositivo, "current")
    except svc.MTConnectError as exc:
        messages.error(request, str(exc))
        return
    coll = CollegamentoMTConnect.objects.filter(asset=asset).first() or CollegamentoMTConnect(asset=asset)
    if coll.pk and coll.fonte == CollegamentoMTConnect.FONTE_COLLECTOR and coll.attivo:
        messages.error(request, f"{asset.name} è già letta dal collector OPC UA: sospendi quel collegamento prima di usare un agent MTConnect.")
        return
    coll.fonte = CollegamentoMTConnect.FONTE_MTCONNECT
    nuovo = coll.pk is None
    if coll.url_agent != url or coll.dispositivo != dispositivo:
        # Agent diverso: i valori grezzi del vecchio non sono confrontabili con il nuovo.
        coll.ore_grezzo = coll.pezzi_grezzo = None
        coll.sospesi = {}
    coll.url_agent, coll.dispositivo = url, dispositivo
    coll.contatore_ore = _contatore(asset, AssetMeter.METER_HOURS) if request.POST.get("usa_ore") else None
    coll.contatore_pezzi = _contatore(asset, AssetMeter.METER_CYCLES) if request.POST.get("usa_pezzi") else None
    coll.attivo = True
    coll.save()
    log_action(request, "mtconnect_collegamento", "assets",
               {"asset_id": asset.pk, "asset_tag": asset.asset_tag, "url_agent": url, "dispositivo": dispositivo, "nuovo": nuovo},
               oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
    mancano = [nome for chiesto, meter, nome in (
        (request.POST.get("usa_ore"), coll.contatore_ore, "Ore"), (request.POST.get("usa_pezzi"), coll.contatore_pezzi, "Cicli"),
    ) if chiesto and meter is None]
    messages.success(request, f"{asset.name} collegata: lo stato arriva entro 2 minuti.")
    if mancano:
        messages.warning(request, f"L'asset non ha un contatore {' né '.join(mancano)}: crealo dalla scheda della macchina "
                                  "(Contatori) e salva di nuovo il collegamento.")


def _azione_su(request: HttpRequest, azione: str) -> None:
    from .models import CollegamentoMTConnect
    from .views import AUDIT_OGGETTO_ASSET, _can_edit_asset

    pk = request.POST.get("collegamento") or ""
    coll = CollegamentoMTConnect.objects.filter(pk=int(pk)).select_related("asset").first() if pk.isdigit() else None
    if coll is None or not _can_edit_asset(request, coll.asset_id):
        messages.error(request, "Collegamento non trovato o permesso mancante.")
        return
    nome = coll.asset.name
    if azione == "elimina":
        coll.delete()
        messages.success(request, f"Collegamento di {nome} tolto (contatori e storico dell'asset restano).")
    else:
        coll.attivo = azione == "riattiva"
        coll.save(update_fields=["attivo", "aggiornato_il"])
        messages.success(request, f"{nome}: lettura {'riattivata' if coll.attivo else 'sospesa'}.")
    log_action(request, f"mtconnect_{azione}", "assets", {"asset_id": coll.asset_id, "asset_tag": coll.asset.asset_tag},
               oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=coll.asset_id)


def _prova(request: HttpRequest) -> dict:
    from .views import _can_edit_asset

    # La prova contatta un indirizzo della rete interna: solo chi può collegare quella macchina.
    asset_id = request.POST.get("asset") or ""
    asset = _macchine().filter(pk=int(asset_id)).first() if asset_id.isdigit() else None
    if asset is None or not _can_edit_asset(request, asset.pk):
        return {"ok": False, "errore": "Scegli prima la macchina: la prova la può fare chi ha il permesso di modificarla."}
    url = request.POST.get("url_agent") or ""
    dispositivo = (request.POST.get("dispositivo") or "").strip()[:120]
    try:
        dispositivi = svc.leggi_probe(svc.scarica(url, "", "probe"))
        dati = svc.leggi_current(svc.scarica(url, dispositivo), dispositivo)
    except svc.MTConnectError as exc:
        return {"ok": False, "errore": str(exc)}
    stato = svc.stato_da(dati)
    return {"ok": True, "dispositivi": dispositivi, "dati": dati, "stato": stato, "stato_label": svc.STATO_ETICHETTE[stato]}


@login_required
def mtconnect_collegamenti(request: HttpRequest) -> HttpResponse:
    from .models import CollegamentoMTConnect
    from .views import _assets_shell_context, _can_edit_asset

    prova = None
    form = {"asset": "", "url_agent": "", "dispositivo": "", "usa_ore": True, "usa_pezzi": True}
    if request.method == "POST":
        azione = request.POST.get("azione") or ""
        if azione == "prova":
            prova = _prova(request)
            form = {k: request.POST.get(k, "") for k in ("asset", "url_agent", "dispositivo")}
            form.update(usa_ore=bool(request.POST.get("usa_ore")), usa_pezzi=bool(request.POST.get("usa_pezzi")))
        else:
            if azione == "salva":
                _salva(request)
            elif azione in ("elimina", "sospendi", "riattiva"):
                _azione_su(request, azione)
            return redirect(reverse("assets:mtconnect_collegamenti"))
    modifica = request.GET.get("modifica") or ""
    if modifica.isdigit() and prova is None:
        coll = CollegamentoMTConnect.objects.filter(pk=int(modifica)).first()
        if coll:
            form = {"asset": str(coll.asset_id), "url_agent": coll.url_agent, "dispositivo": coll.dispositivo,
                    "usa_ore": coll.contatore_ore_id is not None, "usa_pezzi": coll.contatore_pezzi_id is not None}
    righe = list(CollegamentoMTConnect.objects.select_related("asset", "contatore_ore", "contatore_pezzi").order_by("asset__name"))
    for r in righe:
        r.stato_label = svc.STATO_ETICHETTE.get(r.stato, r.stato)
        r.attuale = svc.attuale(r)
        r.ore_oggi = svc.ore_in_lavoro_oggi(r)
        r.puo_modificare = _can_edit_asset(request, r.asset_id)
    return render(request, "assets/pages/mtconnect_collegamenti.html", {
        **_assets_shell_context(request),
        "page_title": "Macchine collegate",
        "righe": righe,
        "macchine": _macchine(),
        "form": form,
        "prova": prova,
    })
