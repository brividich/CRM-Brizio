from django.contrib import messages
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    DispositivoSNMPForm,
    ImpostazioniSNMPForm,
    LetturaForm,
    MacchinaForm,
    SondaSNMPForm,
)
from .models import (
    DispositivoSNMP,
    ImpostazioniSNMP,
    LetturaContatori,
    Macchina,
    SondaSNMP,
    StatoSNMP,
    ValoreSNMP,
)


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
    macchine = Macchina.objects.filter(attiva=True).select_related("asset")
    dispositivi = DispositivoSNMP.objects.filter(attivo=True).select_related("asset")[:8]
    ultime = {l.macchina_id: l for l in LetturaContatori.objects.filter(trimestre=ultimo)} if ultimo else {}
    return render(request, "contatori/dashboard.html", {
        "trimestri": trimestri, "ultimo": ultimo, "riepilogo": riepilogo,
        "problemi": problemi, "macchine": macchine, "ultime": ultime,
        "dispositivi_snmp": dispositivi,
        "snmp_riepilogo": services.centrale_snmp_riepilogo(),
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
    from .snmp import SNMPError
    oggi = timezone.localdate()
    q = (oggi.month - 1) // 3 + 1
    trimestre = f"{oggi.year}-Q{q}"
    ok, ko = 0, []
    for m in Macchina.objects.filter(attiva=True).exclude(host__isnull=True):
        try:
            vals = services.interroga_macchina(m)
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
        "macchine": Macchina.objects.select_related("asset").all(),
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
    from .snmp import SNMPError
    macchina = get_object_or_404(Macchina, pk=pk)
    valori, errore = None, None
    try:
        valori = services.interroga_macchina(macchina)
    except SNMPError as e:
        errore = str(e)
    return render(request, "contatori/_snmp_result.html",
                  {"valori": valori, "errore": errore, "macchina": macchina})


# --- Centrale dispositivi e lettori SNMP ----------------------------------

def snmp_centrale(request):
    categoria = (request.GET.get("categoria") or "").strip().upper()
    stato = (request.GET.get("stato") or "").strip().upper()
    dispositivi = DispositivoSNMP.objects.select_related("asset").all()
    if categoria in DispositivoSNMP.Categoria.values:
        dispositivi = dispositivi.filter(categoria=categoria)
    if stato in StatoSNMP.values:
        dispositivi = dispositivi.filter(snmp_stato=stato)
    return render(request, "contatori/snmp_centrale.html", {
        "dispositivi": dispositivi,
        "macchine": Macchina.objects.filter(attiva=True).select_related("asset"),
        "riepilogo": services.centrale_snmp_riepilogo(),
        "categoria": categoria,
        "stato": stato,
        "categorie": DispositivoSNMP.Categoria.choices,
        "stati": StatoSNMP.choices,
    })


def dispositivo_snmp_detail(request, pk):
    dispositivo = get_object_or_404(
        DispositivoSNMP.objects.select_related("asset"), pk=pk,
    )
    rilevazioni = list(
        dispositivo.rilevazioni.prefetch_related("valori__sonda")[:20]
    )
    ultimo_pk = ValoreSNMP.objects.filter(sonda_id=OuterRef("pk")).order_by(
        "-rilevazione__rilevata_il", "-pk",
    ).values("pk")[:1]
    ultimi_ids = dispositivo.sonde.annotate(
        ultimo_pk=Subquery(ultimo_pk),
    ).values("ultimo_pk")
    ultimi_valori = {
        valore.sonda_id: valore
        for valore in ValoreSNMP.objects.filter(pk__in=Subquery(ultimi_ids))
        .select_related("sonda", "rilevazione")
    }
    sonde = list(dispositivo.sonde.all())
    for sonda in sonde:
        sonda.ultimo_valore = ultimi_valori.get(sonda.pk)
    return render(request, "contatori/snmp_dispositivo_detail.html", {
        "dispositivo": dispositivo,
        "sonde": sonde,
        "rilevazioni": rilevazioni,
    })


def dispositivo_snmp_edit(request, pk=None):
    dispositivo = get_object_or_404(DispositivoSNMP, pk=pk) if pk else None
    initial = {}
    if dispositivo is None:
        initial = {
            "host": (request.GET.get("host") or "").strip(),
            "nome": (request.GET.get("nome") or "").strip(),
            "matricola": (request.GET.get("matricola") or "").strip(),
            "note": (request.GET.get("descr") or "").strip(),
        }
    if request.method == "POST":
        form = DispositivoSNMPForm(request.POST, instance=dispositivo)
        if form.is_valid():
            dispositivo = form.save()
            if pk is None and dispositivo.asset_id is None:
                asset, motivo = services.trova_asset_snmp(
                    seriale=dispositivo.matricola, host=dispositivo.host,
                )
                if asset is not None:
                    dispositivo.asset = asset
                    dispositivo.save(update_fields=["asset", "aggiornato_il"])
                    messages.info(
                        request,
                        f"Collegato automaticamente all'Asset {asset.asset_tag} "
                        f"tramite {motivo}.",
                    )
            messages.success(request, f"Dispositivo «{dispositivo.nome}» salvato.")
            return redirect("contatori:snmp_dispositivo", pk=dispositivo.pk)
    else:
        form = DispositivoSNMPForm(instance=dispositivo, initial=initial)
    return render(request, "contatori/snmp_dispositivo_form.html", {
        "form": form, "dispositivo": dispositivo,
    })


def sonda_snmp_edit(request, dispositivo_pk, pk=None):
    dispositivo = get_object_or_404(DispositivoSNMP, pk=dispositivo_pk)
    sonda = SondaSNMP(dispositivo=dispositivo)
    if pk is not None:
        sonda = get_object_or_404(SondaSNMP, pk=pk, dispositivo=dispositivo)
    if request.method == "POST":
        form = SondaSNMPForm(request.POST, instance=sonda)
        if form.is_valid():
            sonda = form.save(commit=False)
            sonda.dispositivo = dispositivo
            sonda.save()
            messages.success(request, f"Lettore OID «{sonda.nome}» salvato.")
            return redirect("contatori:snmp_dispositivo", pk=dispositivo.pk)
    else:
        form = SondaSNMPForm(instance=sonda)
    return render(request, "contatori/snmp_sonda_form.html", {
        "form": form, "dispositivo": dispositivo, "sonda": sonda,
    })


@require_POST
def dispositivo_snmp_interroga(request, pk):
    dispositivo = get_object_or_404(DispositivoSNMP, pk=pk)
    rilevazione = services.interroga_dispositivo(dispositivo)
    if rilevazione.stato == StatoSNMP.OK:
        messages.success(request, f"{dispositivo.nome}: interrogazione completata.")
    elif rilevazione.stato == StatoSNMP.WARNING:
        messages.warning(request, f"{dispositivo.nome}: lettura parziale o soglie in attenzione.")
    else:
        messages.error(request, f"{dispositivo.nome}: {rilevazione.errore or 'soglia critica rilevata'}")
    return redirect("contatori:snmp_dispositivo", pk=dispositivo.pk)


@require_POST
def dispositivi_snmp_interroga_tutti(request):
    esiti = {StatoSNMP.OK: 0, StatoSNMP.WARNING: 0, StatoSNMP.ERROR: 0}
    for dispositivo in DispositivoSNMP.objects.filter(attivo=True):
        rilevazione = services.interroga_dispositivo(dispositivo)
        esiti[rilevazione.stato] = esiti.get(rilevazione.stato, 0) + 1
    messages.success(
        request,
        f"Interrogazione completata: {esiti[StatoSNMP.OK]} operativi, "
        f"{esiti[StatoSNMP.WARNING]} in attenzione, {esiti[StatoSNMP.ERROR]} errori.",
    )
    return redirect("contatori:snmp_centrale")
