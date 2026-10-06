from django.contrib import messages
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.forms.models import model_to_dict
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action
from . import services
from .permessi import richiede_gestione
from .forms import (
    ColonnaProfiloSNMPForm,
    DispositivoSNMPForm,
    FatturaForm,
    ImpostazioniSNMPForm,
    LetturaForm,
    MacchinaForm,
    ProfiloSNMPForm,
    RigaFatturaForm,
    SondaSNMPForm,
)
from .models import (
    ColonnaProfiloSNMP,
    DispositivoSNMP,
    Fattura,
    ImpostazioniSNMP,
    LetturaContatori,
    Macchina,
    ProfiloSNMP,
    RigaFattura,
    SondaSNMP,
    StatoSNMP,
    ValoreSNMP,
)


@richiede_gestione
def discovery(request):
    from .discovery_views import discovery as discovery_page
    return discovery_page(request)


def _discovery_rapida(request):
    """Discovery SNMP di rete: trova le stampanti che rispondono e le abbina all'anagrafica.

    Serve soprattutto a scoprire un IP sbagliato: l'abbinamento e' sulla matricola
    (numero di serie letto dal dispositivo), non sull'IP.
    """
    from .snmp import SNMPError, scansiona_rete

    cfg = ImpostazioniSNMP.get_solo()
    rete = (request.POST.get("rete") or "").strip()
    community = (request.POST.get("community") or "").strip()
    communities = [c.strip() for c in community.splitlines() if c.strip()] or [cfg.community]
    version = request.POST.get("version") or cfg.version
    try:
        timeout = max(1, min(10, int(request.POST.get("timeout") or 2)))
    except ValueError:
        timeout = 2

    righe, errore, eseguita = None, "", False
    avviso = ""
    if request.method == "POST":
        eseguita = True
        try:
            trovati = scansiona_rete(rete, community=community, port=cfg.port,
                                     timeout=timeout, version=version, communities=communities)
            if getattr(trovati, "incompleta", False):
                avviso = (f"Scansione incompleta: raggiunto il limite di 20 secondi. "
                                 f"Host completati: {trovati.completati}/{trovati.totali}. "
                                 "Risultati parziali: restringi la rete o prova meno community.")
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

    from .discovery_views import contesto_discovery
    return render(request, "contatori/discovery.html", {
        **contesto_discovery(request),
        "rete": rete or "10.0.0.0/24",
        "community": "",
        "version": version,
        "timeout": timeout,
        "righe": righe,
        "errore": errore,
        "eseguita": eseguita,
        "avviso": avviso,
        "cfg": cfg,
    })


@richiede_gestione
@require_POST
def discovery_applica_ip(request, pk):
    """Scrive sulla macchina l'IP realmente trovato in rete."""
    macchina = get_object_or_404(Macchina, pk=pk)
    host = (request.POST.get("host") or "").strip()
    # Tutti i campi attuali: quelli assenti dal POST verrebbero azzerati
    # (profilo, community salvata, parametri SNMP).
    dati = model_to_dict(macchina, fields=MacchinaForm._meta.fields)
    form = MacchinaForm({**dati, "host": host}, instance=macchina)
    if form.is_valid():
        form.save()
        messages.success(request, f"{macchina.reparto}: IP aggiornato a {host}.")
    else:
        messages.error(request, f"{macchina.reparto}: IP non valido ({host}).")
    return redirect("contatori:discovery")


def dashboard(request):
    cruscotto = services.cruscotto_operativo()
    trimestre = cruscotto["trimestre"]
    macchine = Macchina.objects.filter(attiva=True).select_related("asset").order_by("reparto")
    letture = {l.macchina_id: l for l in LetturaContatori.objects.filter(trimestre=trimestre)}
    return render(request, "contatori/dashboard.html", {
        "c": cruscotto, "macchine": macchine, "ultime": letture,
        "dispositivi_snmp": DispositivoSNMP.objects.filter(attivo=True)
        .order_by("snmp_stato", "nome")[:8],
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
        "trimestri": services.opzioni_trimestri(extra=[trimestre] if trimestre else ()),
        "trimestre": trimestre,
        "righe": righe, "riepilogo": riepilogo,
        "fatture": Fattura.objects.filter(trimestre=trimestre).prefetch_related("righe")
        if trimestre else [],
    })


def _righe_formset(fattura, data=None):
    """Formset righe; una fattura nuova parte con una riga per contratto MFC attivo."""
    from django.forms import inlineformset_factory
    # Stesse iniziali anche in POST: le righe precompilate non toccate risultano
    # invariate e il formset non le salva.
    initial = []
    if fattura.pk is None:
        initial = [{"contratto": c, "descrizione": d} for c, d in services.contratti_attivi()]
    cls = inlineformset_factory(Fattura, RigaFattura, form=RigaFatturaForm,
                                extra=len(initial), can_delete=True)
    return cls(data, instance=fattura, prefix="righe", initial=initial)


@richiede_gestione
def fattura_edit(request, pk=None):
    """Inserimento/modifica fattura fornitore con le letture per contratto."""
    fattura = get_object_or_404(Fattura, pk=pk) if pk else Fattura()
    if request.method == "POST":
        form = FatturaForm(request.POST, instance=fattura)
        righe = _righe_formset(fattura, request.POST)
        if form.is_valid() and righe.is_valid():
            with transaction.atomic():
                fattura = form.save()
                righe.instance = fattura
                righe.save()
            log_action(request, "fattura_salvata" if pk else "fattura_creata", "contatori",
                       oggetto=fattura, dettaglio={"trimestre": fattura.trimestre,
                                                   "righe": fattura.righe.count()})
            messages.success(request, f"Fattura {fattura.numero} salvata.")
            return redirect("contatori:riconciliazione_trim", trimestre=fattura.trimestre)
    else:
        initial = {}
        if pk is None:
            trimestre = request.GET.get("trimestre") or ""
            initial = {"trimestre": trimestre if services.trimestre_valido(trimestre)
                       else services.trimestre_corrente()}
        form = FatturaForm(instance=fattura, initial=initial)
        righe = _righe_formset(fattura)
    return render(request, "contatori/fattura_form.html", {
        "form": form, "righe": righe, "fattura": fattura if pk else None,
    })


@richiede_gestione
@require_POST
def fattura_elimina(request, pk):
    fattura = get_object_or_404(Fattura, pk=pk)
    trimestre, numero = fattura.trimestre, fattura.numero
    log_action(request, "fattura_eliminata", "contatori", oggetto=fattura,
               dettaglio={"trimestre": trimestre, "numero": numero})
    fattura.delete()
    messages.success(request, f"Fattura {numero} eliminata.")
    return redirect("contatori:riconciliazione_trim", trimestre=trimestre)


def macchina_detail(request, pk):
    macchina = get_object_or_404(Macchina, pk=pk)
    dati = services.storico_macchina(macchina)
    return render(request, "contatori/macchina.html", {
        "macchina": macchina, "dati": dati,
        "produzione": services.produzione_macchina(macchina),
        "consumabili_stato": services.stato_consumabili([macchina]).get(macchina.pk),
        "letture_mensili": macchina.letture_mensili.all()[:24],
    })


@richiede_gestione
def importa_lettura(request, pk=None):
    """Inserimento (pk assente) o correzione di una lettura trimestrale."""
    lettura = get_object_or_404(LetturaContatori.objects.select_related("macchina"), pk=pk) if pk else None
    if request.method == "POST":
        form = LetturaForm(request.POST, instance=lettura)
        if form.is_valid():
            lettura = form.save()
            log_action(request, "lettura_modificata" if pk else "lettura_creata", "contatori",
                       oggetto=lettura, dettaglio={"trimestre": lettura.trimestre, "fonte": lettura.fonte,
                                                   "calo_confermato": form.cleaned_data.get("conferma_calo", False)})
            messages.success(request, f"Lettura {lettura.trimestre} di {lettura.macchina.reparto} salvata.")
            return redirect("contatori:macchina", pk=lettura.macchina_id)
    else:
        initial = {}
        if lettura is None:
            initial = {"data": timezone.localdate(), "trimestre": services.trimestre_corrente()}
            if request.GET.get("macchina", "").isdigit():
                initial["macchina"] = request.GET["macchina"]
            if services.trimestre_valido(request.GET.get("trimestre")):
                initial["trimestre"] = request.GET["trimestre"]
        form = LetturaForm(instance=lettura, initial=initial)
    return render(request, "contatori/importa_lettura.html", {"form": form, "lettura": lettura})


@richiede_gestione
def letture_proposte(request):
    """Letture trimestrali ricavate dalle mensili SNMP, da confermare (singole o in blocco)."""
    trimestre = request.GET.get("trimestre") or request.POST.get("trimestre") or ""
    if not services.trimestre_valido(trimestre):
        trimestre = services.trimestre_precedente(services.trimestre_corrente())
    proposte = services.proposte_letture_trimestrali(trimestre)
    if request.method == "POST":
        scelte = set(request.POST.getlist("macchina"))
        create = []
        for p in proposte:
            if str(p["macchina"].pk) in scelte and not p["incoerente"]:
                lettura, creata = services.conferma_proposta(p, trimestre)
                if creata:
                    create.append(lettura)
        log_action(request, "letture_da_mensili", "contatori",
                   dettaglio={"trimestre": trimestre, "confermate": len(create)})
        messages.success(request, f"{len(create)} letture {trimestre} confermate dalle letture mensili.")
        return redirect(f"{reverse('contatori:letture_proposte')}?trimestre={trimestre}")
    return render(request, "contatori/letture_proposte.html", {
        "trimestre": trimestre, "proposte": proposte,
        "trimestri": services.opzioni_trimestri(extra=[trimestre]),
    })


@richiede_gestione
@require_POST
def lettura_elimina(request, pk):
    lettura = get_object_or_404(LetturaContatori.objects.select_related("macchina"), pk=pk)
    macchina_id = lettura.macchina_id
    log_action(request, "lettura_eliminata", "contatori", oggetto=lettura,
               dettaglio={"trimestre": lettura.trimestre, "totale": lettura.totale})
    lettura.delete()
    messages.success(request, "Lettura eliminata.")
    return redirect("contatori:macchina", pk=macchina_id)


@richiede_gestione
def leggi_snmp(request):
    """Legge via SNMP le MFC attive con host e salva la lettura del trimestre corrente.

    Non sovrascrive mai una lettura manuale o da fattura e non salva valori piu'
    bassi del trimestre precedente (contatore azzerato o IP che punta a un'altra
    macchina): in entrambi i casi la macchina viene solo segnalata.
    """
    if request.method != "POST":
        return redirect("contatori:dashboard")
    from .models import CONTATORI
    from .snmp import SNMPError
    oggi = timezone.localdate()
    trimestre = services.trimestre_di(oggi)
    presenti = {l.macchina_id: l for l in LetturaContatori.objects.filter(trimestre=trimestre)}
    lette, manuali, incoerenti, errori = 0, [], [], []
    for m in Macchina.objects.filter(attiva=True).exclude(host__isnull=True).order_by("reparto"):
        esistente = presenti.get(m.id)
        if esistente and esistente.fonte != LetturaContatori.Fonte.SNMP:
            manuali.append(m.reparto)
            continue
        try:
            vals = services.interroga_macchina(m)
        except SNMPError as e:
            errori.append(f"{m.reparto} ({e})")
            continue
        prima = m.letture.filter(trimestre__lt=trimestre).order_by("-trimestre").first()
        if prima and any(vals[c] < getattr(prima, c) for c, _ in CONTATORI):
            incoerenti.append(m.reparto)
            continue
        LetturaContatori.objects.update_or_create(
            macchina=m, trimestre=trimestre,
            defaults={**vals, "data": oggi, "fonte": LetturaContatori.Fonte.SNMP})
        lette += 1
    log_action(request, "letture_snmp", "contatori", dettaglio={
        "trimestre": trimestre, "lette": lette, "manuali": len(manuali),
        "incoerenti": len(incoerenti), "errori": len(errori)})
    if lette:
        messages.success(request, f"{lette} MFC lette via SNMP per il {trimestre}.")
    if manuali:
        messages.info(request, "Non sovrascritte (lettura manuale già presente): " + ", ".join(manuali) + ".")
    if incoerenti:
        messages.warning(request, "Valori più bassi del trimestre precedente, non salvati: "
                         + ", ".join(incoerenti) + ". Verifica IP o azzeramento del contatore.")
    if errori:
        messages.error(request, "Non raggiungibili: " + "; ".join(errori[:10])
                       + (f" e altre {len(errori) - 10}." if len(errori) > 10 else "."))
    if not (lette or manuali or incoerenti or errori):
        messages.info(request, "Nessuna MFC attiva con indirizzo IP da leggere.")
    return redirect("contatori:dashboard")


# --- Gestione stampanti & SNMP ---------------------------------------------

@richiede_gestione(solo_post=True)
def macchine_list(request):
    """Elenco stampanti + form parametri SNMP globali (salvati sul singleton)."""
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
        "profili_mfc": [
            profilo for profilo in ProfiloSNMP.objects.filter(
                attivo=True, categoria=ProfiloSNMP.Categoria.STAMPANTE,
            ).prefetch_related("colonne")
            if len({c.contatore_mfc for c in profilo.colonne.all() if c.contatore_mfc}) == 4
        ],
        "ultime": services.ultime_rilevazioni(),
    })


@richiede_gestione
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
    """Legge i consumabili e, se la lettura riesce, la salva nello storico."""
    consumabili, errore = services.leggi_consumabili_macchina(macchina)
    if consumabili:
        services.salva_consumabili(macchina, consumabili)
    return consumabili, errore


@require_POST
def macchina_consumabili(request, pk):
    """Legge lo stato consumabili via SNMP; ritorna il frammento HTMX."""
    macchina = get_object_or_404(Macchina, pk=pk)
    consumabili, errore = _leggi_consumabili_cfg(macchina)
    if request.POST.get("asset_inline") == "1":
        # Same POST route and ACL as Contatori; never echo raw network errors.
        supplies = []
        for item in (consumabili or [])[:20]:
            pct = item.get("pct")
            supplies.append({"nome": item.get("nome", "Consumabile"),
                             "display_pct": pct if type(pct) in (int, float) and 0 <= pct <= 100 else None})
        return render(request, "contatori/_consumabili_asset.html", {
            "supplies": supplies, "failed": bool(errore), "checked_at": timezone.now(),
        })
    return render(request, "contatori/_consumabili.html",
                  {"consumabili": consumabili, "errore": errore, "macchina": macchina})


def _riga_consumabili(macchina, stato):
    """Dati di una riga della pagina flotta, con la chiave di ordinamento per criticita'."""
    if stato is None:
        rango, livello = 2, 101
    elif stato["critici"]:
        rango, livello = 0, stato["peggiore"]["pct"]
    else:
        rango, livello = 1 if stato["peggiore"] is None else 3, (stato["peggiore"] or {}).get("pct", 100)
    return {"macchina": macchina, "stato": stato, "ordine": (rango, livello, macchina.reparto)}


def consumabili_flotta(request):
    """Ultimo livello salvato dei consumabili di ogni MFC attiva con IP, i critici in cima.

    Nessuna interrogazione SNMP all'apertura: i dati arrivano dal task giornaliero o
    da «Leggi ora». host e' GenericIPAddressField: gli IP vuoti sono NULL, mai "".
    """
    macchine = list(Macchina.objects.filter(attiva=True, host__isnull=False))
    stati = services.stato_consumabili(macchine)
    righe = sorted((_riga_consumabili(m, stati.get(m.pk)) for m in macchine), key=lambda r: r["ordine"])
    return render(request, "contatori/consumabili.html", {
        "righe": righe,
        "critici": sum(1 for r in righe if r["stato"] and r["stato"]["critici"]),
        "mai_lette": sum(1 for r in righe if r["stato"] is None),
        "soglia": services.SOGLIA_CONSUMABILE_PCT,
    })


@require_POST
def consumabili_aggiorna(request, pk):
    """«Leggi ora» di una riga: lettura SNMP, salvataggio, riga aggiornata (HTMX)."""
    macchina = get_object_or_404(Macchina, pk=pk, attiva=True)
    _, errore = _leggi_consumabili_cfg(macchina)
    stato = services.stato_consumabili([macchina]).get(macchina.pk)
    return render(request, "contatori/_consumabili_riga.html", {
        "r": _riga_consumabili(macchina, stato), "errore": errore,
        "soglia": services.SOGLIA_CONSUMABILE_PCT,
    })


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
        "profili_disponibili": ProfiloSNMP.objects.filter(attivo=True),
        "ultima_rilevazione": rilevazioni[0] if rilevazioni else None,
        "stampante": dispositivo.categoria == DispositivoSNMP.Categoria.STAMPANTE,
    })


@richiede_gestione
def dispositivo_snmp_edit(request, pk=None):
    dispositivo = get_object_or_404(DispositivoSNMP, pk=pk) if pk else None
    initial = {}
    if dispositivo is None:
        initial = {
            "host": (request.GET.get("host") or "").strip(),
            "nome": (request.GET.get("nome") or "").strip(),
            "matricola": (request.GET.get("matricola") or "").strip(),
            "note": (request.GET.get("descr") or "").strip(),
            "community_salvata": request.GET.get("community_id") or None,
            "versione": request.GET.get("versione") or "",
            "porta": request.GET.get("porta") or None,
        }
    if request.method == "POST":
        form = DispositivoSNMPForm(request.POST, instance=dispositivo)
        if form.is_valid():
            dispositivo = form.save()
            if dispositivo.profilo_snmp_id:
                services.applica_profilo_dispositivo(
                    dispositivo, dispositivo.profilo_snmp,
                )
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


def profili_snmp(request):
    categoria = (request.GET.get("categoria") or "").strip().upper()
    profili = ProfiloSNMP.objects.prefetch_related("colonne").all()
    if categoria in ProfiloSNMP.Categoria.values:
        profili = profili.filter(categoria=categoria)
    return render(request, "contatori/snmp_profili.html", {
        "profili": profili,
        "categoria": categoria,
        "categorie": ProfiloSNMP.Categoria.choices,
    })


@richiede_gestione
def profilo_snmp_edit(request, pk=None):
    profilo = get_object_or_404(ProfiloSNMP, pk=pk) if pk else None
    if request.method == "POST":
        form = ProfiloSNMPForm(request.POST, instance=profilo)
        if form.is_valid():
            profilo = form.save(commit=False)
            profilo.save()
            messages.success(request, f"Profilo «{profilo.nome}» salvato.")
            return redirect("contatori:snmp_profilo_edit", pk=profilo.pk)
    else:
        form = ProfiloSNMPForm(instance=profilo)
    return render(request, "contatori/snmp_profilo_form.html", {
        "form": form, "profilo": profilo,
        "colonne": profilo.colonne.all() if profilo else [],
    })


@richiede_gestione
def colonna_profilo_snmp_edit(request, profilo_pk, pk=None):
    profilo = get_object_or_404(ProfiloSNMP, pk=profilo_pk)
    colonna = ColonnaProfiloSNMP(profilo=profilo)
    if pk is not None:
        colonna = get_object_or_404(
            ColonnaProfiloSNMP, pk=pk, profilo=profilo,
        )
    if request.method == "POST":
        form = ColonnaProfiloSNMPForm(request.POST, instance=colonna)
        if form.is_valid():
            colonna = form.save(commit=False)
            colonna.profilo = profilo
            colonna.save()
            messages.success(request, f"Colonna «{colonna.nome}» salvata.")
            return redirect("contatori:snmp_profilo_edit", pk=profilo.pk)
    else:
        form = ColonnaProfiloSNMPForm(instance=colonna)
    return render(request, "contatori/snmp_profilo_colonna_form.html", {
        "form": form, "profilo": profilo, "colonna": colonna,
    })


@richiede_gestione
@require_POST
def dispositivo_snmp_applica_profilo(request, pk):
    dispositivo = get_object_or_404(DispositivoSNMP, pk=pk)
    profilo = get_object_or_404(
        ProfiloSNMP, pk=request.POST.get("profilo"), attivo=True,
    )
    create_count, update_count = services.applica_profilo_dispositivo(
        dispositivo, profilo, sovrascrivi=request.POST.get("sovrascrivi") == "1",
    )
    messages.success(
        request,
        f"Profilo {profilo.nome} applicato: {create_count} sonde create, "
        f"{update_count} aggiornate.",
    )
    return redirect("contatori:snmp_dispositivo", pk=dispositivo.pk)


@richiede_gestione
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
