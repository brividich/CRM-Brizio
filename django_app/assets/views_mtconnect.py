"""Macchine collegate (``/assets/work-machines/mtconnect/``): collector OPC UA, agent MTConnect, token.

La pagina si apre con il permesso del binding ACL (migrazione ``assets 0148``). Collegare,
modificare, sospendere o togliere una macchina richiede il permesso di modificare quell'asset.
Il riquadro **Collector** (token, IP ammessi, macchine consentite) è solo per gli amministratori
del modulo Asset: il token nuovo si mostra una volta sola nella risposta della pagina, mai in
un messaggio salvato in sessione. La «Prova» MTConnect legge ``/probe`` e ``/current`` senza salvare.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.acl import user_can_modulo_action
from core.audit import log_action

from .services import collector_cnc
from .services import mtconnect as svc


def _macchine():
    from .models import Asset

    return (Asset.objects.filter(work_machine__isnull=False).exclude(status=Asset.STATUS_RETIRED)
            .select_related("work_machine").order_by("-work_machine__cnc_controlled", "name", "asset_tag"))


def _contatore(asset, tipo):
    return asset.meters.filter(meter_type=tipo).order_by("id").first()


def _puo_amministrare(request) -> bool:
    return bool(getattr(request.user, "is_superuser", False)) or user_can_modulo_action(request, "assets", "admin_assets")


# --- macchine ----------------------------------------------------------------------------------

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
    coll = CollegamentoMTConnect.objects.filter(asset=asset).first() or CollegamentoMTConnect(asset=asset)
    nuovo = coll.pk is None
    fonte = request.POST.get("fonte") or CollegamentoMTConnect.FONTE_COLLECTOR
    if fonte == CollegamentoMTConnect.FONTE_COLLECTOR:
        host = (request.POST.get("opcua_host") or "").strip()
        porta = (request.POST.get("opcua_porta") or "4840").strip()
        codice = (request.POST.get("codice") or "").strip()
        errori = collector_cnc.valida_macchina(host, porta, codice)
        if errori:
            messages.error(request, " ".join(errori))
            return
        coll.fonte = fonte
        coll.url_agent, coll.dispositivo = "", ""
        coll.opcua_host, coll.opcua_porta, coll.codice = host, int(porta), codice
        coll.opcua_utente = (request.POST.get("opcua_utente") or "").strip()[:120]
        password = request.POST.get("opcua_password") or ""
        if request.POST.get("togli_password"):
            coll.opcua_password = ""
        elif password:
            coll.opcua_password = collector_cnc.cifra(password[:200])
        coll.contatore_ore = coll.contatore_pezzi = None  # i contatori li manda il collector, per asset_tag
        dettaglio = {"fonte": fonte, "opcua_host": host, "opcua_porta": int(porta), "codice": codice}
        avviso = "il collector la legge al prossimo aggiornamento dell'elenco (entro 5 minuti)."
    else:
        dispositivo = (request.POST.get("dispositivo") or "").strip()[:120]
        try:
            url = svc.valida_url(request.POST.get("url_agent") or "")
            svc._percorso(dispositivo, "current")
        except svc.MTConnectError as exc:
            messages.error(request, str(exc))
            return
        coll.fonte = CollegamentoMTConnect.FONTE_MTCONNECT
        if coll.url_agent != url or coll.dispositivo != dispositivo:
            # Agent diverso: i valori grezzi del vecchio non sono confrontabili con il nuovo.
            coll.ore_grezzo = coll.pezzi_grezzo = None
            coll.sospesi = {}
        coll.url_agent, coll.dispositivo = url, dispositivo
        coll.contatore_ore = _contatore(asset, AssetMeter.METER_HOURS) if request.POST.get("usa_contatori") else None
        coll.contatore_pezzi = _contatore(asset, AssetMeter.METER_CYCLES) if request.POST.get("usa_contatori") else None
        dettaglio = {"fonte": coll.fonte, "url_agent": url, "dispositivo": dispositivo}
        avviso = "lo stato arriva entro 2 minuti."
    coll.attivo = True
    coll.save()
    creati = collector_cnc.crea_contatori(asset) if request.POST.get("crea_contatori") else []
    if creati and coll.fonte == CollegamentoMTConnect.FONTE_MTCONNECT and request.POST.get("usa_contatori"):
        coll.contatore_ore = _contatore(asset, AssetMeter.METER_HOURS)
        coll.contatore_pezzi = _contatore(asset, AssetMeter.METER_CYCLES)
        coll.save(update_fields=["contatore_ore", "contatore_pezzi", "aggiornato_il"])
    log_action(request, "mtconnect_collegamento", "assets",
               {"asset_id": asset.pk, "asset_tag": asset.asset_tag, "nuovo": nuovo, "contatori_creati": creati, **dettaglio},
               oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.pk)
    messages.success(request, f"{asset.name} salvata: {avviso}" + (f" Contatori creati: {', '.join(creati)}." if creati else ""))


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
    elif azione == "contatori":
        creati = collector_cnc.crea_contatori(coll.asset)
        messages.success(request, f"{nome}: contatori creati: {', '.join(creati)}." if creati else f"{nome}: i contatori Ore e Cicli c'erano già.")
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


# --- collector (token, rete, macchine consentite) ----------------------------------------------

def _azione_collector(request: HttpRequest, azione: str) -> dict | None:
    """Ritorna ``{"nome", "token"}`` quando c'è un token nuovo da mostrare una volta sola."""
    from .models import Asset, CollegamentoMTConnect, MeterIngestClient

    if azione == "collector_modalita":
        valore = request.POST.get("modalita") or ""
        if valore not in collector_cnc.MODALITA:
            messages.error(request, "Scegli dove gira il collector.")
            return None
        collector_cnc.imposta_modalita(valore)
        log_action(request, "collector_modalita", "assets", {"modalita": valore})
        messages.success(request, f"Collector: {collector_cnc.MODALITA[valore].lower()}. Il cambio vale entro 5 minuti "
                                  "(il collector rilegge l'elenco delle macchine).")
        return None
    if azione == "collector_crea":
        nome = (request.POST.get("nome") or "").strip()[:120]
        if not nome or MeterIngestClient.objects.filter(name__iexact=nome).exists():
            messages.error(request, "Dai al collector un nome che non sia già usato (es. «Collector CNC officina»).")
            return None
        client = MeterIngestClient(name=nome, created_by=request.user if request.user.is_authenticated else None)
    else:
        pk = request.POST.get("collector") or ""
        client = MeterIngestClient.objects.filter(pk=int(pk)).first() if pk.isdigit() else None
        if client is None:
            messages.error(request, "Collector non trovato.")
            return None
    token = None
    if azione in ("collector_crea", "collector_salva"):
        voci, errori = collector_cnc.valida_ips(request.POST.get("ips", ""))
        if errori:
            messages.error(request, " ".join(errori))
            return None
        client.allowed_ips = ", ".join(voci)
        client.all_meter_assets = request.POST.get("tutte") == "on"
        if azione == "collector_crea":
            token = collector_cnc.nuovo_token(client)
        client.save()
        if not client.all_meter_assets:
            ids = [int(v) for v in request.POST.getlist("macchine") if v.isdigit()]
            consentite = CollegamentoMTConnect.objects.filter(asset_id__in=ids).values_list("asset_id", flat=True)
            client.allowed_assets.set(Asset.objects.filter(pk__in=list(consentite)))
    elif azione == "collector_token":
        token = collector_cnc.nuovo_token(client)
        client.save(update_fields=["token_hash"])
    elif azione in ("collector_disattiva", "collector_riattiva"):
        client.is_active = azione == "collector_riattiva"
        client.save(update_fields=["is_active"])
    log_action(request, azione, "assets", {"collector": client.name, "ips": client.allowed_ips,
                                           "tutte": client.all_meter_assets, "attivo": client.is_active})
    if token:
        return {"nome": client.name, "token": token}
    messages.success(request, f"Collector «{client.name}» aggiornato.")
    return None


def _collector_ctx():
    from .models import MeterIngestClient

    righe = list(MeterIngestClient.objects.prefetch_related("allowed_assets").order_by("name"))
    for c in righe:
        c.consentite_ids = {a.pk for a in c.allowed_assets.all()}
    return righe


# --- pagina ------------------------------------------------------------------------------------

@login_required
def mtconnect_collegamenti(request: HttpRequest) -> HttpResponse:
    from .models import AssetMeter, CollegamentoMTConnect, MeterIngestClient
    from .views import _assets_shell_context, _can_edit_asset

    puo_amministrare = _puo_amministrare(request)
    prova = token_nuovo = None
    form = {"fonte": CollegamentoMTConnect.FONTE_COLLECTOR, "asset": "", "url_agent": "", "dispositivo": "",
            "opcua_host": "", "opcua_porta": 4840, "codice": "", "opcua_utente": "", "ha_password": False}
    if request.method == "POST":
        azione = request.POST.get("azione") or ""
        if azione == "prova":
            prova = _prova(request)
            form.update({k: request.POST.get(k, "") for k in ("asset", "url_agent", "dispositivo")}, fonte="mtconnect")
        elif azione.startswith("collector_"):
            if not puo_amministrare:
                messages.error(request, "I collector li gestiscono gli amministratori del modulo Asset.")
                return redirect(reverse("assets:mtconnect_collegamenti"))
            token_nuovo = _azione_collector(request, azione)
            if token_nuovo is None:
                return redirect(reverse("assets:mtconnect_collegamenti") + "#collector")
        else:
            if azione == "salva":
                _salva(request)
            elif azione in ("elimina", "sospendi", "riattiva", "contatori"):
                _azione_su(request, azione)
            return redirect(reverse("assets:mtconnect_collegamenti"))
    modifica = request.GET.get("modifica") or ""
    if modifica.isdigit() and prova is None:
        coll = CollegamentoMTConnect.objects.filter(pk=int(modifica)).first()
        if coll:
            form = {"fonte": coll.fonte, "asset": str(coll.asset_id), "url_agent": coll.url_agent, "dispositivo": coll.dispositivo,
                    "opcua_host": coll.opcua_host, "opcua_porta": coll.opcua_porta, "codice": coll.codice,
                    "opcua_utente": coll.opcua_utente, "ha_password": bool(coll.opcua_password)}
    collector = _collector_ctx()
    attivi = [c for c in collector if c.is_active]
    righe = list(CollegamentoMTConnect.objects.select_related("asset", "contatore_ore", "contatore_pezzi").order_by("asset__name"))
    contatori = {}
    for asset_id, tipo in AssetMeter.objects.filter(asset_id__in=[r.asset_id for r in righe]).values_list("asset_id", "meter_type"):
        contatori.setdefault(asset_id, set()).add(tipo)
    for r in righe:
        r.stato_label = svc.STATO_ETICHETTE.get(r.stato, r.stato)
        r.attuale = svc.attuale(r)
        r.ore_oggi = svc.ore_in_lavoro_oggi(r)
        r.puo_modificare = _can_edit_asset(request, r.asset_id)
        r.nome_collector = collector_cnc.nome_macchina(r)
        r.mancano_contatori = not {AssetMeter.METER_HOURS, AssetMeter.METER_CYCLES} <= contatori.get(r.asset_id, set())
        r.coperta = r.fonte != CollegamentoMTConnect.FONTE_COLLECTOR or any(
            c.all_meter_assets or r.asset_id in c.consentite_ids for c in attivi)
    return render(request, "assets/pages/mtconnect_collegamenti.html", {
        **_assets_shell_context(request),
        "page_title": "Macchine collegate",
        "righe": righe,
        "macchine": _macchine(),
        "macchine_collector": [r for r in righe if r.fonte == CollegamentoMTConnect.FONTE_COLLECTOR],
        "form": form,
        "prova": prova,
        "puo_amministrare": puo_amministrare,
        "collector": collector if puo_amministrare else [],
        "token_nuovo": token_nuovo,
        "nessun_collector": not MeterIngestClient.objects.filter(is_active=True).exists(),
        "modalita": collector_cnc.modalita(),
        "modalita_scelte": collector_cnc.MODALITA,
        "battito": collector_cnc.battito(),
        "url_portale": request.build_absolute_uri("/").rstrip("/"),
    })
