"""Pagina «Verifica OID»: prova un elenco di OID sull'apparato e crea le colonne."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.audit import log_action

from . import services, verifica_oid
from .models import ColonnaProfiloSNMP, DispositivoSNMP, ProfiloSNMP, SondaSNMP
from .permessi import richiede_gestione

CHIAVE_SESSIONE = "contatori_verifica_oid_{}"


def _stato(request, pk):
    return request.session.get(CHIAVE_SESSIONE.format(pk)) or {}


def _salva_stato(request, pk, stato):
    request.session[CHIAVE_SESSIONE.format(pk)] = stato
    request.session.modified = True


def _decimale(valore):
    testo = (valore or "").strip().replace(",", ".")
    if not testo:
        return None
    try:
        numero = Decimal(testo)
    except InvalidOperation:
        return None
    return numero if numero.is_finite() else None


@richiede_gestione
def dispositivo_snmp_verifica_oid(request, pk):
    dispositivo = get_object_or_404(DispositivoSNMP.objects.select_related("profilo_snmp"), pk=pk)
    stato = _stato(request, pk)
    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione == "verifica":
            return _verifica(request, dispositivo)
        if azione == "proponi" and stato.get("candidati"):
            return _proponi(request, dispositivo, stato)
        if azione == "aggiungi" and stato.get("candidati"):
            return _aggiungi(request, dispositivo, stato)
        if azione == "azzera":
            request.session.pop(CHIAVE_SESSIONE.format(pk), None)
        return redirect("contatori:snmp_dispositivo_verifica_oid", pk=pk)

    proposte = stato.get("proposte") or {}
    righe = []
    for indice, candidato in enumerate(stato.get("candidati") or []):
        proposta = proposte.get(candidato["oid"]) or {}
        righe.append({"i": indice, **candidato, "proposta": proposta,
                      "nome": proposta.get("nome") or "",
                      "aggregazione": proposta.get("aggregazione")
                      or ("PRIMO" if candidato["modalita"] == "GET" else "MASSIMO")})
    profili = ProfiloSNMP.objects.filter(attivo=True)
    return render(request, "contatori/snmp_verifica_oid.html", {
        "dispositivo": dispositivo,
        "stato": stato,
        "righe": righe,
        "testo": stato.get("testo", ""),
        "profili": profili,
        "aggregazioni": ColonnaProfiloSNMP.Aggregazione.choices,
        "max_ai": verifica_oid.MAX_AI_PER_VOLTA,
        "rami": verifica_oid.rami_noti(dispositivo.sys_object_id),
    })


def _verifica(request, dispositivo):
    testo = (request.POST.get("oids") or "")[:20000]
    esplora = request.POST.get("esplora") == "1"
    oids = verifica_oid.estrai_oid(testo)
    if not oids and not esplora:
        messages.error(request, "Nessun OID trovato nel testo: incolla OID numerici (es. 1.3.6.1.2.1.1.3.0) "
                                "oppure spunta «Esplora i rami noti».")
        return redirect("contatori:snmp_dispositivo_verifica_oid", pk=dispositivo.pk)
    esito = verifica_oid.verifica_dispositivo(dispositivo, oids, esplora=esplora)
    _salva_stato(request, dispositivo.pk, {
        "testo": testo[:5000], "esplora": esplora, "richiesti": len(oids),
        "candidati": esito["candidati"], "assenti": esito["assenti"], "errore": esito["errore"],
        "eseguita_il": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        "proposte": verifica_oid.proposte_catalogo(esito["candidati"]),
    })
    log_action(request, "snmp_verifica_oid", "contatori", oggetto=dispositivo, dettaglio={
        "richiesti": len(oids), "esplora": esplora, "rispondono": len(esito["candidati"]),
        "assenti": len(esito["assenti"]), "errore": bool(esito["errore"]),
    })
    if esito["errore"] and not esito["candidati"]:
        messages.error(request, esito["errore"])
    else:
        messages.success(request, f"Verifica completata: {len(esito['candidati'])} OID rispondono, "
                                  f"{len(esito['assenti'])} non esistono sull'apparato.")
    return redirect("contatori:snmp_dispositivo_verifica_oid", pk=dispositivo.pk)


def _selezionati(request, candidati):
    scelti = []
    for valore in request.POST.getlist("sel"):
        try:
            indice = int(valore)
        except ValueError:
            continue
        if 0 <= indice < len(candidati):
            scelti.append((indice, candidati[indice]))
    return scelti


def _proponi(request, dispositivo, stato):
    candidati = stato["candidati"]
    proposte = stato.get("proposte") or {}
    scelti = [c for _, c in _selezionati(request, candidati)]
    # Senza selezione: le righe che non hanno ancora un nome, a blocchi.
    da_proporre = scelti or [c for c in candidati if c["oid"] not in proposte]
    blocco = da_proporre[:verifica_oid.MAX_AI_PER_VOLTA]
    nuove = verifica_oid.proponi_con_ai(dispositivo, blocco)
    proposte.update(nuove)
    stato["proposte"] = proposte
    _salva_stato(request, dispositivo.pk, stato)
    restano = sum(1 for c in candidati if c["oid"] not in proposte)
    if nuove:
        testo = f"L'AI ha proposto {len(nuove)} nomi su {len(blocco)} OID: controllali prima di aggiungerli."
        if restano and not scelti:
            testo += f" Restano {restano} righe senza nome: premi di nuovo per il blocco successivo."
        messages.success(request, testo)
    elif not blocco:
        messages.info(request, "Tutte le righe hanno già un nome. Seleziona le righe da riproporre con l'AI.")
    else:
        messages.warning(request, "L'AI interna non ha risposto in tempo o in un formato leggibile. "
                                  "Riprova selezionando meno righe, oppure compila i nomi a mano.")
    return redirect("contatori:snmp_dispositivo_verifica_oid", pk=dispositivo.pk)


def _aggiungi(request, dispositivo, stato):
    scelti = _selezionati(request, stato["candidati"])
    if not scelti:
        messages.error(request, "Seleziona almeno un OID da aggiungere.")
        return redirect("contatori:snmp_dispositivo_verifica_oid", pk=dispositivo.pk)

    destinazione = request.POST.get("destinazione")
    profilo = None
    if destinazione != "dispositivo":
        profilo = ProfiloSNMP.objects.filter(pk=request.POST.get("profilo") or 0, attivo=True).first()
        if profilo is None:
            messages.error(request, "Scegli il profilo a cui aggiungere le colonne.")
            return redirect("contatori:snmp_dispositivo_verifica_oid", pk=dispositivo.pk)

    modello = (dispositivo.modello or dispositivo.sys_description or dispositivo.host)[:120]
    fonte = f"Verifica OID {timezone.localdate():%d/%m/%Y} su {modello}"[:200]
    tipi = set(ColonnaProfiloSNMP.TipoValore.values)
    aggregazioni = set(ColonnaProfiloSNMP.Aggregazione.values)
    creati, gia_presenti = 0, 0
    with transaction.atomic():
        if profilo is not None:
            ordine = (profilo.colonne.aggregate(m=Max("ordine"))["m"] or 0)
            esistenti = set(profilo.colonne.values_list("oid", flat=True))
        else:
            ordine = (dispositivo.sonde.aggregate(m=Max("ordine"))["m"] or 0)
            esistenti = set(dispositivo.sonde.values_list("oid", flat=True))
        for indice, cand in scelti:
            if cand["oid"] in esistenti:
                gia_presenti += 1
                continue
            p = request.POST
            aggregazione = p.get(f"aggregazione_{indice}") or "PRIMO"
            if cand["modalita"] == "GET" or aggregazione not in aggregazioni:
                aggregazione = "PRIMO" if cand["modalita"] == "GET" else "MASSIMO"
            ordine += 10
            campi = {
                "nome": (p.get(f"nome_{indice}") or "").strip()[:100] or f"OID {cand['oid']}"[:100],
                "oid": cand["oid"],
                "tipo_valore": cand["tipo"] if cand["tipo"] in tipi else ColonnaProfiloSNMP.TipoValore.NUMERO,
                "modalita": cand["modalita"],
                "aggregazione": aggregazione,
                "unita": (p.get(f"unita_{indice}") or "").strip()[:24],
                "fattore": _decimale(p.get(f"fattore_{indice}")) or Decimal("1"),
                "soglia_warning_max": _decimale(p.get(f"avviso_{indice}")),
                "soglia_critica_max": _decimale(p.get(f"critico_{indice}")),
                "etichette": (p.get(f"etichette_{indice}") or "").strip()[:500],
                "ordine": ordine,
            }
            if profilo is not None:
                ColonnaProfiloSNMP.objects.create(profilo=profilo, verificata=True, fonte=fonte, **campi)
            else:
                SondaSNMP.objects.create(dispositivo=dispositivo, attiva=True, **campi)
            creati += 1
        if profilo is not None and creati and dispositivo.profilo_snmp_id == profilo.pk:
            services.applica_profilo_dispositivo(dispositivo, profilo)

    log_action(request, "snmp_verifica_oid_aggiunti", "contatori", oggetto=dispositivo, dettaglio={
        "destinazione": f"profilo {profilo.slug}" if profilo else "dispositivo",
        "creati": creati, "gia_presenti": gia_presenti,
    })
    dove = f"al profilo «{profilo.nome}»" if profilo else "come lettori OID di questo dispositivo"
    messages.success(request, f"Aggiunte {creati} colonne {dove}"
                              + (f"; {gia_presenti} erano già presenti." if gia_presenti else "."))
    if profilo is not None and dispositivo.profilo_snmp_id != profilo.pk:
        messages.info(request, "Il dispositivo usa un altro profilo: applica «"
                               f"{profilo.nome}» dalla scheda per leggere le nuove colonne.")
    return redirect("contatori:snmp_dispositivo", pk=dispositivo.pk)
