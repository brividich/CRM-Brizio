from django.contrib import messages
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.forms.models import model_to_dict
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from core.audit import log_action
from . import integrazione, services
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
from .stampanti import contesto_pannello
from .models import (
    ColonnaProfiloSNMP,
    DispositivoSNMP,
    Fattura,
    ImpostazioniSNMP,
    LetturaContatori,
    LetturaMensileContatori,
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
    prima = macchina.host
    if _applica_ip(macchina, host):
        # Stessa riga di audit di «Correggi IP» su più righe (views_tabelle.discovery_correggi_ip).
        log_action(request, "discovery_ip_corretti", "contatori",
                   {"corretti": [{"macchina_id": macchina.pk, "da": prima, "a": host}]})
        messages.success(request, f"{macchina.reparto}: IP aggiornato a {host}.")
    else:
        messages.error(request, f"{macchina.reparto}: IP non valido ({host}).")
    return redirect("contatori:discovery")


def _applica_ip(macchina, host):
    """Scrive l'IP trovato dalla discovery con la validazione del modulo MFC; False se non valido."""
    # Tutti i campi attuali: quelli assenti dal POST verrebbero azzerati
    # (profilo, community salvata, parametri SNMP).
    dati = model_to_dict(macchina, fields=MacchinaForm._meta.fields)
    form = MacchinaForm({**dati, "host": host}, instance=macchina)
    if not form.is_valid():
        return False
    form.save()
    return True


def _asset_proposto(apparato, tipo):
    """Asset proposto per un apparato senza asset: stesso abbinamento della riconciliazione IT."""
    try:
        from assets.services.identity_match import match_hub_asset

        if tipo == "snmp":
            asset, motivo = match_hub_asset(serial=apparato.matricola, ip=apparato.host, hostname=apparato.sys_name)
        else:
            asset, motivo = match_hub_asset(serial=apparato.matricola, ip=apparato.host or "")
    except Exception:  # noqa: BLE001 - la proposta e' un aiuto, la scheda non dipende da essa
        return None
    if asset is None:
        return None
    return {"asset": asset, "motivo": motivo, "tipo": tipo, "apparato_pk": apparato.pk}


@require_POST
@richiede_gestione
def apparato_collega_asset(request, tipo, pk):
    """Collega MFC o dispositivo SNMP all'asset proposto: solo se la proposta e' ancora quella mostrata."""
    model, dettaglio = {"mfc": (Macchina, "contatori:macchina"),
                        "snmp": (DispositivoSNMP, "contatori:snmp_dispositivo")}.get(tipo, (None, None))
    if model is None:
        return redirect("contatori:dashboard")
    apparato = get_object_or_404(model, pk=pk)
    proposta = _asset_proposto(apparato, tipo) if apparato.asset_id is None else None
    if proposta is None or str(proposta["asset"].pk) != request.POST.get("asset", ""):
        messages.warning(request, "Collegamento non eseguito: l'apparato è già collegato o la proposta è cambiata.")
        return redirect(dettaglio, pk=pk)
    asset = _collega_asset(request, apparato, tipo, proposta)
    messages.success(request, f"Apparato collegato all'asset {asset.asset_tag}.")
    return redirect(dettaglio, pk=pk)


def _collega_asset(request, apparato, tipo, proposta):
    """Collega l'apparato all'asset proposto con la sua riga di audit (azione singola e multipla)."""
    asset = proposta["asset"]
    apparato.asset = asset
    apparato.save(update_fields=["asset", "aggiornato_il"] if tipo == "snmp" else ["asset"])
    log_action(request, "apparato_collegato_asset", "contatori",
               {"tipo": tipo, "apparato_id": apparato.pk, "asset_id": asset.pk, "asset_tag": asset.asset_tag,
                "motivo": proposta["motivo"]})
    return asset


def _puo_creare_asset(request):
    """Creare un asset dall'apparato: gestione Contatori e permesso di creazione nel modulo Asset."""
    from assets.services.it_monitoring import can_view_monitoring
    from .permessi import puo_gestire

    return puo_gestire(request) and can_view_monitoring(request, reverse("assets:asset_create"))


def _licenze_software_asset(asset, apparato=None, tipo="", request=None):
    """Riquadro «Asset collegato» e «Sicurezza» delle schede apparato (moduli Asset e SOC)."""
    sicurezza = integrazione.sicurezza_apparato(request, apparato) if apparato is not None and request else None
    if asset is None:
        proposta = _asset_proposto(apparato, tipo) if apparato is not None else None
        crea = None
        if apparato is not None and request is not None and _puo_creare_asset(request):
            crea = {"tipo": tipo, "pk": apparato.pk, "dati": integrazione.dati_asset_proposti(apparato)}
        return {"licenze_asset": [], "software_asset": None, "asset_proposto": proposta,
                "crea_asset": crea, "sicurezza": sicurezza}
    from assets.services.software_licenze import licenses_for_asset

    software = None
    try:
        from security.services.software_catalog import software_for_hub_asset

        software = software_for_hub_asset(asset)
    except Exception:  # noqa: BLE001 - la scheda apparato non dipende dall'inventario software
        software = None
    costi = None
    try:
        from assets.services.costi_asset import costi_asset

        costi = costi_asset(asset)
    except Exception:  # noqa: BLE001 - la scheda apparato non dipende dai costi
        costi = None
    allineamento = integrazione.allineamento_asset(apparato) if apparato is not None else []
    return {"licenze_asset": licenses_for_asset(asset), "software_asset": software, "costi_asset": costi,
            "allineamento": allineamento, "sicurezza": sicurezza}


@require_POST
@richiede_gestione
def apparato_crea_asset(request, tipo, pk):
    """Crea nell'inventario l'asset dell'apparato (dati letti via SNMP + punto rete con l'IP) e lo collega."""
    model = integrazione._modello_apparato(tipo)
    if model is None:
        return redirect("contatori:dashboard")
    apparato = get_object_or_404(model, pk=pk)
    dettaglio = integrazione.url_apparato(apparato)
    if not _puo_creare_asset(request):
        messages.error(request, "Per creare l'asset serve anche il permesso di creazione nel modulo Asset.")
        return redirect(dettaglio)
    try:
        asset = integrazione.crea_asset_da_apparato(apparato)
    except ValueError as exc:
        messages.warning(request, str(exc))
        return redirect(dettaglio)
    dati = {"tipo": tipo, "apparato_id": apparato.pk, "apparato": integrazione.nome_apparato(apparato),
            "asset_id": asset.pk, "asset_tag": asset.asset_tag, "ip": apparato.host or ""}
    # Agganciata all'asset: compare nello storico della sua scheda.
    log_action(request, "asset_creato_da_apparato", "contatori", dati, oggetto_tipo="assets.asset", oggetto_id=str(asset.pk))
    messages.success(request, f"Asset {asset.asset_tag} creato e collegato. Completa reparto, data d'acquisto e assegnazione dalla scheda asset.")
    return redirect(dettaglio)


def dashboard(request):
    cruscotto = services.cruscotto_operativo()
    trimestre = cruscotto["trimestre"]
    macchine = Macchina.objects.filter(attiva=True).select_related("asset").order_by("reparto")
    letture = {l.macchina_id: l for l in LetturaContatori.objects.filter(trimestre=trimestre)}
    dispositivi = services.dispositivi_senza_doppioni(DispositivoSNMP.objects.filter(attivo=True))
    dispositivi_snmp = list(dispositivi.order_by("snmp_stato", "nome")[:8])
    flotta = services.stato_flotta()
    errori_snmp = services.ultimi_errori_snmp()
    return render(request, "contatori/dashboard.html", {
        "c": cruscotto, "macchine": macchine, "ultime": letture,
        # Elenchi brevi: «e altri N →» porta alla lista completa (stesso conteggio dei riquadri).
        "dispositivi_snmp": dispositivi_snmp,
        "dispositivi_altri": max(dispositivi.count() - len(dispositivi_snmp), 0),
        "snmp_riepilogo": services.centrale_snmp_riepilogo(),
        "flotta": flotta,
        "mappa": services.mappa_flotta(),
        "etichette_flotta": services.FLOTTA,
        "errori_snmp": errori_snmp,
        "errori_altri": max(flotta["errore"] - len(errori_snmp), 0),
        "da_riconciliare": services.fatture_da_riconciliare(),
        "licenze_apparati": services.licenze_asset_apparati(),
        "integrazione": integrazione.quadro_integrazione(request),
    })


def riconciliazione(request, trimestre=None):
    trimestri = services.trimestri_disponibili()
    if trimestre is None:
        trimestre = trimestri[0] if trimestri else None
    righe, riepilogo = ([], None)
    if trimestre:
        righe, riepilogo = services.riconcilia(trimestre)
    gruppi_tutti = riepilogo["gruppi"] if riepilogo else []
    solo_da_verificare = request.GET.get("vista") == "da-verificare"
    da_verificare = [gr for gr in gruppi_tutti if gr["livello"] != "ok"]
    return render(request, "contatori/riconciliazione.html", {
        "trimestri": services.opzioni_trimestri(extra=[trimestre] if trimestre else ()),
        "trimestre": trimestre,
        "righe": righe, "riepilogo": riepilogo,
        "gruppi_tutti": gruppi_tutti,
        "gruppi": da_verificare if solo_da_verificare else gruppi_tutti,
        "da_verificare": len(da_verificare), "solo_da_verificare": solo_da_verificare,
        "fatture": Fattura.objects.filter(trimestre=trimestre).prefetch_related("righe")
        if trimestre else [],
    })


def guida(request):
    from .guida import SEZIONI
    return render(request, "contatori/guida.html", {"sezioni": SEZIONI})


def riconciliazione_guida(request):
    """Vecchio indirizzo della guida (sotto la riconciliazione): resta valido e porta alla nuova."""
    return redirect("contatori:guida", permanent=True)


def _righe_formset(fattura, data=None, initial=None):
    """Formset righe; una fattura nuova parte con una riga per contratto MFC attivo
    (o con le righe lette dal file della fattura, se passate in `initial`)."""
    from django.forms import inlineformset_factory
    # Stesse iniziali anche in POST: le righe precompilate non toccate risultano
    # invariate e il formset non le salva.
    if initial is None:
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
    if request.method == "POST" and request.POST.get("azione") == "importa" and pk is None:
        from .fattura_import import MAX_BYTES, FatturaNonLeggibile, leggi_fattura
        caricato = request.FILES.get("file_fattura")
        try:
            if caricato is None:
                raise FatturaNonLeggibile("Scegli il file XML o PDF della fattura.")
            if caricato.size > MAX_BYTES:
                raise FatturaNonLeggibile("File troppo grande (massimo 5 MB).")
            letta = leggi_fattura(caricato.name, caricato.read())
        except FatturaNonLeggibile as e:
            messages.error(request, f"Fattura non importata: {e}")
            return redirect("contatori:fattura_nuova")
        # Il file non viene conservato: si usano solo i dati per precompilare la pagina.
        log_action(request, "fattura_letta_da_file", "contatori",
                   dettaglio={"numero": letta["testata"]["numero"], "righe": len(letta["righe"])})
        testata = {k: v for k, v in letta["testata"].items() if v}
        form = FatturaForm(instance=fattura, initial=testata)
        righe = _righe_formset(fattura, initial=letta["righe"])
        return render(request, "contatori/fattura_form.html", {
            "form": form, "righe": righe, "fattura": None,
            "avvisi_import": letta["avvisi"], "file_letto": caricato.name,
        })
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
    elif pk is None and request.GET.get("da_import", "").isdigit():
        # Fattura letta nell'import multiplo: si apre qui per controllarla e salvarla.
        from .fatture_multiple import CHIAVE_SESSIONE, dati_form
        voci = request.session.get(CHIAVE_SESSIONE) or []
        i = int(request.GET["da_import"])
        if i >= len(voci) or voci[i].get("errore"):
            messages.error(request, "Fattura dell'import non più disponibile: ricarica i file.")
            return redirect("contatori:fatture_importa")
        testata, righe_iniziali = dati_form(voci[i])
        return render(request, "contatori/fattura_form.html", {
            "form": FatturaForm(instance=fattura, initial=testata),
            "righe": _righe_formset(fattura, initial=righe_iniziali), "fattura": None,
            "avvisi_import": voci[i]["avvisi"], "file_letto": voci[i]["file"],
        })
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


def fatture_elenco(request):
    """Archivio fatture per trimestre con esito della riconciliazione e trimestri scoperti."""
    archivio = services.archivio_fatture()
    # Collegamento facoltativo alla scheda del fornitore: senza abbinamento resta il solo codice.
    from fornitori import collegamenti as forn

    if forn.apre(request, "fornitori:fornitori_list"):
        schede = forn.mappa_codici()
        for voce in archivio:
            for fattura in voce["fatture"]:
                fattura.fornitore_hub_id = schede.get(fattura.fornitore)
    if _vuole_excel(request):
        from . import export
        return _xlsx_response(export.fatture_xlsx(archivio), "archivio_fatture.xlsx")
    return render(request, "contatori/fatture.html", {
        "archivio": archivio, "url_excel": _url_excel(request),
        "scoperti": [a for a in archivio if not a["fatture"] and not a["in_corso"]],
        "totale_fatture": sum(len(a["fatture"]) for a in archivio),
    })


@richiede_gestione
def fatture_importa(request):
    """Import di piu' fatture: si caricano i file, si controlla l'anteprima, si salvano le scelte."""
    from .fatture_multiple import CHIAVE_SESSIONE, MAX_FILE, PRONTA, classifica, leggi_file, salva

    azione = request.POST.get("azione") if request.method == "POST" else ""
    if azione == "leggi":
        files = request.FILES.getlist("file_fatture")
        if not files:
            messages.error(request, "Scegli uno o più file XML o PDF.")
            return redirect("contatori:fatture_importa")
        if len(files) > MAX_FILE:
            messages.warning(request, f"Lette solo le prime {MAX_FILE} fatture: carica le altre dopo.")
        voci = leggi_file(files)
        request.session[CHIAVE_SESSIONE] = voci
        log_action(request, "fatture_lette_da_file", "contatori",
                   dettaglio={"file": len(voci), "non_leggibili": sum(1 for v in voci if v["errore"])})
        return redirect("contatori:fatture_importa")
    voci = request.session.get(CHIAVE_SESSIONE) or []
    if azione == "salva":
        scelte = {int(i) for i in request.POST.getlist("voce") if i.isdigit()}
        salvate, scartate = [], []
        for voce in classifica(voci):
            if voce["indice"] not in scelte or voce["errore"] or voce.get("salvata"):
                continue
            fattura, errori = salva(voce)
            if fattura is None:
                scartate.append(f"{voce['file']}: {'; '.join(errori[:3])}")
                continue
            salvate.append(fattura)
            voce["salvata"] = fattura.pk
            log_action(request, "fattura_creata", "contatori", oggetto=fattura,
                       dettaglio={"trimestre": fattura.trimestre, "righe": fattura.righe.count(),
                                  "da_import_multiplo": True})
        request.session[CHIAVE_SESSIONE] = voci
        if salvate:
            messages.success(request, f"{len(salvate)} fatture salvate: "
                             + ", ".join(f"{f.numero} ({f.trimestre})" for f in salvate) + ".")
        if scartate:
            messages.error(request, "Non salvate, aprile per correggerle: " + " · ".join(scartate[:8])
                           + (f" e altre {len(scartate) - 8}." if len(scartate) > 8 else ""))
        if not (salvate or scartate):
            messages.info(request, "Nessuna fattura selezionata.")
        return redirect("contatori:fatture_importa")
    if azione == "svuota":
        request.session.pop(CHIAVE_SESSIONE, None)
        return redirect("contatori:fatture_importa")
    voci = classifica(voci)
    return render(request, "contatori/fatture_importa.html", {
        "voci": voci, "max_file": MAX_FILE,
        "pronte": sum(1 for v in voci if v["stato"] == PRONTA and not v.get("salvata")),
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
    macchina = get_object_or_404(
        Macchina.objects.select_related("asset", "profilo_snmp", "community_salvata"), pk=pk)
    dati = services.storico_macchina(macchina)
    from .ticket_stampante import url_apri_ticket

    consumabili_stato = services.stato_consumabili([macchina]).get(macchina.pk)
    from .presentazione import collegamenti_mfc, disegno_stampante

    return render(request, "contatori/macchina.html", {
        "collegamenti": collegamenti_mfc(macchina, request),
        "disegno_mfc": disegno_stampante(macchina.dati_stampante, macchina.snmp_stato),
        "url_ticket": url_apri_ticket(request, macchina, consumabili_stato),
        "macchina": macchina, "dati": dati, "info_snmp": services.info_snmp(macchina),
        "ultima_mensile": macchina.letture_mensili.order_by("-rilevata_il").first(),
        "produzione": services.produzione_macchina(macchina),
        "consumabili_stato": consumabili_stato,
        "righe_letture": services.righe_letture_macchina(macchina),
        "righe_mensili": services.righe_mensili_macchina(macchina),
        "mensili_totale": macchina.letture_mensili.count(),
        "fatture_contratto": services.fatture_macchina(macchina),
        "fatture_contratto_totale": services.trimestri_fatturati_contratto(macchina.contratto),
        "colleghi_pool": (list(Macchina.objects.filter(contratto=macchina.contratto)
                               .exclude(pk=macchina.pk).order_by("reparto"))
                          if macchina.contratto else []),
        **contesto_pannello(macchina, macchina.dati_stampante),
        "dispositivo_tecnico": services.dispositivo_dello_stesso_apparato(macchina),
        **_licenze_software_asset(macchina.asset, macchina, "mfc", request),
    })


def _ritorno_gestione(request):
    """URL di «Gestisci letture» (con i suoi filtri) da cui si e' arrivati, altrimenti ""."""
    dest = request.POST.get("next") or request.GET.get("next") or ""
    return dest if dest.startswith(reverse("contatori:letture_gestisci")) else ""


@richiede_gestione
def importa_lettura(request, pk=None):
    """Inserimento (pk assente) o correzione di una lettura trimestrale."""
    lettura = get_object_or_404(LetturaContatori.objects.select_related("macchina"), pk=pk) if pk else None
    ritorno = _ritorno_gestione(request)
    mensile = None
    if request.method == "POST":
        form = LetturaForm(request.POST, instance=lettura)
        if form.is_valid():
            lettura = form.save()
            if pk and set(services.CAMPI) & set(form.changed_data):
                services.azzera_calo_spiegato(lettura)
            log_action(request, "lettura_modificata" if pk else "lettura_creata", "contatori",
                       oggetto=lettura, dettaglio={"trimestre": lettura.trimestre, "fonte": lettura.fonte,
                                                   "calo_confermato": form.cleaned_data.get("conferma_calo", False)})
            messages.success(request, f"Lettura {lettura.trimestre} di {lettura.macchina.reparto} salvata.")
            return redirect(ritorno or reverse("contatori:macchina", args=[lettura.macchina_id]))
    else:
        initial = {}
        if lettura is None:
            initial = {"data": timezone.localdate(), "trimestre": services.trimestre_corrente()}
            if request.GET.get("macchina", "").isdigit():
                initial["macchina"] = request.GET["macchina"]
            if services.trimestre_valido(request.GET.get("trimestre")):
                initial["trimestre"] = request.GET["trimestre"]
            macchina = Macchina.objects.filter(pk=initial.get("macchina")).first()
            if macchina is not None:
                # I contatori si prendono dalla lettura mensile SNMP (mezzanotte del primo del mese).
                mensile = services.mensile_per_trimestre(macchina, initial["trimestre"])
            if mensile is not None:
                initial.update({c: getattr(mensile, c) for c in services.CAMPI},
                               data=timezone.localtime(mensile.rilevata_il).date(),
                               fonte=LetturaContatori.Fonte.SNMP,
                               note=f"Da lettura mensile del {mensile.mese:%m/%Y}")
        form = LetturaForm(instance=lettura, initial=initial)
    return render(request, "contatori/importa_lettura.html",
                  {"form": form, "lettura": lettura, "ritorno": ritorno,
                   "mensile": mensile,
                   "provvisoria": mensile is not None and form.initial["trimestre"] == services.trimestre_corrente()})


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
    return redirect(_ritorno_gestione(request) or reverse("contatori:macchina", args=[macchina_id]))


@richiede_gestione
def lettura_mensile_edit(request, pk):
    """Correzione di una lettura mensile (i 4 contatori)."""
    from .forms import LetturaMensileForm
    lettura = get_object_or_404(LetturaMensileContatori.objects.select_related("macchina"), pk=pk)
    ritorno = _ritorno_gestione(request)
    if request.method == "POST":
        form = LetturaMensileForm(request.POST, instance=lettura)
        if form.is_valid():
            lettura = form.save()
            if set(services.CAMPI) & set(form.changed_data):
                services.azzera_calo_spiegato(lettura)
            log_action(request, "lettura_mensile_modificata", "contatori", oggetto=lettura,
                       dettaglio={"mese": f"{lettura.mese:%Y-%m}", "totale": lettura.totale,
                                  "calo_confermato": form.cleaned_data.get("conferma_calo", False)})
            messages.success(request, f"Lettura {lettura.mese:%m/%Y} di {lettura.macchina.reparto} salvata.")
            return redirect(ritorno or reverse("contatori:macchina", args=[lettura.macchina_id]))
    else:
        form = LetturaMensileForm(instance=lettura)
    return render(request, "contatori/lettura_mensile_form.html",
                  {"form": form, "lettura": lettura, "ritorno": ritorno})


@richiede_gestione
@require_POST
def lettura_mensile_elimina(request, pk):
    lettura = get_object_or_404(LetturaMensileContatori.objects.select_related("macchina"), pk=pk)
    macchina_id = lettura.macchina_id
    log_action(request, "lettura_mensile_eliminata", "contatori", oggetto=lettura,
               dettaglio={"mese": f"{lettura.mese:%Y-%m}", "totale": lettura.totale})
    lettura.delete()
    messages.success(request, "Lettura mensile eliminata.")
    return redirect(_ritorno_gestione(request) or reverse("contatori:macchina", args=[macchina_id]))


_TIPI_GESTIONE = {"trimestrali": LetturaContatori, "mensili": LetturaMensileContatori}
_TIPI_CALO = {"trimestrale": LetturaContatori, "mensile": LetturaMensileContatori}


@richiede_gestione
@require_POST
def lettura_calo_spiegato(request, tipo, pk):
    """Segna il calo di una lettura come spiegato (azzeramento o sostituzione), con il motivo."""
    modello = _TIPI_CALO.get(tipo)
    if modello is None:
        return redirect("contatori:dashboard")
    lettura = get_object_or_404(modello.objects.select_related("macchina"), pk=pk)
    motivo = (request.POST.get("motivo") or "").strip()
    if not motivo:
        messages.error(request, "Scrivi il motivo del calo (es. «contatore azzerato dal tecnico»).")
        return redirect(reverse("contatori:dashboard") + "#cali")
    services.segna_calo_spiegato(lettura, motivo=motivo, utente=request.user)
    periodo = f"{lettura.mese:%m/%Y}" if tipo == "mensile" else lettura.trimestre
    log_action(request, "lettura_calo_spiegato", "contatori", oggetto=lettura,
               dettaglio={"tipo": tipo, "periodo": periodo, "motivo": lettura.calo_spiegato_motivo,
                          "matricola": lettura.macchina.matricola})
    messages.success(request, f"Calo della lettura {periodo} di {lettura.macchina.reparto} segnato come spiegato.")
    return redirect(reverse("contatori:dashboard") + "#cali")


@richiede_gestione
def letture_gestisci(request):
    """Elenco unico delle letture (trimestrali o mensili) da correggere o eliminare, anche in blocco."""
    tipo = request.POST.get("tipo") or request.GET.get("tipo") or "trimestrali"
    if tipo not in _TIPI_GESTIONE:
        tipo = "trimestrali"
    if request.method == "POST":
        ids = [int(i) for i in request.POST.getlist("lettura") if i.isdigit()]
        letture = list(_TIPI_GESTIONE[tipo].objects.filter(pk__in=ids).select_related("macchina"))
        if letture:
            log_action(request, "letture_eliminate", "contatori", dettaglio={
                "tipo": tipo, "eliminate": len(letture),
                "letture": [f"{l.macchina.matricola} {l.mese:%Y-%m}" if tipo == "mensili"
                            else f"{l.macchina.matricola} {l.trimestre}" for l in letture][:200]})
            _TIPI_GESTIONE[tipo].objects.filter(pk__in=[l.pk for l in letture]).delete()
            messages.success(request, f"{len(letture)} letture eliminate.")
        else:
            messages.info(request, "Nessuna lettura selezionata.")
        return redirect(_ritorno_gestione(request) or f"{reverse('contatori:letture_gestisci')}?tipo={tipo}")
    macchina_id = request.GET.get("macchina", "")
    macchina_id = int(macchina_id) if macchina_id.isdigit() else None
    anno = request.GET.get("anno", "")
    anno = int(anno) if anno.isdigit() else None
    solo_cali = request.GET.get("cali") == "1"
    from core.paginazione import pagina_elenco

    righe = services.elenco_letture_gestione(tipo, macchina_id=macchina_id, anno=anno, solo_cali=solo_cali)
    if _vuole_excel(request):
        from . import export
        return _xlsx_response(export.letture_gestione_xlsx(tipo, righe), f"letture_{tipo}.xlsx")
    # A pagine: nel browser fm-table-enhanced carica le successive scorrendo (o tutte se si cerca).
    page_obj = pagina_elenco(request, righe)
    return render(request, "contatori/letture_gestisci.html", {
        "tipo": tipo, "righe": page_obj, "page_obj": page_obj, "totale": len(righe),
        "macchina_id": macchina_id, "anno": anno, "solo_cali": solo_cali,
        "macchine": Macchina.objects.order_by("-attiva", "reparto", "matricola"),
        "anni": services.anni_letture(),
        "qui": request.get_full_path(),
        "con_cali": sum(1 for r in righe if r["cali"]),
        "url_excel": _url_excel(request),
    })


@richiede_gestione
def leggi_snmp(request):
    """Legge via SNMP le MFC attive con host e salva la lettura del trimestre corrente.

    Non sovrascrive mai una lettura manuale o da fattura e non salva valori piu'
    bassi dell'ultima lettura salvata (contatore azzerato, lettura precedente
    sbagliata): in entrambi i casi la macchina viene solo segnalata. Matricola
    diversa o somma oltre le pagine totali sono scartate da interroga_macchina.
    """
    if request.method != "POST":
        return redirect("contatori:dashboard")
    esito = services.salva_letture_trimestrali_snmp()
    trimestre, lette = esito["trimestre"], esito["lette"]
    manuali, incoerenti, errori = esito["manuali"], esito["incoerenti"], esito["errori"]
    log_action(request, "letture_snmp", "contatori", dettaglio={
        "trimestre": trimestre, "lette": lette, "manuali": len(manuali),
        "incoerenti": len(incoerenti), "errori": len(errori)})
    if lette:
        messages.success(request, f"{lette} MFC lette via SNMP per il {trimestre}.")
    if manuali:
        messages.info(request, "Non sovrascritte (lettura manuale già presente): " + ", ".join(manuali) + ".")
    if incoerenti:
        messages.warning(request, "Valori più bassi dell'ultima lettura salvata, non salvati: "
                         + ", ".join(incoerenti) + ". Il dettaglio è nella salute SNMP della MFC.")
    if errori:
        messages.error(request, "Non lette: " + "; ".join(errori[:10])
                       + (f" e altre {len(errori) - 10}." if len(errori) > 10 else "."))
    if not (lette or manuali or incoerenti or errori):
        messages.info(request, "Nessuna MFC attiva con indirizzo IP da leggere.")
    return redirect("contatori:dashboard")


# --- Gestione stampanti & SNMP ---------------------------------------------

def impostazioni(request):
    """Parametri SNMP globali (singleton) e intervalli/storico della videosorveglianza."""
    # Con il sistema dei ruoli acceso decide l'azione «impostazioni» della matrice.
    from core.permessi.impostazioni import impostazioni_o

    from .permessi import nega, puo_gestire

    if not impostazioni_o(request, "contatori", puo_gestire):
        return nega(request)
    cfg = ImpostazioniSNMP.get_solo()
    if request.method == "POST":
        form = ImpostazioniSNMPForm(request.POST, instance=cfg)
        if form.is_valid():
            prima = model_to_dict(ImpostazioniSNMP.objects.get(pk=cfg.pk), fields=["port", "timeout", "version",
                                                                                 "tvcc_intervallo_nvr",
                                                                                 "tvcc_intervallo_telecamere",
                                                                                 "tvcc_retention_giorni"])
            form.save()
            # La community non finisce nell'audit: si registra solo che e' cambiata.
            log_action(request, "impostazioni_snmp_salvate", "contatori",
                       {"prima": prima, "community_cambiata": "community" in form.changed_data,
                        "campi": [c for c in form.changed_data if c != "community"]})
            messages.success(request, "Parametri SNMP salvati.")
            return redirect("contatori:impostazioni")
    else:
        form = ImpostazioniSNMPForm(instance=cfg)
    in_chiaro = sum(1 for o in (*Macchina.objects.filter(attiva=True, host__isnull=False)
                                .select_related("profilo_snmp", "community_salvata"),
                                *services.dispositivi_senza_doppioni(DispositivoSNMP.objects.filter(attivo=True))
                                .select_related("profilo_snmp", "community_salvata"))
                    if integrazione.postura_snmp(o))
    return render(request, "contatori/impostazioni.html", {
        "snmp_form": form, "cfg": cfg, "apparati_in_chiaro": in_chiaro,
        "profili_mfc": [
            profilo for profilo in ProfiloSNMP.objects.filter(
                attivo=True, categoria=ProfiloSNMP.Categoria.STAMPANTE,
            ).prefetch_related("colonne")
            if len({c.contatore_mfc for c in profilo.colonne.all() if c.contatore_mfc}) == 4
        ],
    })


def macchine_list(request):
    """Elenco stampanti MFC con filtri; i parametri SNMP globali stanno in «Impostazioni»."""
    from django.db.models import Q
    trimestre = services.trimestre_corrente()
    filtri = {k: request.GET.get(k, "").strip() for k in ("q", "stato", "lettura", "dismesse")}
    qs = Macchina.objects.select_related("asset", "profilo_snmp")
    dismesse_nascoste = 0 if filtri["dismesse"] == "1" else qs.filter(attiva=False).count()
    if filtri["dismesse"] != "1":
        qs = qs.filter(attiva=True)
    if filtri["q"]:
        q = filtri["q"]
        qs = qs.filter(Q(reparto__icontains=q) | Q(matricola__icontains=q) | Q(contratto__icontains=q)
                       | Q(modello__icontains=q) | Q(host__icontains=q) | Q(asset__asset_tag__icontains=q))
    if filtri["stato"] in StatoSNMP.values:
        qs = qs.filter(snmp_stato=filtri["stato"])
    con_lettura = set(LetturaContatori.objects.filter(trimestre=trimestre)
                      .values_list("macchina_id", flat=True))
    macchine = list(qs.order_by("-attiva", "reparto"))
    if filtri["lettura"] == "mancante":
        macchine = [m for m in macchine if m.pk not in con_lettura]
    elif filtri["lettura"] == "presente":
        macchine = [m for m in macchine if m.pk in con_lettura]
    elif filtri["lettura"] == "mensile_mancante":
        # Stesso criterio della voce «letture mensili in attesa / saltate» della Centrale.
        mancanti = {m.pk for m in services.mensili_mancanti()}
        macchine = [m for m in macchine if m.pk in mancanti]
    consumabili = services.stato_consumabili(macchine)
    if _vuole_excel(request):
        from . import export
        return _xlsx_response(export.macchine_xlsx(macchine, trimestre=trimestre, con_lettura=con_lettura,
                                                   consumabili=consumabili), "stampanti_mfc.xlsx")
    return render(request, "contatori/macchine.html", {
        "macchine": macchine, "filtri": filtri, "trimestre": trimestre, "con_lettura": con_lettura,
        "url_excel": _url_excel(request),
        "dismesse_nascoste": dismesse_nascoste, "stati": StatoSNMP.choices,
        "mese_corrente": timezone.localdate().replace(day=1),
        "filtrato": any(filtri[k] for k in ("q", "stato", "lettura")),
        "consumabili": consumabili,
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
            if pk is None and m.asset_id is None:
                # Come per i dispositivi SNMP: nuova MFC collegata all'asset con la stessa matricola o lo stesso IP.
                proposta = _asset_proposto(m, "mfc")
                if proposta is not None:
                    m.asset = proposta["asset"]
                    m.save(update_fields=["asset"])
                    log_action(request, "apparato_collegato_asset", "contatori",
                               {"tipo": "mfc", "apparato_id": m.pk, "asset_id": m.asset_id,
                                "asset_tag": m.asset.asset_tag, "motivo": proposta["motivo"], "automatico": True})
                    messages.info(request, f"Collegata all'asset {m.asset.asset_tag} (trovato per {proposta['motivo']}).")
            return redirect("contatori:macchina", pk=m.pk)
    else:
        form = MacchinaForm(instance=macchina)
    return render(request, "contatori/macchina_form.html",
                  {"form": form, "macchina": macchina})


def _vuole_excel(request):
    """«Scarica Excel» delle pagine elenco: stessa view e stessi filtri, ?formato=xlsx."""
    return request.GET.get("formato") == "xlsx"


def _url_excel(request):
    """URL della pagina corrente (filtri compresi, senza la pagina dell'elenco) con ?formato=xlsx."""
    parametri = request.GET.copy()
    parametri.pop("page", None)
    parametri["formato"] = "xlsx"
    return f"{request.path}?{parametri.urlencode()}"


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


def export_macchina(request, pk):
    from . import export
    macchina = get_object_or_404(Macchina, pk=pk)
    wb = export.storico_macchina_xlsx(macchina)
    return _xlsx_response(wb, f"contatori_{macchina.matricola}.xlsx")


CONTATORI_FORM = ("a4_bn", "a3_bn", "a4_col", "a3_col")


def _riga_vuota(form):
    return not any((form.data.get(form.add_prefix(c)) or "").strip() for c in CONTATORI_FORM)


@richiede_gestione
def letture_trimestre(request):
    """Inserimento delle letture di un trimestre per tutte le MFC attive in una pagina.

    Ogni riga e' un LetturaForm (stessi controlli della pagina singola: data nel
    trimestre, contatori che non scendono salvo conferma, niente doppioni). Le righe
    lasciate vuote si saltano; si salvano le righe valide e quelle con errori restano
    in pagina da correggere.
    """
    from .forms import LetturaForm
    oggi = timezone.localdate()
    trimestre = request.POST.get("trimestre") or request.GET.get("trimestre") or ""
    if not services.trimestre_valido(trimestre):
        trimestre = services.trimestre_precedente(services.trimestre_corrente())
    inizio, fine = services.limiti_trimestre(trimestre)
    # Trimestre chiuso: la lettura di chiusura e' quella dei giorni dopo la fine.
    data_default = fine if fine <= oggi else oggi
    presenti = {l.macchina_id: l for l in LetturaContatori.objects.filter(trimestre=trimestre)}
    precedenti = {}
    for l in LetturaContatori.objects.filter(trimestre__lt=trimestre).order_by("trimestre"):
        precedenti[l.macchina_id] = l
    righe, salvate = [], []
    for m in Macchina.objects.filter(attiva=True).order_by("reparto", "matricola"):
        riga = {"macchina": m, "esistente": presenti.get(m.pk), "precedente": precedenti.get(m.pk)}
        if riga["esistente"] is None:
            prefix = f"m{m.pk}"
            if request.method == "POST":
                dati = request.POST.copy()
                dati[f"{prefix}-macchina"] = str(m.pk)
                dati[f"{prefix}-trimestre"] = trimestre
                form = LetturaForm(dati, prefix=prefix)
                if not _riga_vuota(form) and form.is_valid():
                    lettura = form.save()
                    salvate.append(lettura)
                    log_action(request, "lettura_creata", "contatori", oggetto=lettura,
                               dettaglio={"trimestre": trimestre, "fonte": lettura.fonte, "massivo": True,
                                          "calo_confermato": form.cleaned_data.get("conferma_calo", False)})
                    riga["esistente"] = lettura
                    form = None
            else:
                form = LetturaForm(prefix=prefix, initial={
                    "macchina": m.pk, "trimestre": trimestre, "data": data_default,
                    "fonte": LetturaContatori.Fonte.MANUALE,
                    # Campi vuoti, non 0: una riga non compilata non deve sembrare una lettura.
                    **{c: "" for c in CONTATORI_FORM}})
            riga["form"] = form
        righe.append(riga)
    if request.method == "POST":
        errate = [r for r in righe if r.get("form") is not None and not _riga_vuota(r["form"])]
        if salvate:
            messages.success(request, f"{len(salvate)} letture {trimestre} salvate.")
        if errate:
            messages.error(request, f"{len(errate)} righe non salvate: correggi i valori evidenziati.")
        elif not salvate:
            messages.info(request, "Nessuna lettura inserita: compila almeno una riga.")
        if not errate:
            return redirect(f"{reverse('contatori:letture_trimestre')}?trimestre={trimestre}")
    return render(request, "contatori/letture_trimestre.html", {
        "trimestre": trimestre, "righe": righe, "inizio": inizio, "fine": fine,
        "trimestri": services.opzioni_trimestri(indietro=16, extra=[trimestre]),
        "da_inserire": sum(1 for r in righe if r.get("form") is not None),
    })


def letture_registro(request):
    """Registro letture: MFC x trimestri, con mancanti, cali e copie del trimestre."""
    try:
        n = min(max(int(request.GET.get("trimestri", 8)), 4), 16)
    except ValueError:
        n = 8
    dismesse = request.GET.get("dismesse") == "1"
    registro = services.registro_letture(n, dismesse=dismesse)
    if _vuole_excel(request):
        from . import export
        return _xlsx_response(export.registro_letture_xlsx(registro), "registro_letture.xlsx")
    return render(request, "contatori/letture_registro.html", {
        "registro": registro, "n": n, "dismesse": dismesse, "url_excel": _url_excel(request),
    })


def letture_mensili(request):
    """Letture mensili per mese: MFC × 12 mesi dell'anno scelto, mancanti in evidenza, Excel della mail."""
    oggi = timezone.localdate()
    anni = sorted({d.year for d in LetturaMensileContatori.objects.dates("mese", "year")} | {oggi.year},
                  reverse=True)
    anno = request.GET.get("anno", "")
    anno = int(anno) if anno.isdigit() and int(anno) in anni else None
    mese_xlsx = request.GET.get("mese", "")
    if _vuole_excel(request) and mese_xlsx:
        # Lo stesso Excel allegato alla mail mensile (mail_mensile.riepilogo + export.letture_mensili_xlsx).
        from datetime import date

        from . import export
        from .mail_mensile import riepilogo
        try:
            a, m = (int(x) for x in mese_xlsx.split("-"))
            primo = date(a, m, 1)
        except ValueError:
            return redirect("contatori:letture_mensili")
        return _xlsx_response(export.letture_mensili_xlsx(riepilogo(primo)), f"letture_mfc_{primo:%Y-%m}.xlsx")
    return render(request, "contatori/letture_mensili.html", {
        **services.letture_mensili_per_mese(anno=anno, oggi=oggi), "anni": anni, "anno": anno,
    })


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


_VISTE_LETTURA = {"asset", "macchina", "riga"}


def _nega_lettura(request):
    """«Leggi ora» scrive nello storico: serve la gestione. JSON/fragment 403, mai redirect."""
    from django.http import JsonResponse

    if (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest":
        return JsonResponse({"ok": False, "error": "Permesso «Contatori - Gestione» richiesto."}, status=403)
    return HttpResponse('<p class="af-note" role="status">Serve il permesso «Contatori - Gestione» per leggere adesso.</p>',
                        status=403)


def _frammento_lettura(request, macchina, vista):
    """Stato della lettura richiesta: in coda (il frammento si ri-interroga) o conclusa (dati salvati)."""
    from . import lettura_ora

    stato = lettura_ora.stato(macchina.pk) or {"stato": lettura_ora.OK}
    salvato = services.stato_consumabili([macchina]).get(macchina.pk)
    ctx = {
        "macchina": macchina, "vista": vista, "lettura": stato,
        "in_coda": stato["stato"] == lettura_ora.IN_CODA,
        "fallita": stato["stato"] == lettura_ora.ERRORE,
        "stato_url": reverse("contatori:macchina_consumabili", args=[macchina.pk]) + f"?vista={vista}",
        "scaduta": stato.get("scaduta", False),
        "salvato": salvato, "soglia": services.SOGLIA_CONSUMABILE_PCT,
    }
    if vista == "riga":
        ctx["r"] = _riga_consumabili(macchina, salvato)
        return render(request, "contatori/_consumabili_riga.html", ctx)
    return render(request, "contatori/_lettura_ora.html", ctx)


@require_http_methods(["GET", "POST"])
def macchina_consumabili(request, pk):
    """«Leggi ora»: POST accoda il job di lettura (niente SNMP nella request), GET ne
    segue lo stato (polling HTMX, sola lettura: stessa route e stesso binding ACL)."""
    from . import lettura_ora
    from .permessi import puo_gestire

    if request.method == "GET":
        macchina = get_object_or_404(Macchina, pk=pk)
        vista = request.GET.get("vista") if request.GET.get("vista") in _VISTE_LETTURA else "macchina"
        return _frammento_lettura(request, macchina, vista)
    if not puo_gestire(request):
        return _nega_lettura(request)
    macchina = get_object_or_404(Macchina, pk=pk)
    vista = "asset" if request.POST.get("asset_inline") == "1" else "macchina"
    if not macchina.host or not macchina.attiva:
        return HttpResponse('<p class="af-note" role="status">Lettura non disponibile: MFC disattivata o senza IP.</p>')
    lettura_ora.accoda(macchina)
    log_action(request, "contatori_consumabili_leggi_ora", "contatori", {"macchina_id": macchina.pk})
    return _frammento_lettura(request, macchina, vista)


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
    from . import lettura_ora

    macchine = list(Macchina.objects.filter(attiva=True, host__isnull=False))
    stati = services.stato_consumabili(macchine)
    righe = sorted((_riga_consumabili(m, stati.get(m.pk)) for m in macchine), key=lambda r: r["ordine"])
    # Dopo «Leggi ora le selezionate» le righe in coda seguono lo stato come quella del «Leggi ora» singolo.
    in_coda = lettura_ora.in_coda([m.pk for m in macchine])
    for r in righe:
        r["in_coda"] = r["macchina"].pk in in_coda
        r["stato_url"] = reverse("contatori:macchina_consumabili", args=[r["macchina"].pk]) + "?vista=riga"

    def critica(r):
        return bool(r["stato"] and r["stato"]["critici"])

    def non_recente(r):
        return r["stato"] is None or not r["stato"]["recente"]

    # Stessa funzione della Centrale e della pagina «Fabbisogno»: i numeri coincidono.
    entro_30 = services.fabbisogno_consumabili(macchine, stati)["entro_30"]

    def in_esaurimento(r):
        return r["macchina"].pk in entro_30

    filtri = {"critici": critica, "non_recenti": non_recente, "entro_30": in_esaurimento}
    critici = sum(1 for r in righe if critica(r))
    non_recenti = sum(1 for r in righe if non_recente(r))
    filtro = request.GET.get("filtro") if request.GET.get("filtro") in filtri else ""
    totale = len(righe)
    if filtro:
        righe = [r for r in righe if filtri[filtro](r)]
    if _vuole_excel(request):
        from . import export
        return _xlsx_response(export.consumabili_xlsx(righe), "consumabili.xlsx")
    return render(request, "contatori/consumabili.html", {
        "righe": righe, "totale": totale, "filtro": filtro,
        "critici": critici, "entro_30": len(entro_30), "giorni_esaurimento": services.FABBISOGNO_GIORNI[0],
        "url_excel": _url_excel(request),
        "non_recenti": non_recenti,
        "soglia": services.SOGLIA_CONSUMABILE_PCT,
        "giorni_recente": services.CONSUMABILI_RECENTE_GIORNI,
    })


def consumabili_fabbisogno(request):
    """Fabbisogno per consumabile: MFC che lo usano, durata media, pezzi all'anno, in esaurimento."""
    dati = services.fabbisogno_consumabili()
    if _vuole_excel(request):
        from . import export
        return _xlsx_response(export.fabbisogno_xlsx(dati), "fabbisogno_consumabili.xlsx")
    return render(request, "contatori/consumabili_fabbisogno.html", {
        **dati, "url_excel": _url_excel(request),
    })


@require_POST
def consumabili_aggiorna(request, pk):
    """«Leggi ora» di una riga della flotta: job in coda, la riga segue lo stato (HTMX)."""
    from . import lettura_ora
    from .permessi import puo_gestire

    if not puo_gestire(request):
        return _nega_lettura(request)
    macchina = get_object_or_404(Macchina, pk=pk, attiva=True)
    lettura_ora.accoda(macchina)
    log_action(request, "contatori_consumabili_leggi_ora", "contatori", {"macchina_id": macchina.pk})
    return _frammento_lettura(request, macchina, "riga")


def macchina_consumabili_riepilogo(request, pk):
    """Frammento compatto per la vista flotta: peggior livello + critici (≤15%)."""
    # Solo l'ultima lettura salvata: un GET non interroga la stampante e non scrive.
    macchina = get_object_or_404(Macchina, pk=pk)
    stato = services.stato_consumabili([macchina]).get(macchina.pk)
    riepilogo = None
    errore = "" if stato else "nessuna lettura salvata"
    if stato:
        riepilogo = {
            "peggiore": stato["peggiore"],
            "critici": stato["critici"],
            "n_totali": len(stato["voci"]),
        }
    return render(request, "contatori/_consumabili_riepilogo.html",
                  {"riepilogo": riepilogo, "errore": errore, "macchina": macchina})


@richiede_gestione
@require_POST
def macchina_test_snmp(request, pk):
    """Testa la lettura SNMP di una macchina; ritorna il frammento con l'esito."""
    from .snmp import SNMPError
    macchina = get_object_or_404(Macchina, pk=pk)
    valori, errore, incoerenze = None, None, []
    try:
        valori = services.interroga_macchina(macchina)
        incoerenze = services.incoerenze_lettura(macchina, valori)
    except SNMPError as e:
        errore = str(e)
    return render(request, "contatori/_snmp_result.html",
                  {"valori": valori, "errore": errore, "incoerenze": incoerenze, "macchina": macchina})


# --- Centrale dispositivi e lettori SNMP ----------------------------------

_FLOTTA_DA_STATO = {StatoSNMP.ERROR: "errore", StatoSNMP.WARNING: "attenzione", StatoSNMP.OK: "ok",
                    StatoSNMP.MAI: "non_interrogati"}


def snmp_centrale(request):
    categoria = (request.GET.get("categoria") or "").strip().upper()
    flotta = (request.GET.get("flotta") or "").strip()
    # Vecchi link con lo stato grezzo (?stato=ERROR): stessa categoria dei riquadri.
    flotta = flotta or _FLOTTA_DA_STATO.get((request.GET.get("stato") or "").strip().upper(), "")
    # Una stampante che è anche MFC a contratto compare una volta sola: come MFC.
    dispositivi = services.dispositivi_senza_doppioni(DispositivoSNMP.objects.select_related("asset"))
    macchine = Macchina.objects.filter(attiva=True).select_related("asset")
    if flotta in services.FLOTTA:
        # Stesso criterio del riquadro della Centrale: lista e conteggio coincidono.
        mfc_monitorate, disp_monitorati = services.flotta_monitorata()
        dispositivi = services.filtra_flotta(dispositivi.filter(pk__in=disp_monitorati), flotta)
        macchine = services.filtra_flotta(macchine.filter(pk__in=mfc_monitorate), flotta)
    else:
        flotta = ""
    if categoria == "TVCC":
        # Videosorveglianza: NVR e telecamere insieme.
        dispositivi = dispositivi.filter(categoria__in=DispositivoSNMP.CATEGORIE_TVCC)
    elif categoria in DispositivoSNMP.Categoria.values:
        dispositivi = dispositivi.filter(categoria=categoria)
    # Le MFC sono stampanti: una categoria diversa le esclude, invece di mostrarle comunque.
    if categoria and categoria != DispositivoSNMP.Categoria.STAMPANTE:
        macchine = macchine.none()
    q = (request.GET.get("q") or "").strip()
    if q:
        from django.db.models import Q
        dispositivi = dispositivi.filter(
            Q(nome__icontains=q) | Q(host__icontains=q) | Q(posizione__icontains=q)
            | Q(asset__asset_tag__icontains=q) | Q(asset__name__icontains=q))
        macchine = macchine.filter(Q(reparto__icontains=q) | Q(matricola__icontains=q)
                                   | Q(host__icontains=q) | Q(modello__icontains=q)
                                   | Q(asset__asset_tag__icontains=q) | Q(asset__name__icontains=q))
    dispositivi = list(dispositivi)
    disponibilita = services.disponibilita_flotta(d.pk for d in dispositivi)
    if _vuole_excel(request):
        from . import export
        return _xlsx_response(export.monitor_snmp_xlsx(dispositivi, list(macchine.order_by("reparto")), disponibilita),
                              "monitor_snmp.xlsx")
    return render(request, "contatori/snmp_centrale.html", {
        "dispositivi": dispositivi, "q": q, "filtrato": bool(q or categoria or flotta),
        "url_excel": _url_excel(request),
        "da_interrogare": services.dispositivi_senza_doppioni(DispositivoSNMP.objects.filter(attivo=True)).count(),
        "disponibilita": disponibilita,
        "macchine": macchine,
        "flotta": flotta, "flotta_etichetta": services.FLOTTA.get(flotta, ""),
        "riepilogo": services.centrale_snmp_riepilogo(),
        "flotta_giorni": services.SNMP_NON_INTERROGATO_GIORNI,
        "categoria": categoria,
        "categorie": [("TVCC", "Videosorveglianza (NVR e telecamere)"), *DispositivoSNMP.Categoria.choices],
        "stati_flotta": list(services.FLOTTA.items()),
    })


def dispositivo_snmp_detail(request, pk):
    dispositivo = get_object_or_404(
        DispositivoSNMP.objects.select_related("asset", "profilo_snmp", "community_salvata"), pk=pk,
    )
    mfc = services.mfc_dello_stesso_apparato(dispositivo)
    if mfc is not None and request.GET.get("tecnico") != "1":
        # Stessa stampante della MFC a contratto: una scheda sola, quella della MFC.
        return redirect("contatori:macchina", pk=mfc.pk)
    from core.paginazione import pagina_elenco

    ultima_rilevazione = dispositivo.rilevazioni.first()
    stato_storico = (request.GET.get("stato") or "").strip().upper()
    storico = dispositivo.rilevazioni.prefetch_related("valori__sonda")
    if stato_storico in (StatoSNMP.OK, StatoSNMP.WARNING, StatoSNMP.ERROR):
        storico = storico.filter(stato=stato_storico)
    else:
        stato_storico = ""
    rilevazioni_pagina = pagina_elenco(request, storico, per_pagina=50)
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
    stampante = dispositivo.categoria == DispositivoSNMP.Categoria.STAMPANTE
    dati_extra = {}
    if stampante:
        from .stampanti import stime

        ultima = ultima_rilevazione
        dati_extra = {**contesto_pannello(dispositivo, ultima.dati_stampante if ultima else {}),
                      "stime_stampante": stime(dispositivo)}
        per_indice = {r["indice"]: r for r in dati_extra["stime_stampante"]["consumabili"]}
        for c in ((ultima.dati_stampante or {}).get("consumabili") or []) if ultima else []:
            c["stima"] = per_indice.get(c.get("indice"))  # solo in memoria, non si salva
    disponibilita = services.disponibilita_dispositivo(dispositivo)
    from .presentazione import vista as vista_apparato

    return render(request, "contatori/snmp_dispositivo_detail.html", {
        **dati_extra,
        # Layout del suo tipo (UPS, firewall, switch, server, NAS, NVR…): solo dati già in memoria, nessuna query in più.
        "vista": vista_apparato(dispositivo, sonde, ultima=ultima_rilevazione, disponibilita=disponibilita, request=request),
        # Disegno dell'apparato: pannello delle porte (firewall, switch) o stampante, dai dati salvati.
        **_disegno(dispositivo, ultima_rilevazione),
        "dispositivo": dispositivo,
        "sonde": sonde,
        "rilevazioni": rilevazioni_pagina.object_list,
        "rilevazioni_pagina": rilevazioni_pagina,
        "stato_storico": stato_storico,
        "stati_storico": [(StatoSNMP.OK, "Operativo"), (StatoSNMP.WARNING, "Attenzione"), (StatoSNMP.ERROR, "Errore")],
        "profili_disponibili": ProfiloSNMP.objects.filter(attivo=True),
        "ultima_rilevazione": ultima_rilevazione,
        "stampante": stampante,
        "info_snmp": services.info_snmp(dispositivo),
        "ultima_ok": dispositivo.rilevazioni.filter(stato=StatoSNMP.OK).order_by("-rilevata_il").first(),
        "ultima_ko": dispositivo.rilevazioni.filter(stato=StatoSNMP.ERROR).order_by("-rilevata_il").first(),
        **_licenze_software_asset(dispositivo.asset, dispositivo, "snmp", request),
        "firmware_storico": list(dispositivo.firmware_storico.all()[:20]),
        "disponibilita": disponibilita,
        "periodi_disponibilita": (("24h", "ultime 24 ore"), ("7g", "ultimi 7 giorni")),
        **_porte_switch(dispositivo),
    })


def _disegno(dispositivo, ultima):
    from .presentazione import disegno_stampante
    from .topologia import pannello

    if dispositivo.categoria in (DispositivoSNMP.Categoria.FIREWALL, DispositivoSNMP.Categoria.RETE):
        return pannello(dispositivo)
    if dispositivo.categoria == DispositivoSNMP.Categoria.STAMPANTE:
        return {"disegno_mfc": disegno_stampante(ultima.dati_stampante if ultima else {}, dispositivo.snmp_stato)}
    return {}


def _porte_switch(dispositivo):
    """Tabella MAC dello switch («Rete»): PC riconosciuti sulle porte d'accesso (contatori.tabella_mac)."""
    if dispositivo.categoria != DispositivoSNMP.Categoria.RETE:
        return {}
    from .tabella_mac import collegati_allo_switch

    righe = collegati_allo_switch(dispositivo)
    ultima = dispositivo.mac_porte.order_by("-letto_il").values_list("letto_il", flat=True).first()
    return {"porte_switch": righe, "porte_switch_letto": ultima, "porte_switch_mac": dispositivo.mac_porte.count(),
            "porte_switch_riconosciuti": sum(1 for r in righe if r["asset"])}


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
            if pk is None:
                # Creato senza test di connessione: «non verificato» fino alla prima lettura riuscita.
                dispositivo.verificato = False
                dispositivo.save(update_fields=["verificato"])
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


@richiede_gestione
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


@richiede_gestione
@require_POST
def dispositivi_snmp_interroga_tutti(request):
    """Accoda un'interrogazione per ogni dispositivo attivo (stesso job del monitor): niente SNMP nella request."""
    from .tasks import _enqueue

    pks = list(services.dispositivi_senza_doppioni(DispositivoSNMP.objects.filter(attivo=True))
               .values_list("pk", flat=True))
    # Il lock di coda salta chi e' gia' in coda: non si accumulano doppioni.
    accodati = sum(_enqueue("contatori.tasks.poll_dispositivo", pk) for pk in pks)
    log_action(request, "snmp_interroga_tutti", "contatori", {"dispositivi": len(pks), "accodati": accodati})
    messages.success(
        request,
        f"Interrogazione avviata per {len(pks)} dispositivi"
        + (f" ({len(pks) - accodati} erano già in coda)" if accodati < len(pks) else "")
        + ": gli stati si aggiornano entro qualche minuto.",
    )
    return redirect("contatori:snmp_centrale")


# --- Topologia e porte degli apparati (contatori.topologia) -----------------------------------------

def topologia(request):
    """Albero della rete dalle porte descritte su firewall e switch: solo dati salvati, nessuna interrogazione."""
    from .topologia import albero

    return render(request, "contatori/topologia.html", {"t": albero()})


@richiede_gestione
def dispositivo_porte(request, pk):
    """Editor delle porte di un firewall o di uno switch: nome, tipo, VLAN, cosa c'è collegato. Proposte dalla tabella MAC."""
    from .models import PortaApparato
    from .topologia import PORTE_DEFAULT, porte_pannello, proposte_da_tabella_mac

    dispositivo = get_object_or_404(DispositivoSNMP, pk=pk)
    candidati_d = list(services.dispositivi_senza_doppioni(DispositivoSNMP.objects.filter(attivo=True).exclude(pk=pk)).order_by("nome"))
    candidati_m = list(Macchina.objects.filter(attiva=True).order_by("reparto"))
    validi = {f"d:{d.pk}" for d in candidati_d} | {f"m:{m.pk}" for m in candidati_m}
    if request.method == "POST":
        try:
            totale = max(0, min(96, int(request.POST.get("porte_totali") or 0)))
        except ValueError:
            totale = dispositivo.porte_totali
        tipi = {c for c, _l in PortaApparato.Tipo.choices}
        esistenti = {p.numero: p for p in dispositivo.porte_disegnate.all()}
        salvate = 0
        with transaction.atomic():
            DispositivoSNMP.objects.filter(pk=pk).update(porte_totali=totale)
            for n in range(1, (totale or PORTE_DEFAULT.get(dispositivo.categoria, 0)) + 1):
                campi = {k: (request.POST.get(f"{k}_{n}") or "").strip() for k in ("nome", "tipo", "vlan", "coll", "testo", "nota")}
                coll = campi["coll"] if campi["coll"] in validi else ""
                vuota = not any((campi["nome"], campi["vlan"], coll, campi["testo"], campi["nota"])) and campi["tipo"] in ("", "LAN")
                if vuota:
                    if n in esistenti:
                        esistenti[n].delete()
                    continue
                PortaApparato.objects.update_or_create(dispositivo=dispositivo, numero=n, defaults={
                    "nome": campi["nome"][:60], "tipo": campi["tipo"] if campi["tipo"] in tipi else "LAN", "vlan": campi["vlan"][:40],
                    "collegato_dispositivo_id": int(coll[2:]) if coll.startswith("d:") else None,
                    "collegato_macchina_id": int(coll[2:]) if coll.startswith("m:") else None,
                    "collegato_testo": "" if coll else campi["testo"][:120], "nota": campi["nota"][:200]})
                salvate += 1
            # Porte oltre il nuovo totale: non si disegnano più, si tolgono.
            if totale:
                dispositivo.porte_disegnate.filter(numero__gt=totale).delete()
        log_action(request, "apparato_porte_salvate", "contatori", {"porte_totali": totale, "porte_descritte": salvate},
                   oggetto_tipo="contatori.dispositivosnmp", oggetto_id=str(pk))
        messages.success(request, f"Porte salvate: {salvate} descritte su {totale or 'quelle predefinite'}.")
        return redirect(reverse("contatori:snmp_dispositivo", args=[pk]) + "#disegno")
    porte = porte_pannello(dispositivo)
    righe_db = {p.numero: p for p in dispositivo.porte_disegnate.all()}
    proposte = proposte_da_tabella_mac(dispositivo)
    for porta in porte:
        p = righe_db.get(porta["numero"])
        porta["coll"] = (f"d:{p.collegato_dispositivo_id}" if p and p.collegato_dispositivo_id else
                         f"m:{p.collegato_macchina_id}" if p and p.collegato_macchina_id else "")
        porta["testo"] = p.collegato_testo if p else ""
        porta["proposta"] = proposte.get(porta["numero"]) if not p else None
    return render(request, "contatori/dispositivo_porte.html", {
        "dispositivo": dispositivo, "porte": porte, "totale_mostrato": len(porte),
        "candidati_d": [{"valore": f"d:{d.pk}", "label": f"{d.nome} · {d.host}"} for d in candidati_d],
        "candidati_m": [{"valore": f"m:{m.pk}", "label": f"MFC {m.reparto}"} for m in candidati_m],
        "tipi": PortaApparato.Tipo.choices, "n_proposte": sum(1 for p in porte if p["proposta"]),
    })
