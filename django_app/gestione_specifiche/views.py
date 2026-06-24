"""View dell'app gestione_specifiche.

F1: elenco base + download allegato protetto. L'elenco ricco con pill di stato,
filtri e azioni inline arriva in F7; il flusso MOD.133 (HTMX) in F3.
Gating: `@login_required` + ACLMiddleware (binding canonico per rotta).
"""
from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_fsm import TransitionNotAllowed

from . import constants as C
from .forms import ApprovazioneForm, RigaMOD133FormSet, SpecificaForm
from .models import MOD133, Specifica

_INHERIT_FIELDS = ["codice", "titolo", "tipo", "fonte", "cliente", "tag",
                   "note", "commessa_ref", "famiglia_ref"]


def _incrementa_revisione(rev: str) -> str:
    rev = (rev or "").strip()
    if rev.isdigit():
        return str(int(rev) + 1)
    m = re.search(r"(\d+)$", rev)
    if m:
        return rev[: m.start()] + str(int(m.group(1)) + 1)
    return "1" if not rev else rev + ".1"


@login_required
def lista(request):
    """Elenco specifiche (versione base F1, default = solo attive)."""
    mostra_storico = request.GET.get("storico") == "1"
    qs = Specifica.objects.all().select_related("mod133")
    if not mostra_storico:
        qs = qs.filter(stato__in=C.STATI_ATTIVI)
    qs = qs.order_by("-data_inserimento", "codice")
    context = {
        "specifiche": qs[:500],
        "mostra_storico": mostra_storico,
        "tot": qs.count(),
    }
    return render(request, "gestione_specifiche/lista.html", context)


@login_required
def allegato_download(request, pk: int):
    """Download protetto dell'allegato di una specifica (storage privato)."""
    spec = get_object_or_404(Specifica, pk=pk)
    if not spec.allegato:
        raise Http404("Allegato non presente")
    try:
        fh = spec.allegato.open("rb")
    except FileNotFoundError as exc:
        raise Http404("File non trovato") from exc
    filename = spec.allegato.name.rsplit("/", 1)[-1]
    return FileResponse(fh, as_attachment=True, filename=filename)


# ---------------------------------------------------------------------------
# F3 — Flusso MOD.133 (metadati specifica, compilazione, approvazione)
# ---------------------------------------------------------------------------

@login_required
def dettaglio(request, pk: int):
    spec = get_object_or_404(Specifica.objects.select_related("mod133"), pk=pk)
    mod = MOD133.objects.filter(specifica=spec).first()
    context = {
        "spec": spec,
        "mod": mod,
        "righe": mod.righe.all() if mod else [],
        "eventi": spec.eventi.all()[:50],
        "C": C,
    }
    return render(request, "gestione_specifiche/dettaglio.html", context)


@login_required
def nuova_specifica(request):
    """Crea una nuova specifica; con ?da=<pk> eredita i campi e incrementa rev."""
    da = request.GET.get("da") or request.POST.get("da")
    prev = get_object_or_404(Specifica, pk=da) if da else None

    if request.method == "POST":
        form = SpecificaForm(request.POST, request.FILES)
        if form.is_valid():
            spec = form.save(commit=False)
            if prev is not None:
                spec.revisione_precedente = prev
            spec.save()
            messages.success(request, "Specifica creata.")
            return redirect("gestione_specifiche:dettaglio", pk=spec.pk)
    else:
        initial = {}
        if prev is not None:
            initial = {f: getattr(prev, f) for f in _INHERIT_FIELDS}
            initial["revisione"] = _incrementa_revisione(prev.revisione)
        form = SpecificaForm(initial=initial)

    return render(request, "gestione_specifiche/specifica_form.html",
                  {"form": form, "prev": prev, "is_new": True})


@login_required
def modifica_specifica(request, pk: int):
    spec = get_object_or_404(Specifica, pk=pk)
    if spec.stato not in (C.STATO_BOZZA, C.STATO_FLOW_DOWN):
        messages.error(request, "Metadati modificabili solo in bozza o flow-down.")
        return redirect("gestione_specifiche:dettaglio", pk=spec.pk)
    if request.method == "POST":
        form = SpecificaForm(request.POST, request.FILES, instance=spec)
        if form.is_valid():
            form.save()
            messages.success(request, "Specifica aggiornata.")
            return redirect("gestione_specifiche:dettaglio", pk=spec.pk)
    else:
        form = SpecificaForm(instance=spec)
    return render(request, "gestione_specifiche/specifica_form.html",
                  {"form": form, "spec": spec, "is_new": False})


@login_required
@require_POST
def avvia_flow_down_view(request, pk: int):
    """S1→S2: crea il MOD.133 e apre la compilazione (DM)."""
    spec = get_object_or_404(Specifica, pk=pk)
    try:
        spec.avvia_flow_down(attore=request.user)
        spec.save()
        messages.success(request, "Flow-down avviato: MOD.133 creato.")
    except (TransitionNotAllowed, ValidationError) as exc:
        messages.error(request, f"Operazione non consentita: {exc}")
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


@login_required
@require_POST
def claim(request, pk: int):
    """Presa in carico ('dito'): assegna l'utente come compilatore del MOD.133."""
    spec = get_object_or_404(Specifica, pk=pk)
    mod = MOD133.objects.filter(specifica=spec).first()
    if mod is None:
        messages.error(request, "MOD.133 non ancora creato.")
    elif mod.compilatore_id and mod.compilatore_id != request.user.id:
        messages.error(request, "Task già preso in carico da un altro utente.")
    else:
        mod.compilatore = request.user
        mod.save(update_fields=["compilatore", "updated_at"])
        messages.success(request, "Task preso in carico.")
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


@login_required
def mod133_compila(request, pk: int):
    """Compilazione righe MOD.133 con formset (HTMX add/remove lato client)."""
    spec = get_object_or_404(Specifica, pk=pk)
    mod = MOD133.objects.filter(specifica=spec).first()
    if mod is None:
        messages.error(request, "Avvia prima il flow-down.")
        return redirect("gestione_specifiche:dettaglio", pk=spec.pk)
    # claim implicito del compilatore
    if not mod.compilatore_id:
        mod.compilatore = request.user
        mod.save(update_fields=["compilatore", "updated_at"])

    if request.method == "POST":
        formset = RigaMOD133FormSet(request.POST, instance=mod, prefix="righe")
        if formset.is_valid():
            formset.save()
            messages.success(request, "Righe MOD.133 salvate.")
            return redirect("gestione_specifiche:mod133_compila", pk=spec.pk)
    else:
        formset = RigaMOD133FormSet(instance=mod, prefix="righe")
    return render(request, "gestione_specifiche/mod133_compila.html",
                  {"spec": spec, "mod": mod, "formset": formset})


@login_required
def mod133_riga_add(request, pk: int):
    """HTMX: ritorna una nuova riga vuota del formset all'indice richiesto."""
    spec = get_object_or_404(Specifica, pk=pk)
    mod = get_object_or_404(MOD133, specifica=spec)
    try:
        idx = int(request.GET.get("i", "0"))
    except ValueError:
        idx = 0
    formset = RigaMOD133FormSet(instance=mod, prefix="righe")
    form = formset.empty_form
    html = render(request, "gestione_specifiche/partials/_riga_form.html",
                  {"form": form, "index": idx}).content.decode("utf-8")
    # sostituisce il placeholder __prefix__ con l'indice reale
    html = html.replace("__prefix__", str(idx))
    return HttpResponse(html)


@login_required
@require_POST
def mod133_chiudi(request, pk: int):
    """Chiusura compilazione: firma compilatore + data, pronta per approvazione."""
    spec = get_object_or_404(Specifica, pk=pk)
    mod = get_object_or_404(MOD133, specifica=spec)
    if not mod.compilatore_id:
        mod.compilatore = request.user
    mod.data_chiusura_compilazione = timezone.now()
    mod.save(update_fields=["compilatore", "data_chiusura_compilazione", "updated_at"])
    messages.success(request, "Compilazione chiusa: in attesa di approvazione.")
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


@login_required
def mod133_approva(request, pk: int):
    """Approvazione/respingimento del flow-down (approvatore ≠ compilatore)."""
    spec = get_object_or_404(Specifica, pk=pk)
    mod = get_object_or_404(MOD133, specifica=spec)
    if request.method != "POST":
        return render(request, "gestione_specifiche/mod133_approva.html",
                      {"spec": spec, "mod": mod, "form": ApprovazioneForm()})

    form = ApprovazioneForm(request.POST)
    if not form.is_valid():
        return render(request, "gestione_specifiche/mod133_approva.html",
                      {"spec": spec, "mod": mod, "form": form})

    esito = form.cleaned_data["esito"]
    note = form.cleaned_data.get("note", "")
    # Segregazione dei compiti: l'approvatore deve essere diverso dal compilatore.
    if esito == C.ESITO_APPROVATO and mod.compilatore_id == request.user.id:
        messages.error(request, "L'approvatore deve essere diverso dal compilatore.")
        return redirect("gestione_specifiche:dettaglio", pk=spec.pk)
    # l'approvatore prende in carico l'approvazione ('dito')
    mod.approvatore = request.user
    mod.esito = esito
    mod.data_approvazione = timezone.now()
    mod.save(update_fields=["approvatore", "esito", "data_approvazione", "updated_at"])
    try:
        if esito == C.ESITO_APPROVATO:
            spec.approva_flow_down(attore=request.user)
        else:
            spec.respingi_flow_down(attore=request.user, motivo=note)
        spec.save()
        messages.success(request, "Esito registrato.")
    except (TransitionNotAllowed, ValidationError) as exc:
        messages.error(request, f"Operazione non consentita: {exc}")
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)
