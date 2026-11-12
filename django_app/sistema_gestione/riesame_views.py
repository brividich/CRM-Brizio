"""Riesame della direzione: verbali MOD.062 e obiettivi."""
from __future__ import annotations

import re
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_RIESAME_APPROVA, PERM_RIESAME_EDIT, PERM_RIESAME_VIEW
from .forms import CopiaFirmataForm
from .models import Riesame, RiesameObiettivo, RiesamePartecipante
from .riesame_forms import ObiettivoAndamentoForm, ObiettivoForm, PartecipanteForm, RiesameForm
from .services import riesame as service
from .views import MODULE, _has_perm, _nega

_NEGATO = "Non hai i permessi richiesti per il riesame della direzione."


def _aree(request) -> set[str]:
    """Gli indicatori di un'area entrano nel verbale solo se chi prepara può vederla."""
    from report_conformita.views import _aree_consentite

    return _aree_consentite(request)


def _modificabile(request, riesame: Riesame):
    """Risposta da restituire se il verbale non si può toccare, altrimenti ``None``."""
    if not _has_perm(request, PERM_RIESAME_EDIT):
        return _nega(request, _NEGATO)
    if not riesame.modificabile:
        messages.error(request, "Il verbale non è in bozza: non si modifica.")
        return redirect("sistema_gestione:riesame_dettaglio", pk=riesame.pk)
    return None


@login_required
def elenco(request):
    if not _has_perm(request, PERM_RIESAME_VIEW):
        return _nega(request, _NEGATO)
    return render(request, "sistema_gestione/pages/riesame_elenco.html", {
        "page_title": "Riesame della direzione",
        "verbali": Riesame.objects.select_related("approvato_da"),
        "obiettivi": service.obiettivi_aperti(),
        "prossimo": service.prossimo_riesame(),
        "oggi": timezone.localdate(),
        "puo_modificare": _has_perm(request, PERM_RIESAME_EDIT),
        "puo_dati": bool(_aree(request)),
    })


@login_required
def nuovo(request):
    if not _has_perm(request, PERM_RIESAME_EDIT):
        return _nega(request, _NEGATO)
    oggi = timezone.localdate()
    form = RiesameForm(request.POST or None, initial={
        "anno": oggi.year, "data": oggi, "periodo_dal": oggi.replace(month=1, day=1), "periodo_al": oggi})
    if request.method == "POST" and form.is_valid():
        riesame = service.crea_riesame(form.save(commit=False), utente=request.user, aree=_aree(request))
        log_action(request, "riesame_creato", MODULE, {"id": riesame.pk}, oggetto=riesame)
        messages.success(request, "Verbale creato con gli indicatori del periodo.")
        return redirect("sistema_gestione:riesame_dettaglio", pk=riesame.pk)
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Nuovo verbale di riesame", "form": form, "indietro": reverse("sistema_gestione:riesame_elenco")})


@login_required
def modifica(request, pk: int):
    riesame = get_object_or_404(Riesame, pk=pk)
    negato = _modificabile(request, riesame)
    if negato:
        return negato
    form = RiesameForm(request.POST or None, instance=riesame)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request, "riesame_modificato", MODULE, {"id": riesame.pk}, oggetto=riesame)
        return redirect("sistema_gestione:riesame_dettaglio", pk=pk)
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Dati del verbale", "form": form,
        "indietro": reverse("sistema_gestione:riesame_dettaglio", args=[pk])})


def _al_pannello(request, pk: int):
    """Torna al verbale sul pannello richiesto: conta solo un identificativo, mai un indirizzo."""
    url = reverse("sistema_gestione:riesame_dettaglio", args=[pk])
    pannello = request.POST.get("next", "")
    if re.fullmatch(r"[a-z]+(-\d+)?", pannello):
        url += f"#{pannello}"
    return redirect(url)


@login_required
def dettaglio(request, pk: int):
    if not _has_perm(request, PERM_RIESAME_VIEW):
        return _nega(request, _NEGATO)
    riesame = get_object_or_404(Riesame.objects.select_related("preparato_da", "approvato_da"), pk=pk)
    argomenti = list(riesame.argomenti.all())
    puo_modificare = _has_perm(request, PERM_RIESAME_EDIT) and riesame.modificabile
    precedenti = None if riesame.stato == Riesame.STATO_APPROVATO else list(service.obiettivi_precedenti(riesame))
    return render(request, "sistema_gestione/pages/riesame_dettaglio.html", {
        "page_title": str(riesame),
        "riesame": riesame,
        "ingresso": [a for a in argomenti if a.gruppo == Riesame.GRUPPO_INGRESSO],
        "uscita": [a for a in argomenti if a.gruppo == Riesame.GRUPPO_USCITA],
        "n_compilati": sum(1 for a in argomenti if a.analisi.strip()),
        "n_argomenti": len(argomenti),
        "partecipanti": riesame.partecipanti.select_related("utente"),
        "precedenti": precedenti,
        "n_precedenti": len(riesame.fotografia_precedenti) if precedenti is None else len(precedenti),
        "n_prec_valutati": (len(riesame.fotografia_precedenti) if precedenti is None
                            else sum(1 for o in precedenti if o.nota.strip())),
        "stati_obiettivo": RiesameObiettivo.STATO_CHOICES,
        "obiettivi": riesame.obiettivi.select_related("responsabile", "processo", "origine"),
        "problemi": service.problemi_proposta(riesame) if riesame.modificabile else [],
        "puo_modificare": puo_modificare,
        "puo_proporre": _has_perm(request, PERM_RIESAME_EDIT),
        "puo_approvare": _has_perm(request, PERM_RIESAME_APPROVA),
        "form_partecipante": PartecipanteForm() if puo_modificare else None,
        "form_firmata": CopiaFirmataForm(),
    })


@login_required
@require_POST
@transaction.atomic
def salva_analisi(request, pk: int):
    """Analisi degli argomenti e livello di raggiungimento degli obiettivi precedenti, in un solo salvataggio."""
    riesame = get_object_or_404(Riesame.objects.select_for_update(), pk=pk)
    negato = _modificabile(request, riesame)
    if negato:
        return negato
    for argomento in riesame.argomenti.all():
        chiave = f"analisi_{argomento.pk}"
        if chiave in request.POST:
            argomento.analisi = request.POST[chiave].strip()
            argomento.save(update_fields=["analisi"])
    stati = dict(RiesameObiettivo.STATO_CHOICES)
    for obiettivo in service.obiettivi_precedenti(riesame):
        stato = request.POST.get(f"stato_{obiettivo.pk}")
        if stato in stati:
            service.valuta_precedente(riesame, obiettivo, stato=stato, nota=request.POST.get(f"nota_{obiettivo.pk}", ""))
    log_action(request, "riesame_analisi_salvata", MODULE, {"id": riesame.pk}, oggetto=riesame)
    messages.success(request, "Verbale salvato.")
    return _al_pannello(request, pk)


@login_required
@require_POST
def aggiorna_indicatori(request, pk: int):
    riesame = get_object_or_404(Riesame, pk=pk)
    negato = _modificabile(request, riesame)
    if negato:
        return negato
    service.aggiorna_indicatori(riesame, _aree(request))
    log_action(request, "riesame_indicatori_aggiornati", MODULE, {"id": riesame.pk}, oggetto=riesame)
    messages.success(request, "Indicatori aggiornati.")
    return _al_pannello(request, pk)


@login_required
@require_POST
def partecipante_aggiungi(request, pk: int):
    riesame = get_object_or_404(Riesame, pk=pk)
    negato = _modificabile(request, riesame)
    if negato:
        return negato
    form = PartecipanteForm(request.POST)
    if form.is_valid():
        partecipante = form.save(commit=False)
        partecipante.riesame = riesame
        partecipante.save()
    else:
        for errori in form.errors.values():
            for errore in errori:
                messages.error(request, errore)
    return redirect(reverse("sistema_gestione:riesame_dettaglio", args=[pk]) + "#partecipanti")


@login_required
@require_POST
def partecipante_togli(request, pk: int, partecipante_pk: int):
    riesame = get_object_or_404(Riesame, pk=pk)
    negato = _modificabile(request, riesame)
    if negato:
        return negato
    get_object_or_404(RiesamePartecipante, pk=partecipante_pk, riesame=riesame).delete()
    return redirect(reverse("sistema_gestione:riesame_dettaglio", args=[pk]) + "#partecipanti")


@login_required
def obiettivo(request, pk: int, obiettivo_pk: int | None = None):
    """Nuovo obiettivo o modifica; in un verbale approvato si registra solo l'andamento."""
    if not _has_perm(request, PERM_RIESAME_EDIT):
        return _nega(request, _NEGATO)
    riesame = get_object_or_404(Riesame, pk=pk)
    oggetto = get_object_or_404(RiesameObiettivo, pk=obiettivo_pk, riesame=riesame) if obiettivo_pk else None
    if oggetto is None and not riesame.modificabile:
        messages.error(request, "Il verbale non è in bozza: non si aggiungono obiettivi.")
        return redirect("sistema_gestione:riesame_dettaglio", pk=pk)
    classe = ObiettivoForm if riesame.modificabile else ObiettivoAndamentoForm
    form = classe(request.POST or None, instance=oggetto)
    if request.method == "POST" and form.is_valid():
        salvato = form.save(commit=False)
        salvato.riesame = riesame
        salvato.save()
        log_action(request, "riesame_obiettivo_salvato", MODULE, {"id": salvato.pk, "riesame": riesame.pk}, oggetto=riesame)
        return redirect(reverse("sistema_gestione:riesame_dettaglio", args=[pk]) + "#obiettivi")
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Obiettivo del riesame", "form": form,
        "indietro": reverse("sistema_gestione:riesame_dettaglio", args=[pk])})


@login_required
@require_POST
def obiettivo_togli(request, pk: int, obiettivo_pk: int):
    riesame = get_object_or_404(Riesame, pk=pk)
    negato = _modificabile(request, riesame)
    if negato:
        return negato
    get_object_or_404(RiesameObiettivo, pk=obiettivo_pk, riesame=riesame).delete()
    return redirect(reverse("sistema_gestione:riesame_dettaglio", args=[pk]) + "#obiettivi")


def _transizione(request, pk: int, permesso: str, azione, evento: str, successo: str):
    if not _has_perm(request, permesso):
        return _nega(request, _NEGATO)
    with transaction.atomic():
        riesame = get_object_or_404(Riesame.objects.select_for_update(), pk=pk)
        try:
            azione(riesame)
        except service.TransizioneNonAmmessa as exc:
            messages.error(request, str(exc))
            return redirect("sistema_gestione:riesame_dettaglio", pk=pk)
        log_action(request, evento, MODULE, {"id": riesame.pk}, oggetto=riesame)
    messages.success(request, successo)
    return redirect("sistema_gestione:riesame_dettaglio", pk=pk)


@login_required
@require_POST
def proponi(request, pk: int):
    return _transizione(request, pk, PERM_RIESAME_EDIT, service.proponi, "riesame_proposto", "Verbale proposto alla Direzione.")


@login_required
@require_POST
def riporta_in_bozza(request, pk: int):
    return _transizione(request, pk, PERM_RIESAME_EDIT, service.riporta_in_bozza, "riesame_riportato_in_bozza",
                        "Verbale riportato in bozza.")


@login_required
@require_POST
def approva(request, pk: int):
    return _transizione(request, pk, PERM_RIESAME_APPROVA, lambda r: service.approva(r, utente=request.user),
                        "riesame_approvato", "Verbale approvato: da ora non cambia più.")


@login_required
def pdf(request, pk: int):
    if not _has_perm(request, PERM_RIESAME_VIEW):
        return _nega(request, _NEGATO)
    from .exports import riesame_pdf

    riesame = get_object_or_404(Riesame, pk=pk)
    log_action(request, "riesame_pdf", MODULE, {"id": riesame.pk}, oggetto=riesame)
    risposta = HttpResponse(riesame_pdf(riesame), content_type="application/pdf")
    risposta["Content-Disposition"] = f'attachment; filename="MOD062_Verbale_riesame_{riesame.data:%Y%m%d}.pdf"'
    return risposta


@login_required
@require_POST
def carica_firmata(request, pk: int):
    if not _has_perm(request, PERM_RIESAME_EDIT):
        return _nega(request, _NEGATO)
    riesame = get_object_or_404(Riesame, pk=pk)
    if riesame.stato != Riesame.STATO_APPROVATO:
        messages.error(request, "La copia firmata si carica dopo l'approvazione.")
        return redirect("sistema_gestione:riesame_dettaglio", pk=pk)
    form = CopiaFirmataForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(form.errors.get("file", ["File non valido."])))
        return redirect("sistema_gestione:riesame_dettaglio", pk=pk)
    caricato = form.cleaned_data["file"]
    riesame.copia_firmata.save(f"MOD062_{riesame.data:%Y%m%d}_firmata.pdf", caricato, save=False)
    riesame.copia_firmata_nome = Path(caricato.name).name[:255]
    riesame.save(update_fields=["copia_firmata", "copia_firmata_nome", "updated_at"])
    log_action(request, "riesame_copia_firmata_caricata", MODULE, {"id": riesame.pk}, oggetto=riesame)
    messages.success(request, "Copia firmata caricata.")
    return redirect("sistema_gestione:riesame_dettaglio", pk=pk)


@login_required
def copia_firmata(request, pk: int):
    if not _has_perm(request, PERM_RIESAME_VIEW):
        return _nega(request, _NEGATO)
    riesame = get_object_or_404(Riesame, pk=pk)
    if not riesame.copia_firmata:
        raise Http404("Copia firmata non presente.")
    try:
        fh = riesame.copia_firmata.open("rb")
    except FileNotFoundError as exc:
        raise Http404("File non trovato.") from exc
    log_action(request, "riesame_copia_firmata_scaricata", MODULE, {"id": riesame.pk}, oggetto=riesame)
    return FileResponse(fh, as_attachment=True, filename=f"MOD062_{riesame.data:%Y%m%d}_firmata.pdf",
                        content_type="application/pdf")
