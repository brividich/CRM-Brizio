"""View dell'app gestione_specifiche.

F1: elenco base + download allegato protetto. L'elenco ricco con pill di stato,
filtri e azioni inline arriva in F7; il flusso MOD.133 (HTMX) in F3.
Gating: `@login_required` + ACLMiddleware (binding canonico per rotta).
"""
from __future__ import annotations

import csv
import io
import json
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_fsm import TransitionNotAllowed
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import constants as C
from .ai_copilota import proponi_righe_mod133, proponi_tag, ricerca_semantica
from .distribuzione import DerogaCopieRichiesta, crea_distribuzione
from .forms import ApprovazioneForm, DistribuzioneForm, RigaMOD133FormSet, SpecificaForm
from .models import AzioneOFI, Distribuzione, MOD133, RigaMOD133, Specifica
from .ofi import approva_azione_ofi, crea_ofi_da_riga

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
    """Elenco/archivio ricercabile. Default = solo specifiche attive; lo storico
    (incluse superate/terminali S4/S6/S7/S8) è raggiungibile col toggle o filtrando
    per stato/intervallo date."""
    mostra_storico = request.GET.get("storico") == "1"
    f_stato = request.GET.get("stato", "").strip()
    f_tipo = request.GET.get("tipo", "").strip()
    f_cliente = request.GET.get("cliente", "").strip()
    f_tag = request.GET.get("tag", "").strip()
    f_q = request.GET.get("q", "").strip()
    f_dal = request.GET.get("dal", "").strip()
    f_al = request.GET.get("al", "").strip()

    qs = Specifica.objects.all().select_related("mod133")
    if not mostra_storico and not f_stato:
        qs = qs.filter(stato__in=C.STATI_ATTIVI)
    if f_stato:
        qs = qs.filter(stato=f_stato)
    if f_tipo:
        qs = qs.filter(tipo=f_tipo)
    if f_cliente:
        qs = qs.filter(cliente__icontains=f_cliente)
    if f_tag:
        qs = qs.filter(tag__icontains=f_tag)
    if f_q:
        qs = qs.filter(Q(codice__icontains=f_q) | Q(titolo__icontains=f_q))
    if f_dal:
        qs = qs.filter(data_inserimento__date__gte=f_dal)
    if f_al:
        qs = qs.filter(data_inserimento__date__lte=f_al)
    qs = qs.order_by("-data_inserimento", "codice")

    context = {
        "specifiche": qs[:500],
        "tot": qs.count(),
        "mostra_storico": mostra_storico,
        "f": {"stato": f_stato, "tipo": f_tipo, "cliente": f_cliente,
              "tag": f_tag, "q": f_q, "dal": f_dal, "al": f_al},
        "STATO_CHOICES": C.STATO_CHOICES,
        "TIPO_CHOICES": C.TIPO_CHOICES,
        "C": C,
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
    azioni_ofi = (
        AzioneOFI.objects.filter(riga_mod133__mod133=mod).select_related("approvatore", "riga_mod133")
        if mod else []
    )
    context = {
        "spec": spec,
        "mod": mod,
        "righe": mod.righe.all() if mod else [],
        "azioni_ofi": azioni_ofi,
        "distribuzioni": spec.distribuzioni.prefetch_related("destinatari"),
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


# ---------------------------------------------------------------------------
# F5 — OFI → MOD.174 + sotto-flusso documento CN
# ---------------------------------------------------------------------------

@login_required
@require_POST
def riga_genera_ofi(request, pk: int, riga_id: int):
    """Genera l'OFI per una riga con impatto, SU CONFERMA (mai automatica)."""
    spec = get_object_or_404(Specifica, pk=pk)
    riga = get_object_or_404(RigaMOD133, pk=riga_id, mod133__specifica=spec)
    try:
        azione = crea_ofi_da_riga(riga, attore=request.user)
        messages.success(request, f"OFI {azione.ofi} generato per la riga «{riga.argomento}».")
    except ValidationError as exc:
        messages.error(request, f"Impossibile generare l'OFI: {exc.messages[0] if exc.messages else exc}")
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


@login_required
@require_POST
def azione_ofi_approva(request, azione_id: int):
    """Approva/respinge il sotto-flusso documento CN (modo da APPROVAZIONE_DOC_CN_MODE)."""
    azione = get_object_or_404(
        AzioneOFI.objects.select_related("riga_mod133__mod133__specifica"), pk=azione_id)
    spec = azione.riga_mod133.mod133.specifica
    esito = request.POST.get("esito", C.AZIONE_OFI_APPROVATA)
    try:
        approva_azione_ofi(azione, approvatore=request.user, esito=esito)
        messages.success(request, f"Azione OFI {azione.ofi}: {azione.get_stato_display()}.")
    except ValidationError as exc:
        messages.error(request, f"Operazione non consentita: {exc.messages[0] if exc.messages else exc}")
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


# ---------------------------------------------------------------------------
# F6 — Distribuzione + tracciamento copie
# ---------------------------------------------------------------------------

@login_required
def distribuzione_nuova(request, pk: int):
    """Crea una distribuzione tracciata; per le cartacee applica la regola copie
    (warning + deroga giustificata, no blocco rigido)."""
    spec = get_object_or_404(Specifica, pk=pk)
    deroga_richiesta = False
    if request.method == "POST":
        form = DistribuzioneForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                dist = crea_distribuzione(
                    spec, canale=cd["canale"], reparti=cd["destinatari"],
                    cartacea=cd["cartacea"],
                    n_copie_distribuite=cd.get("n_copie_distribuite") or 0,
                    n_copie_ritirate=cd.get("n_copie_ritirate") or 0,
                    deroga_giustificazione=cd.get("deroga_giustificazione", ""),
                    attore=request.user,
                )
                if dist.deroga_giustificazione:
                    messages.warning(request, "Distribuzione registrata CON deroga sulle copie.")
                else:
                    messages.success(request, "Distribuzione registrata.")
                return redirect("gestione_specifiche:dettaglio", pk=spec.pk)
            except DerogaCopieRichiesta as exc:
                deroga_richiesta = True
                messages.warning(
                    request,
                    f"Copie non corrispondenti: la revisione precedente aveva {exc.attese} copie "
                    f"distribuite ma ne risultano {exc.ritirate} ritirate. Inserisci una "
                    f"giustificazione di deroga per procedere.",
                )
    else:
        form = DistribuzioneForm()
    return render(request, "gestione_specifiche/distribuzione_form.html",
                  {"spec": spec, "form": form, "deroga_richiesta": deroga_richiesta})


# ---------------------------------------------------------------------------
# F7 — Azioni di stato SSR (inline) + storico consultabile + export
# ---------------------------------------------------------------------------

def _esegui_transizione(request, spec, azione_label, fn, **kwargs):
    try:
        fn(attore=request.user, **kwargs)
        spec.save()
        messages.success(request, f"{azione_label} eseguita.")
    except (TransitionNotAllowed, ValidationError) as exc:
        msg = exc.messages[0] if isinstance(exc, ValidationError) and exc.messages else str(exc)
        messages.error(request, f"Operazione non consentita: {msg}")


@login_required
@require_POST
def sospendi_view(request, pk: int):
    spec = get_object_or_404(Specifica, pk=pk)
    motivo = request.POST.get("motivo", "").strip()
    _esegui_transizione(request, spec, "Sospensione", spec.sospendi,
                        motivo=motivo, data=timezone.now().date())
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


@login_required
@require_POST
def ripristina_view(request, pk: int):
    spec = get_object_or_404(Specifica, pk=pk)
    motivo = request.POST.get("motivo", "").strip()
    _esegui_transizione(request, spec, "Ripristino", spec.ripristina, motivo=motivo)
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


@login_required
@require_POST
def annulla_view(request, pk: int):
    spec = get_object_or_404(Specifica, pk=pk)
    motivo = request.POST.get("motivo", "").strip()
    _esegui_transizione(request, spec, "Annullamento", spec.annulla, motivo=motivo)
    return redirect("gestione_specifiche:dettaglio", pk=spec.pk)


def _catena_revisioni(spec: Specifica):
    """Restituisce la catena lineare di revisioni dalla radice all'ultima."""
    radice = spec
    visti = set()
    while radice.revisione_precedente_id and radice.revisione_precedente_id not in visti:
        visti.add(radice.id)
        radice = radice.revisione_precedente
    catena, nodo, visti2 = [], radice, set()
    while nodo is not None and nodo.id not in visti2:
        visti2.add(nodo.id)
        catena.append(nodo)
        nodo = nodo.revisioni_successive.order_by("data_inserimento").first()
    return catena


def _ricostruzione_punto_nel_tempo(spec: Specifica):
    """Ultimo snapshot dei metadati di quando la specifica era 'In validità'
    (dal payload di EventoSpecifica), per ricostruire il punto-nel-tempo."""
    evt = (
        spec.eventi.filter(stato_a=C.STATO_IN_VALIDITA).order_by("-timestamp").first()
        or spec.eventi.order_by("-timestamp").first()
    )
    if evt and isinstance(evt.payload, dict):
        return evt.payload.get("snapshot")
    return None


@login_required
def scheda_storico(request, pk: int):
    spec = get_object_or_404(Specifica.objects.select_related("mod133"), pk=pk)
    mod = MOD133.objects.filter(specifica=spec).first()
    azioni_ofi = AzioneOFI.objects.filter(riga_mod133__mod133=mod) if mod else []
    context = {
        "spec": spec,
        "catena": _catena_revisioni(spec),
        "eventi": spec.eventi.all(),
        "righe": mod.righe.all() if mod else [],
        "azioni_ofi": azioni_ofi,
        "distribuzioni": spec.distribuzioni.prefetch_related("destinatari"),
        "snapshot": _ricostruzione_punto_nel_tempo(spec),
        "C": C,
    }
    return render(request, "gestione_specifiche/scheda_storico.html", context)


@login_required
def storico_export_csv(request, pk: int):
    spec = get_object_or_404(Specifica, pk=pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="storico_{spec.codice}_{spec.revisione or "0"}.csv"'
    response.write("﻿")  # BOM per Excel
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["timestamp", "stato_da", "stato_a", "trigger", "attore", "payload"])
    for e in spec.eventi.all():
        writer.writerow([
            e.timestamp.isoformat(), e.stato_da, e.stato_a, e.trigger,
            str(e.attore or ""), json.dumps(e.payload, ensure_ascii=False),
        ])
    return response


@login_required
def storico_export_pdf(request, pk: int):
    spec = get_object_or_404(Specifica, pk=pk)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"Storico specifica {spec.codice} rev.{spec.revisione or '0'}")
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawString(40, y, f"{spec.titolo} — stato attuale: {spec.get_stato_display()}")
    y -= 24
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Cronologia eventi (audit ISO 9001 / EN 9100)")
    y -= 16
    c.setFont("Helvetica", 8)
    for e in spec.eventi.all():
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 8)
        riga = f"{e.timestamp:%Y-%m-%d %H:%M}  {e.stato_da or '-'} -> {e.stato_a}  [{e.trigger}]  {e.attore or ''}"
        c.drawString(40, y, riga[:120])
        y -= 12
    c.showPage()
    c.save()
    buf.seek(0)
    return FileResponse(buf, as_attachment=True,
                        filename=f"storico_{spec.codice}_{spec.revisione or '0'}.pdf",
                        content_type="application/pdf")


# ---------------------------------------------------------------------------
# F9 — Copilota AI locale (proposte; l'umano valida e firma — mai auto-applicate)
# ---------------------------------------------------------------------------

@login_required
def ai_precompila_mod133(request, pk: int):
    """Proposta AI di righe MOD.133 dal PDF (JSON). NON salva nulla."""
    spec = get_object_or_404(Specifica, pk=pk)
    proposta = proponi_righe_mod133(spec)
    proposta["nota"] = "Proposta AI: rivedi e inserisci manualmente. Nessuna riga è stata salvata."
    return JsonResponse(proposta)


@login_required
def ai_proponi_tag(request, pk: int):
    """Proposta AI del TAG di processo (JSON). NON salva nulla."""
    spec = get_object_or_404(Specifica, pk=pk)
    testo = f"{spec.titolo}\n{spec.note}\n{spec.cliente}"
    proposta = proponi_tag(testo)
    proposta["nota"] = "Proposta AI: applica il TAG manualmente se corretto. Nessuna modifica salvata."
    return JsonResponse(proposta)


@login_required
def ricerca_semantica_view(request):
    """Ricerca semantica sull'archivio specifiche (sola lettura)."""
    q = request.GET.get("q", "").strip()
    risultati = ricerca_semantica(q) if q else []
    if request.GET.get("format") == "json" or request.headers.get("HX-Request"):
        return JsonResponse({"query": q, "risultati": risultati})
    return render(request, "gestione_specifiche/ricerca.html",
                  {"q": q, "risultati": risultati})
