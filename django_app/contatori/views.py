from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import LetturaForm, MacchinaForm, ImpostazioniSNMPForm
from .models import Macchina, LetturaContatori, ImpostazioniSNMP


def discovery(request):
    """Discovery SNMP di rete: trova le stampanti che rispondono e le abbina all'anagrafica.

    Serve soprattutto a scoprire un IP sbagliato: l'abbinamento e' sulla matricola
    (numero di serie letto dal dispositivo), non sull'IP.
    """
    from .snmp import SNMPError, scansiona_rete

    cfg = ImpostazioniSNMP.get_solo()
    rete = (request.POST.get("rete") or "").strip()
    community = (request.POST.get("community") or cfg.community).strip()
    version = request.POST.get("version") or cfg.version
    try:
        timeout = max(1, min(10, int(request.POST.get("timeout") or 2)))
    except ValueError:
        timeout = 2

    righe, errore, eseguita = None, "", False
    if request.method == "POST":
        eseguita = True
        try:
            trovati = scansiona_rete(rete, community=community, port=cfg.port,
                                     timeout=timeout, version=version)
            righe = services.abbina_discovery(trovati)
            if not righe:
                messages.warning(
                    request,
                    "Nessun dispositivo ha risposto. Attenzione: in SNMPv1/v2c una community "
                    "sbagliata NON da' errore, da' timeout — quindi 'nessuna risposta' puo' "
                    "voler dire anche 'community errata'. Prova con un'altra community."
                )
        except SNMPError as e:
            errore = str(e)

    return render(request, "contatori/discovery.html", {
        "rete": rete or "10.0.0.0/24",
        "community": community,
        "version": version,
        "timeout": timeout,
        "righe": righe,
        "errore": errore,
        "eseguita": eseguita,
        "cfg": cfg,
    })


@require_POST
def discovery_applica_ip(request, pk):
    """Scrive sulla macchina l'IP realmente trovato in rete."""
    macchina = get_object_or_404(Macchina, pk=pk)
    host = (request.POST.get("host") or "").strip()
    form = MacchinaForm({**{f: getattr(macchina, f) for f in
                            ("reparto", "matricola", "modello", "contratto", "fornitore")},
                         "host": host, "attiva": macchina.attiva,
                         "asset": macchina.asset_id}, instance=macchina)
    if form.is_valid():
        form.save()
        messages.success(request, f"{macchina.reparto}: IP aggiornato a {host}.")
    else:
        messages.error(request, f"{macchina.reparto}: IP non valido ({host}).")
    return redirect("contatori:discovery")


def dashboard(request):
    trimestri = services.trimestri_disponibili()
    ultimo = trimestri[0] if trimestri else None
    riepilogo = None
    if ultimo:
        _, riepilogo = services.riconcilia(ultimo)
    problemi = services.controllo_monotonia()
    macchine = Macchina.objects.filter(attiva=True)
    ultime = {l.macchina_id: l for l in LetturaContatori.objects.filter(trimestre=ultimo)} if ultimo else {}
    return render(request, "contatori/dashboard.html", {
        "trimestri": trimestri, "ultimo": ultimo, "riepilogo": riepilogo,
        "problemi": problemi, "macchine": macchine, "ultime": ultime,
    })


def riconciliazione(request, trimestre=None):
    trimestri = services.trimestri_disponibili()
    if trimestre is None:
        trimestre = trimestri[0] if trimestri else None
    righe, riepilogo = ([], None)
    if trimestre:
        righe, riepilogo = services.riconcilia(trimestre)
    return render(request, "contatori/riconciliazione.html", {
        "trimestri": trimestri, "trimestre": trimestre,
        "righe": righe, "riepilogo": riepilogo,
    })


def macchina_detail(request, pk):
    macchina = get_object_or_404(Macchina, pk=pk)
    dati = services.storico_macchina(macchina)
    return render(request, "contatori/macchina.html", {"macchina": macchina, "dati": dati})


def importa_lettura(request):
    if request.method == "POST":
        form = LetturaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Lettura salvata.")
            return redirect("contatori:dashboard")
    else:
        form = LetturaForm(initial={"data": timezone.now().date()})
    return render(request, "contatori/importa_lettura.html", {"form": form})


def leggi_snmp(request):
    """Legge via SNMP tutte le macchine attive con host. Salva le letture del trimestre corrente."""
    if request.method != "POST":
        return redirect("contatori:dashboard")
    from .snmp import leggi_macchina, SNMPError
    oggi = timezone.now().date()
    q = (oggi.month - 1) // 3 + 1
    trimestre = f"{oggi.year}-Q{q}"
    cfg = ImpostazioniSNMP.get_solo()
    ok, ko = 0, []
    for m in Macchina.objects.filter(attiva=True).exclude(host__isnull=True):
        try:
            vals = leggi_macchina(m, community=cfg.community, port=cfg.port,
                                  timeout=cfg.timeout, version=cfg.version)
            LetturaContatori.objects.update_or_create(
                macchina=m, trimestre=trimestre,
                defaults={**vals, "data": oggi, "fonte": "SNMP"})
            ok += 1
        except SNMPError as e:
            ko.append(f"{m.reparto}: {e}")
    if ok:
        messages.success(request, f"{ok} macchine lette via SNMP ({trimestre}).")
    for msg in ko:
        messages.warning(request, msg)
    return redirect("contatori:dashboard")


# --- Gestione stampanti & SNMP ---------------------------------------------

def macchine_list(request):
    """Elenco stampanti + form parametri SNMP globali (salvati sul singleton)."""
    from .snmp import COUNTER_MAP
    cfg = ImpostazioniSNMP.get_solo()
    if request.method == "POST":
        form = ImpostazioniSNMPForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            messages.success(request, "Parametri SNMP salvati.")
            return redirect("contatori:macchine")
    else:
        form = ImpostazioniSNMPForm(instance=cfg)
    return render(request, "contatori/macchine.html", {
        "macchine": Macchina.objects.all(),
        "snmp_form": form,
        "modelli_noti": sorted(COUNTER_MAP.keys()),
        "ultime": services.ultime_rilevazioni(),
    })


def macchina_edit(request, pk=None):
    """Crea (pk assente) o modifica una macchina."""
    macchina = get_object_or_404(Macchina, pk=pk) if pk else None
    if request.method == "POST":
        form = MacchinaForm(request.POST, instance=macchina)
        if form.is_valid():
            m = form.save()
            messages.success(request, f"Stampante «{m.reparto}» salvata.")
            return redirect("contatori:macchine")
    else:
        form = MacchinaForm(instance=macchina)
    return render(request, "contatori/macchina_form.html",
                  {"form": form, "macchina": macchina})


def _xlsx_response(wb, filename):
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(resp)
    return resp


def export_riconciliazione(request, trimestre):
    from . import export
    wb = export.riconciliazione_xlsx(trimestre)
    return _xlsx_response(wb, f"riconciliazione_{trimestre}.xlsx")


def export_analisi(request):
    from . import export
    wb = export.analisi_xlsx()
    return _xlsx_response(wb, "analisi_contatori.xlsx")


def analisi(request):
    """Sezione analisi: andamento, consumo (delta), ripartizione, classifica."""
    andamento = services.andamento_trimestri()
    consumo, anomalie = services.consumo_per_trimestre()
    classifica = services.classifica_reparti()
    return render(request, "contatori/analisi.html", {
        "andamento": andamento,
        "consumo": consumo,
        "anomalie_consumo": anomalie,
        "ripartizione": services.ripartizione(),
        "classifica": classifica,
        "and_max": max((a["totale"] for a in andamento), default=0),
        "cons_max": max((c["totale"] for c in consumo), default=0),
        "clas_max": classifica[0]["totale"] if classifica else 0,
    })


def _leggi_consumabili_cfg(macchina):
    """Legge i consumabili usando la config SNMP globale. Ritorna (lista, errore)."""
    from .snmp import leggi_consumabili, SNMPError
    cfg = ImpostazioniSNMP.get_solo()
    try:
        return leggi_consumabili(macchina, community=cfg.community, port=cfg.port,
                                 timeout=cfg.timeout, version=cfg.version), None
    except SNMPError as e:
        return None, str(e)


@require_POST
def macchina_consumabili(request, pk):
    """Legge lo stato consumabili via SNMP; ritorna il frammento HTMX."""
    macchina = get_object_or_404(Macchina, pk=pk)
    consumabili, errore = _leggi_consumabili_cfg(macchina)
    return render(request, "contatori/_consumabili.html",
                  {"consumabili": consumabili, "errore": errore, "macchina": macchina})


def consumabili_flotta(request):
    """Pagina flotta: tutte le macchine attive con host, riepilogo consumabili lazy."""
    # host è GenericIPAddressField: gli IP vuoti sono salvati come NULL, mai "".
    macchine = Macchina.objects.filter(attiva=True, host__isnull=False)
    return render(request, "contatori/consumabili.html", {"macchine": macchine})


def macchina_consumabili_riepilogo(request, pk):
    """Frammento compatto per la vista flotta: peggior livello + critici (≤15%)."""
    macchina = get_object_or_404(Macchina, pk=pk)
    consumabili, errore = _leggi_consumabili_cfg(macchina)
    riepilogo = None
    if consumabili:
        misurabili = [c for c in consumabili if c["pct"] is not None]
        critici = [c for c in misurabili if c["pct"] <= 15]
        riepilogo = {
            "peggiore": min(misurabili, key=lambda c: c["pct"]) if misurabili else None,
            "critici": critici,
            "n_totali": len(consumabili),
        }
    return render(request, "contatori/_consumabili_riepilogo.html",
                  {"riepilogo": riepilogo, "errore": errore, "macchina": macchina})


@require_POST
def macchina_test_snmp(request, pk):
    """Testa la lettura SNMP di una macchina; ritorna il frammento con l'esito."""
    from .snmp import leggi_macchina, SNMPError
    macchina = get_object_or_404(Macchina, pk=pk)
    cfg = ImpostazioniSNMP.get_solo()
    valori, errore = None, None
    try:
        valori = leggi_macchina(macchina, community=cfg.community, port=cfg.port,
                                timeout=cfg.timeout, version=cfg.version)
    except SNMPError as e:
        errore = str(e)
    return render(request, "contatori/_snmp_result.html",
                  {"valori": valori, "errore": errore, "macchina": macchina})
