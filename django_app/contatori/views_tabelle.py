"""Pannello laterale di anteprima e azioni su più righe delle tabelle del modulo Contatori.

- ``anteprima``: frammento per il pannello laterale ([data-preview]) di una MFC o di un
  dispositivo SNMP; stessa route di consultazione delle schede (binding ACL ``contatori.modulo.view``).
- ``consumabili_azioni``: «Leggi ora le selezionate» (serve la gestione, come «Leggi ora» di riga)
  e «Prepara richiesta ordine» (CSV, sola lettura).
- ``macchine_collega_asset``: collega più MFC agli asset proposti, prima l'anteprima poi la conferma.
- ``discovery_correggi_ip``: «Correggi IP» della discovery su più righe.
"""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from . import services
from .models import AvvisoStampante, DispositivoSNMP, LetturaContatori, Macchina
from . import permessi
from .permessi import richiede_gestione

#: Righe massime di un elenco nel pannello: il resto sta nella scheda completa.
_MAX_PANNELLO = 6


def _avvisi_aperti(**chi):
    """Avvisi ancora presenti (non informativi) dell'apparato, i critici prima."""
    qs = (AvvisoStampante.objects.filter(chiuso_il__isnull=True, informativo=False, **chi)
          .order_by("-critico", "-aperto_il"))
    return list(qs[:_MAX_PANNELLO]), qs.count()


def anteprima(request, kind, pk):
    """Frammento del pannello laterale: niente SNMP, solo i dati salvati."""
    if kind == "mfc":
        macchina = get_object_or_404(Macchina.objects.select_related("asset", "profilo_snmp"), pk=pk)
        avvisi, n_avvisi = _avvisi_aperti(macchina=macchina)
        proposta = None
        if macchina.asset_id is None and permessi.puo_gestire(request):
            from .views import _asset_proposto
            proposta = _asset_proposto(macchina, "mfc")
        return render(request, "contatori/partials/preview_macchina.html", {
            "m": macchina,
            "trimestre": services.trimestre_corrente(),
            "ultima": macchina.letture.order_by("-trimestre", "-data").first(),
            "ha_lettura_trimestre": LetturaContatori.objects.filter(
                macchina=macchina, trimestre=services.trimestre_corrente()).exists(),
            "consumabili": services.stato_consumabili([macchina]).get(macchina.pk),
            "soglia": services.SOGLIA_CONSUMABILE_PCT,
            "avvisi": avvisi, "n_avvisi": n_avvisi,
            "proposta": proposta,
        })
    if kind == "snmp":
        dispositivo = get_object_or_404(DispositivoSNMP.objects.select_related("asset", "profilo_snmp"), pk=pk)
        avvisi, n_avvisi = _avvisi_aperti(dispositivo=dispositivo)
        return render(request, "contatori/partials/preview_dispositivo.html", {
            "d": dispositivo,
            "disponibilita": services.disponibilita_dispositivo(dispositivo)["24h"],
            "n_sonde": dispositivo.sonde.count(),
            "mfc": services.mfc_dello_stesso_apparato(dispositivo),
            "avvisi": avvisi, "n_avvisi": n_avvisi,
        })
    raise Http404("Tipo di anteprima sconosciuto")


def _ids(request, nome):
    return [int(v) for v in request.POST.getlist(nome) if v.isdigit()]


def _voci_ordine(stato):
    """Consumabili da ordinare di una MFC: quelli sotto soglia, altrimenti il più basso."""
    if not stato:
        return []
    if stato["critici"]:
        return stato["critici"]
    return [stato["peggiore"]] if stato["peggiore"] else []


@require_POST
def consumabili_azioni(request):
    """Azioni sulle MFC selezionate nella pagina Consumabili."""
    from . import lettura_ora

    azione = request.POST.get("azione", "")
    macchine = list(Macchina.objects.filter(pk__in=_ids(request, "macchina"), attiva=True, host__isnull=False)
                    .order_by("reparto"))
    if azione == "leggi":
        if not permessi.puo_gestire(request):
            return permessi.nega(request)
        for macchina in macchine:
            lettura_ora.accoda(macchina)
        if macchine:
            log_action(request, "contatori_consumabili_leggi_ora", "contatori",
                       {"macchine": [m.pk for m in macchine][:200], "selezionate": len(macchine)})
            messages.success(request, f"Lettura in coda per {len(macchine)} MFC: i livelli si aggiornano "
                                      "nella pagina appena la stampante risponde.")
        else:
            messages.info(request, "Nessuna MFC selezionata.")
        return redirect("contatori:consumabili")
    if azione == "ordine":
        if not macchine:
            messages.info(request, "Nessuna MFC selezionata.")
            return redirect("contatori:consumabili")
        from core.csv_export import csv_download_response

        stati = services.stato_consumabili(macchine)
        response, writer = csv_download_response(
            f"richiesta_ordine_consumabili_{timezone.localdate():%Y%m%d}.csv", delimiter=";")
        writer.writerow(["Modello", "Matricola", "MFC", "Consumabile", "Livello %", "Giorni stimati",
                         "Sotto soglia", "Letto il"])
        for macchina in macchine:
            stato = stati.get(macchina.pk)
            voci = _voci_ordine(stato)
            if not voci:
                writer.writerow([macchina.modello, macchina.matricola, macchina.reparto, "nessuna lettura salvata",
                                 "", "", "", ""])
                continue
            letto = timezone.localtime(stato["rilevata_il"]).strftime("%d/%m/%Y %H:%M")
            for voce in voci:
                writer.writerow([macchina.modello, macchina.matricola, macchina.reparto, voce["nome"],
                                 "" if voce["pct"] is None else voce["pct"],
                                 "" if voce["giorni"] is None else voce["giorni"],
                                 "sì" if voce["critico"] else "no", letto])
        return response
    messages.error(request, "Azione non riconosciuta.")
    return redirect("contatori:consumabili")


@richiede_gestione
@require_POST
def macchine_collega_asset(request):
    """Collega le MFC selezionate agli asset proposti: anteprima degli abbinamenti, poi conferma."""
    from .views import _asset_proposto, _collega_asset

    if request.POST.get("conferma") == "1":
        scelte = {}
        for valore in request.POST.getlist("abbina"):
            mac, _, asset = valore.partition(":")
            if mac.isdigit() and asset.isdigit():
                scelte[int(mac)] = asset
        collegate, saltate = [], []
        for macchina in Macchina.objects.filter(pk__in=scelte).order_by("reparto"):
            proposta = _asset_proposto(macchina, "mfc") if macchina.asset_id is None else None
            # Solo se la proposta è ancora quella mostrata nell'anteprima, come l'azione singola.
            if proposta is None or str(proposta["asset"].pk) != scelte[macchina.pk]:
                saltate.append(macchina.reparto)
                continue
            asset = _collega_asset(request, macchina, "mfc", proposta)
            collegate.append(f"{macchina.reparto} → {asset.asset_tag}")
        if collegate:
            messages.success(request, f"{len(collegate)} MFC collegate: " + ", ".join(collegate[:10])
                             + (f" e altre {len(collegate) - 10}." if len(collegate) > 10 else "."))
        if saltate:
            messages.warning(request, "Non collegate (già collegate o proposta cambiata): " + ", ".join(saltate) + ".")
        if not (collegate or saltate):
            messages.info(request, "Nessun collegamento confermato.")
        return redirect("contatori:macchine")
    righe = []
    for macchina in Macchina.objects.filter(pk__in=_ids(request, "macchina")).select_related("asset").order_by("reparto"):
        if macchina.asset_id is not None:
            righe.append({"macchina": macchina, "proposta": None, "esito": "collegata"})
            continue
        proposta = _asset_proposto(macchina, "mfc")
        righe.append({"macchina": macchina, "proposta": proposta, "esito": "proposta" if proposta else "nessuna"})
    if not righe:
        messages.info(request, "Nessuna MFC selezionata.")
        return redirect("contatori:macchine")
    return render(request, "contatori/macchine_collega_asset.html", {
        "righe": righe, "da_collegare": sum(1 for r in righe if r["proposta"]),
    })


@richiede_gestione
@require_POST
def discovery_correggi_ip(request):
    """«Correggi IP» su più righe della discovery: stesso salvataggio dell'azione singola."""
    from .views import _applica_ip

    coppie = {}
    for valore in request.POST.getlist("correggi"):
        mac, _, host = valore.partition("|")
        if mac.isdigit() and host.strip():
            coppie[int(mac)] = host.strip()
    corrette, errate = [], []
    for macchina in Macchina.objects.filter(pk__in=coppie).order_by("reparto"):
        host = coppie[macchina.pk]
        prima = macchina.host
        if _applica_ip(macchina, host):
            corrette.append({"macchina_id": macchina.pk, "da": prima, "a": host})
        else:
            errate.append(f"{macchina.reparto} ({host})")
    if corrette:
        log_action(request, "discovery_ip_corretti", "contatori", {"corretti": corrette[:200]})
        messages.success(request, f"IP aggiornato su {len(corrette)} MFC.")
    if errate:
        messages.error(request, "IP non valido: " + ", ".join(errate) + ".")
    if not (corrette or errate):
        messages.info(request, "Nessuna riga selezionata.")
    ritorno = request.POST.get("next") or ""
    return redirect(ritorno if ritorno.startswith(reverse("contatori:discovery")) else "contatori:discovery")
