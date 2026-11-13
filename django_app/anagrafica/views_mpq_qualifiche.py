"""MOD.128 — persone qualificate e macchine qualificate (13/11/2026).

Viste aggiuntive al dettaglio del processo (``views_mpq``): ruoli del processo,
requisiti persona (per ruolo, una tantum o ricorrenti) con le loro evidenze,
requisiti macchina (dal motore manutenzioni), parametri della verifica, scheda
della macchina sul processo con verifiche e cambi di stato, elenco stampabile
(allegati «personale qualificato» e «macchine qualificate»).

Permessi: lettura ``anagrafica.mpq.view``, scrittura ``anagrafica.mpq.manage``
(stessi codici del MOD.128, binding in ``acl_bootstrap._MPQ_ROUTE_BINDINGS``).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models_mpq import (
    AbilitazioneProcesso,
    EvidenzaRequisitoPersona,
    ParametroVerificaMacchina,
    ProcessoQualificato,
    QualificaMacchina,
    RequisitoMacchina,
    RequisitoPersona,
    RuoloProcesso,
    VerificaMacchina,
)
from .views_mpq import _check_manage, _check_mpq_permission, _mpq_denied, _mpq_log, _nomi_map


def _dettaglio(processo_id, ancora=""):
    url = reverse("anagrafica:mpq_processo_detail", args=[processo_id])
    return url + (f"#{ancora}" if ancora else "")


def _ritorno(request, default):
    from .views._helpers import back_sicuro

    return back_sicuro(request, request.GET.get("back") or request.POST.get("back")) or default


def _form_page(request, form, titolo, back_url, *, multipart=False):
    return render(request, "anagrafica/pages/mpq_form.html", {
        "form": form, "titolo": titolo, "back_url": back_url, "multipart": multipart,
    })


# ── Ruoli del processo ───────────────────────────────────────────────────────

@login_required
@require_POST
def mpq_ruolo_add(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    nomi = [n.strip()[:120] for n in (request.POST.get("nome") or "").split(";") if n.strip()]
    creati = 0
    ordine = proc.ruoli.count()
    for nome in nomi:
        _r, creato = RuoloProcesso.objects.get_or_create(
            processo=proc, nome=nome, defaults={"ordine": ordine + creati})
        creati += int(creato)
    if creati:
        _mpq_log(request, processo=proc, evento="Ruoli aggiunti", dettaglio=", ".join(nomi))
        messages.success(request, f"{creati} ruol{'o' if creati == 1 else 'i'} aggiunt{'o' if creati == 1 else 'i'}.")
    else:
        messages.info(request, "Nessun ruolo nuovo.")
    return redirect(_dettaglio(proc.id, "requisiti-persone"))


@login_required
@require_POST
def mpq_ruolo_delete(request, ruolo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    ruolo = get_object_or_404(RuoloProcesso, pk=ruolo_id)
    pid = ruolo.processo_id
    _mpq_log(request, processo=ruolo.processo, evento="Ruolo rimosso", dettaglio=ruolo.nome)
    ruolo.delete()
    messages.success(request, "Ruolo rimosso.")
    return redirect(_dettaglio(pid, "requisiti-persone"))


# ── Requisiti persona ────────────────────────────────────────────────────────

@login_required
def mpq_requisito_persona_add(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import RequisitoPersonaForm

    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    back = _dettaglio(proc.id, "requisiti-persone")
    if request.method == "POST":
        form = RequisitoPersonaForm(request.POST, processo=proc)
        if form.is_valid():
            req = form.save(commit=False)
            req.processo = proc
            req.ordine = proc.requisiti_persona.count()
            req.save()
            form.save_m2m()
            _mpq_log(request, processo=proc, evento="Requisito persona aggiunto",
                     dettaglio=f"{req.get_tipo_display()}: {req.etichetta}")
            messages.success(request, "Requisito aggiunto.")
            return redirect(back)
    else:
        form = RequisitoPersonaForm(processo=proc, initial={"bloccante": True, "attivo": True})
    return _form_page(request, form, f"Cosa serve a una persona · {proc.nome}", back)


@login_required
def mpq_requisito_persona_edit(request, req_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import RequisitoPersonaForm

    req = get_object_or_404(RequisitoPersona.objects.select_related("processo"), pk=req_id)
    back = _dettaglio(req.processo_id, "requisiti-persone")
    if request.method == "POST":
        form = RequisitoPersonaForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            _mpq_log(request, processo=req.processo, evento="Requisito persona modificato",
                     dettaglio=f"{req.get_tipo_display()}: {req.etichetta}")
            messages.success(request, "Requisito aggiornato.")
            return redirect(back)
    else:
        form = RequisitoPersonaForm(instance=req)
    return _form_page(request, form, f"Modifica requisito · {req.processo.nome}", back)


@login_required
@require_POST
def mpq_requisito_persona_delete(request, req_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    req = get_object_or_404(RequisitoPersona.objects.select_related("processo"), pk=req_id)
    pid = req.processo_id
    _mpq_log(request, processo=req.processo, evento="Requisito persona rimosso",
             dettaglio=f"{req.get_tipo_display()}: {req.etichetta}")
    req.delete()
    messages.success(request, "Requisito rimosso.")
    return redirect(_dettaglio(pid, "requisiti-persone"))


@login_required
def mpq_evidenza_add(request, ab_id: int, req_id: int):
    """Registra test visivo, esame, ore, affiancamento… per una persona."""
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import EvidenzaRequisitoPersonaForm

    ab = get_object_or_404(AbilitazioneProcesso.objects.select_related("processo"), pk=ab_id)
    req = get_object_or_404(RequisitoPersona, pk=req_id, processo_id=ab.processo_id)
    if req.tipo in RequisitoPersona.TIPI_DA_ALTRI_MODULI:
        messages.info(request, "Corsi e visite si registrano in Formazione e Visite mediche.")
        return redirect(_dettaglio(ab.processo_id, "persone"))
    back = _ritorno(request, _dettaglio(ab.processo_id, "persone"))
    nome = ab.nominativo_esterno or _nomi_map([ab.legacy_anagrafica_id]).get(
        ab.legacy_anagrafica_id, f"#{ab.legacy_anagrafica_id}")
    if request.method == "POST":
        form = EvidenzaRequisitoPersonaForm(request.POST, request.FILES, requisito=req)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.abilitazione = ab
            ev.requisito = req
            ev.registrato_da = request.user
            if ev.documento:
                ev.documento_nome_originale = getattr(ev.documento, "name", "")[:255]
            ev.save()
            _mpq_log(request, processo=ab.processo, abilitazione=ab,
                     evento=f"Registrato: {req.etichetta}",
                     dettaglio=f"{nome} · {ev.data_esecuzione:%d-%m-%Y} · {ev.get_esito_display()}")
            messages.success(request, f"{req.etichetta} registrato per {nome}.")
            return redirect(back)
    else:
        form = EvidenzaRequisitoPersonaForm(requisito=req, initial={"data_esecuzione": timezone.localdate()})
    return _form_page(request, form, f"{req.etichetta} · {nome}", back, multipart=True)


# ── Requisiti macchina e parametri della verifica ────────────────────────────

@login_required
def mpq_requisito_macchina_add(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import RequisitoMacchinaForm

    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    back = _dettaglio(proc.id, "requisiti-macchine")
    if request.method == "POST":
        form = RequisitoMacchinaForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.processo = proc
            req.ordine = proc.requisiti_macchina.count()
            req.save()
            _mpq_log(request, processo=proc, evento="Requisito macchina aggiunto", dettaglio=req.descrizione)
            messages.success(request, "Requisito aggiunto.")
            return redirect(back)
    else:
        form = RequisitoMacchinaForm(initial={"bloccante": True, "attivo": True})
    return _form_page(request, form, f"Cosa serve a una macchina · {proc.nome}", back)


@login_required
def mpq_requisito_macchina_edit(request, req_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import RequisitoMacchinaForm

    req = get_object_or_404(RequisitoMacchina.objects.select_related("processo"), pk=req_id)
    back = _dettaglio(req.processo_id, "requisiti-macchine")
    if request.method == "POST":
        form = RequisitoMacchinaForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            _mpq_log(request, processo=req.processo, evento="Requisito macchina modificato",
                     dettaglio=req.descrizione)
            messages.success(request, "Requisito aggiornato.")
            return redirect(back)
    else:
        form = RequisitoMacchinaForm(instance=req)
    return _form_page(request, form, f"Modifica requisito · {req.processo.nome}", back)


@login_required
@require_POST
def mpq_requisito_macchina_delete(request, req_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    req = get_object_or_404(RequisitoMacchina.objects.select_related("processo"), pk=req_id)
    pid = req.processo_id
    _mpq_log(request, processo=req.processo, evento="Requisito macchina rimosso", dettaglio=req.descrizione)
    req.delete()
    messages.success(request, "Requisito rimosso.")
    return redirect(_dettaglio(pid, "requisiti-macchine"))


def _decimale(valore):
    from .services.mpq_macchine import _dec

    return _dec(valore)


@login_required
@require_POST
def mpq_parametro_add(request, processo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    nome = (request.POST.get("nome") or "").strip()[:150]
    tipo = request.POST.get("tipo") or ParametroVerificaMacchina.TIPO_TOLLERANZA
    if tipo not in dict(ParametroVerificaMacchina.TIPO_CHOICES):
        tipo = ParametroVerificaMacchina.TIPO_TOLLERANZA
    tol = _decimale(request.POST.get("tolleranza_pct"))
    minimo = _decimale(request.POST.get("valore_minimo"))
    errore = ""
    if not nome:
        errore = "Scrivi il nome della voce (es. «Giri mandrino»)."
    elif tipo == ParametroVerificaMacchina.TIPO_TOLLERANZA and tol is None:
        errore = "Indica la tolleranza in % (es. 10)."
    elif tipo == ParametroVerificaMacchina.TIPO_MINIMO and minimo is None:
        errore = "Indica il valore minimo (es. 4,1)."
    if errore:
        messages.error(request, errore)
    else:
        ParametroVerificaMacchina.objects.create(
            processo=proc, nome=nome, tipo=tipo, unita=(request.POST.get("unita") or "").strip()[:20],
            tolleranza_pct=tol if tipo == ParametroVerificaMacchina.TIPO_TOLLERANZA else None,
            valore_minimo=minimo if tipo == ParametroVerificaMacchina.TIPO_MINIMO else None,
            ordine=proc.parametri_verifica.count(),
        )
        _mpq_log(request, processo=proc, evento="Voce di verifica macchina aggiunta", dettaglio=nome)
        messages.success(request, "Voce aggiunta alla verifica.")
    return redirect(_dettaglio(proc.id, "requisiti-macchine"))


@login_required
@require_POST
def mpq_parametro_delete(request, parametro_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    par = get_object_or_404(ParametroVerificaMacchina.objects.select_related("processo"), pk=parametro_id)
    pid = par.processo_id
    _mpq_log(request, processo=par.processo, evento="Voce di verifica macchina rimossa", dettaglio=par.nome)
    par.delete()
    messages.success(request, "Voce rimossa.")
    return redirect(_dettaglio(pid, "requisiti-macchine"))


# ── Macchina sul processo ────────────────────────────────────────────────────

@login_required
@require_POST
def mpq_qualifica_macchina_crea(request, processo_id: int, asset_id: int):
    """Apre la qualifica di una macchina che è nel processo solo per il flag PART 145."""
    if not _check_manage(request):
        return _mpq_denied(request)
    from assets.models import Asset

    from .services.mpq_macchine import collega

    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    asset = get_object_or_404(Asset, pk=asset_id)
    qm = collega(proc, asset, user=request.user)
    return redirect("anagrafica:mpq_qualifica_macchina", qm_id=qm.pk)


@login_required
def mpq_qualifica_macchina(request, qm_id: int):
    """Scheda della macchina sul processo: stato, requisiti, verifiche, azioni."""
    if not _check_mpq_permission(request):
        return _mpq_denied(request)
    from .services.mpq_macchine import periodo_da_riesaminare, stato_requisiti_macchina, stato_visuale

    qm = get_object_or_404(QualificaMacchina.objects.select_related("processo", "processo__cliente", "asset"),
                           pk=qm_id)
    oggi = timezone.localdate()
    verifiche = list(qm.verifiche.prefetch_related("misure").select_related("registrato_da"))
    ultima_ko = next((v for v in verifiche if v.esito == VerificaMacchina.ESITO_KO), None)
    riesame = None
    if ultima_ko and qm.stato == QualificaMacchina.STATO_SOSPESA:
        riesame = periodo_da_riesaminare(ultima_ko)
    return render(request, "anagrafica/pages/mpq_qualifica_macchina.html", {
        "qm": qm, "processo": qm.processo, "asset": qm.asset,
        "stato": stato_visuale(qm, oggi),
        "requisiti": stato_requisiti_macchina(qm.processo, qm.asset, oggi=oggi),
        "verifiche": verifiche,
        "riesame": riesame,
        "can_manage": _check_manage(request),
        "storico": list(qm.processo.storico.filter(evento__contains=qm.asset.asset_tag)
                        .select_related("registrato_da")[:30]),
    })


@login_required
def mpq_qualifica_macchina_edit(request, qm_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import QualificaMacchinaForm

    qm = get_object_or_404(QualificaMacchina.objects.select_related("processo", "asset"), pk=qm_id)
    back = reverse("anagrafica:mpq_qualifica_macchina", args=[qm.pk])
    if request.method == "POST":
        form = QualificaMacchinaForm(request.POST, instance=qm)
        if form.is_valid():
            q = form.save(commit=False)
            q.aggiornato_da = request.user
            q.save()
            _mpq_log(request, processo=qm.processo, evento=f"Macchina {qm.asset.asset_tag}: dati qualifica modificati")
            messages.success(request, "Qualifica aggiornata.")
            return redirect(back)
    else:
        form = QualificaMacchinaForm(instance=qm)
    return _form_page(request, form, f"{qm.asset.asset_tag} · {qm.processo.nome}", back)


# Azioni di stato: (nuovo stato, messaggio, motivo obbligatorio)
_AZIONI_STATO = {
    "non_incide": (QualificaMacchina.STATO_QUALIFICATA, "Confermato: la manutenzione non incide, macchina di nuovo qualificata.", False),
    "riqualifica": (QualificaMacchina.STATO_SOSPESA, "Macchina sospesa: registra la verifica di riqualifica.", False),
    "sospendi": (QualificaMacchina.STATO_SOSPESA, "Macchina sospesa.", True),
    "declassa": (QualificaMacchina.STATO_DECLASSATA, "Macchina declassata.", True),
    "ritira": (QualificaMacchina.STATO_RITIRATA, "Macchina tolta dal processo.", False),
}


@login_required
@require_POST
def mpq_qualifica_macchina_stato(request, qm_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .services.mpq_macchine import cambia_stato, scollega

    qm = get_object_or_404(QualificaMacchina.objects.select_related("processo", "asset"), pk=qm_id)
    azione = request.POST.get("azione") or ""
    if azione not in _AZIONI_STATO:
        messages.error(request, "Azione non valida.")
        return redirect("anagrafica:mpq_qualifica_macchina", qm_id=qm.pk)
    nuovo, msg, serve_motivo = _AZIONI_STATO[azione]
    motivo = (request.POST.get("motivo") or "").strip()
    if serve_motivo and not motivo:
        messages.error(request, "Scrivi il motivo.")
        return redirect("anagrafica:mpq_qualifica_macchina", qm_id=qm.pk)
    if azione == "non_incide" and qm.stato != QualificaMacchina.STATO_DA_VALUTARE:
        messages.error(request, "«Non incide» vale solo per una macchina da valutare.")
        return redirect("anagrafica:mpq_qualifica_macchina", qm_id=qm.pk)
    if azione == "non_incide" and not qm.data_qualifica:
        nuovo = QualificaMacchina.STATO_DA_QUALIFICARE
    if azione == "riqualifica":
        motivo = motivo or "Serve la riqualifica dopo la manutenzione."
    if azione == "non_incide":
        motivo = motivo or "Valutata: la manutenzione non incide sul processo."
    if azione == "ritira":
        scollega(qm.processo, qm.asset, user=request.user)
        _mpq_log(request, processo=qm.processo, evento=f"Attrezzatura scollegata: {qm.asset.asset_tag}",
                 dettaglio=motivo)
        messages.success(request, msg)
        return redirect(_dettaglio(qm.processo_id, "attrezzature"))
    cambia_stato(qm, nuovo, motivo=motivo, user=request.user,
                 limitazioni=(request.POST.get("limitazioni") if azione == "declassa" else None))
    messages.success(request, msg)
    return redirect("anagrafica:mpq_qualifica_macchina", qm_id=qm.pk)


@login_required
def mpq_verifica_add(request, qm_id: int):
    """Registra una verifica di qualifica con le misure dei parametri del processo."""
    if not _check_manage(request):
        return _mpq_denied(request)
    from .services.mpq_macchine import registra_verifica

    qm = get_object_or_404(QualificaMacchina.objects.select_related("processo", "asset"), pk=qm_id)
    parametri = list(qm.processo.parametri_verifica.filter(attivo=True))
    if qm.stato in (QualificaMacchina.STATO_DA_QUALIFICARE,) and not qm.verifiche.exists():
        tipo_default = VerificaMacchina.TIPO_INIZIALE
    elif qm.stato in (QualificaMacchina.STATO_DA_VALUTARE, QualificaMacchina.STATO_SOSPESA):
        tipo_default = VerificaMacchina.TIPO_RIQUALIFICA
    else:
        tipo_default = VerificaMacchina.TIPO_PERIODICA
    errori = []
    valori = {}
    if request.method == "POST":
        from datetime import date as _date

        tipo = request.POST.get("tipo") or tipo_default
        if tipo not in dict(VerificaMacchina.TIPO_CHOICES):
            tipo = tipo_default
        try:
            data = _date.fromisoformat(request.POST.get("data") or "")
        except ValueError:
            data = None
            errori.append("Indica la data della verifica.")
        righe = []
        for par in parametri:
            v = {
                "nominale": request.POST.get(f"nom_{par.pk}"),
                "misurato": request.POST.get(f"mis_{par.pk}"),
                "conforme": request.POST.get(f"ok_{par.pk}") == "1",
            }
            valori[par.pk] = v
            if par.tipo == par.TIPO_TOLLERANZA and (not v["nominale"] or not v["misurato"]):
                errori.append(f"«{par.nome}»: servono valore nominale e misurato.")
            elif par.tipo == par.TIPO_MINIMO and not v["misurato"]:
                errori.append(f"«{par.nome}»: serve il valore misurato.")
            righe.append((par, v))
        if data and data > timezone.localdate():
            errori.append("La data non può essere futura.")
        if not errori:
            ver = registra_verifica(
                qm, tipo=tipo, data=data, righe=righe,
                eseguita_da=(request.POST.get("eseguita_da") or "").strip(),
                note=(request.POST.get("note") or "").strip(),
                documento=request.FILES.get("documento"), user=request.user,
            )
            if ver.esito == VerificaMacchina.ESITO_OK:
                messages.success(request, f"Verifica conforme: {qm.asset.asset_tag} qualificata.")
            else:
                messages.error(request, f"Verifica NON conforme: {qm.asset.asset_tag} sospesa. "
                                        "Riesamina le parti lavorate nel periodo indicato.")
            return redirect("anagrafica:mpq_qualifica_macchina", qm_id=qm.pk)
    return render(request, "anagrafica/pages/mpq_verifica_form.html", {
        "qm": qm, "processo": qm.processo, "asset": qm.asset, "parametri": parametri,
        "righe_form": [(p, valori.get(p.pk, {})) for p in parametri], "errori": errori, "tipi": VerificaMacchina.TIPO_CHOICES,
        "tipo_sel": request.POST.get("tipo") or tipo_default,
        "data_sel": request.POST.get("data") or timezone.localdate().isoformat(),
        "post": request.POST if request.method == "POST" else {},
    })


@login_required
def mpq_documento(request, tipo: str, pk: int):
    """Scarica il documento di una verifica macchina o di un'evidenza persona."""
    if not _check_mpq_permission(request):
        return _mpq_denied(request)
    if tipo == "verifica":
        obj = get_object_or_404(VerificaMacchina, pk=pk)
    elif tipo == "evidenza":
        obj = get_object_or_404(EvidenzaRequisitoPersona, pk=pk)
    else:
        raise Http404
    if not obj.documento:
        raise Http404
    nome = obj.documento_nome_originale or obj.documento.name.rsplit("/", 1)[-1]
    return FileResponse(obj.documento.open("rb"), as_attachment=True, filename=nome.rsplit("/", 1)[-1])


@login_required
def mpq_elenco(request, processo_id: int):
    """Elenco stampabile: personale qualificato per ruolo e macchine qualificate.

    Sostituisce gli allegati compilati a mano (es. MT CN 69 allegati 2 e 3):
    l'elenco nasce dai dati, quindi un cambio di nominativi non richiede di
    rivedere la procedura.
    """
    if not _check_mpq_permission(request):
        return _mpq_denied(request)
    from .services.mpq_macchine import righe_macchine
    from .services.mpq_persone import contesto_processo, stato_persona

    proc = get_object_or_404(ProcessoQualificato.objects.select_related("cliente"), pk=processo_id)
    oggi = timezone.localdate()
    abil = list(proc.abilitazioni.filter(stato=AbilitazioneProcesso.STATO_ATTIVA)
                .prefetch_related("ruoli_processo", "certificazioni"))
    nomi = _nomi_map([a.legacy_anagrafica_id for a in abil])
    ctx = contesto_processo(proc, abil)
    gruppi: dict[str, list] = {r.nome: [] for r in proc.ruoli.all()}
    for a in abil:
        st = stato_persona(a, oggi=oggi, contesto=ctx)
        voce = {"nome": a.nominativo_esterno or nomi.get(a.legacy_anagrafica_id, f"#{a.legacy_anagrafica_id}"),
                "stato": st}
        ruoli = [r.nome for r in a.ruoli_processo.all()] or ["Senza ruolo"]
        for r in ruoli:
            gruppi.setdefault(r, []).append(voce)
    for lista in gruppi.values():
        lista.sort(key=lambda v: v["nome"].lower())
    macchine = [r for r in righe_macchine(proc, oggi=oggi) if r["qualifica"] is not None]
    return render(request, "anagrafica/pages/mpq_elenco.html", {
        "processo": proc, "oggi": oggi,
        "gruppi": [(k, v) for k, v in gruppi.items() if v],
        "n_persone": len(abil), "macchine": macchine,
    })
