"""Fase 4: checklist di audit per norma (EN 9100 Folder B, ISO 45001, UNI/PdR 125). Viste fail-closed."""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_AUDIT_EDIT, PERM_AUDIT_VIEW
from .audit_views import _deny
from .models import ChecklistDomanda, ChecklistModello, ChecklistSezione
from .services import checklist_norme as service
from .views import MODULE, _has_perm


class ChecklistSezioneForm(forms.ModelForm):
    class Meta:
        model = ChecklistSezione
        fields = ["codice", "titolo", "criteri", "ordine"]
        widgets = {"criteri": forms.Textarea(attrs={"rows": 2})}
        labels = {"codice": "Codice (es. §4)", "criteri": "Criteri di verifica (procedure, moduli)"}


class ChecklistDomandaForm(forms.ModelForm):
    class Meta:
        model = ChecklistDomanda
        fields = ["punti", "testo", "ordine", "attiva"]
        widgets = {"testo": forms.Textarea(attrs={"rows": 2})}
        labels = {"punti": "Punti norma", "testo": "Domanda guida"}


def _url(modello: ChecklistModello, anchor: str = "") -> str:
    url = reverse("sistema_gestione:checklist_modello", kwargs={"pk": modello.pk})
    return f"{url}#{anchor}" if anchor else url


@login_required
def checklist_norme(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    norme = []
    for codice, info in service.NORME.items():
        revisioni = list(ChecklistModello.objects.filter(codice=codice).order_by("-revisione"))
        for modello in revisioni:
            modello.n_domande = ChecklistDomanda.objects.filter(sezione__modello=modello, attiva=True).count()
        norme.append({
            "codice": codice, "info": info, "revisioni": revisioni,
            "attiva": next((m for m in revisioni if m.attivo), None),
            "bozza_disponibile": codice in service.BOZZE and not revisioni,
        })
    return render(request, "sistema_gestione/pages/checklist_norme.html", {
        "page_title": "Checklist di audit per norma", "norme": norme,
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
    })


@login_required
@require_POST
def checklist_proponi(request, codice: str):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    if codice not in service.NORME:
        raise Http404
    try:
        modello = service.proponi_bozza(codice, utente=request.user)
    except service.ChecklistNonModificabile as exc:
        messages.error(request, str(exc))
        return redirect("sistema_gestione:checklist_norme")
    log_action(request, "checklist_bozza_proposta", MODULE, {"codice": codice}, oggetto=modello)
    messages.success(request, "Bozza creata, inattiva: verifica domande e criteri, poi attivala.")
    return redirect(_url(modello))


@login_required
@transaction.atomic
def checklist_modello(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    modello = get_object_or_404(ChecklistModello, pk=pk)
    puo_modificare = _has_perm(request, PERM_AUDIT_EDIT)
    modificabile = puo_modificare and service.modificabile(modello)
    if request.method == "POST":
        if not modificabile:
            if not puo_modificare:
                return _deny(request)
            messages.error(request, "Questa revisione non è modificabile: aprine una nuova.")
            return redirect(_url(modello))
        return _salva(request, modello)
    sezioni = []
    for sezione in modello.sezioni.prefetch_related("domande"):
        sezioni.append({
            "sezione": sezione,
            "form": ChecklistSezioneForm(instance=sezione, prefix=f"s{sezione.pk}"),
            "domande": [{"domanda": d, "form": ChecklistDomandaForm(instance=d, prefix=f"d{d.pk}")} for d in sezione.domande.all()],
            "nuova": ChecklistDomandaForm(prefix=f"n{sezione.pk}", initial={"ordine": (sezione.domande.count() + 1) * 10}),
        })
    return render(request, "sistema_gestione/pages/checklist_modello.html", {
        "page_title": f"{modello.titolo} Rev.{modello.revisione}", "modello": modello, "sezioni": sezioni,
        "info": service.NORME.get(modello.codice, {}),
        "nuova_sezione": ChecklistSezioneForm(prefix="ns", initial={"ordine": (modello.sezioni.count() + 1) * 10}),
        "puo_modificare": puo_modificare, "modificabile": modificabile, "usato": service.usato(modello),
    })


def _salva(request, modello: ChecklistModello):
    azione = request.POST.get("azione", "")
    try:
        if azione == "sezione":
            sezione = get_object_or_404(ChecklistSezione, pk=request.POST.get("id"), modello=modello)
            form = ChecklistSezioneForm(request.POST, instance=sezione, prefix=f"s{sezione.pk}")
            ancora = f"sez-{sezione.pk}"
        elif azione == "nuova_sezione":
            form = ChecklistSezioneForm(request.POST, instance=ChecklistSezione(modello=modello), prefix="ns")
            ancora = "nuova-sezione"
        elif azione == "domanda":
            domanda = get_object_or_404(ChecklistDomanda, pk=request.POST.get("id"), sezione__modello=modello)
            form = ChecklistDomandaForm(request.POST, instance=domanda, prefix=f"d{domanda.pk}")
            ancora = f"dom-{domanda.pk}"
        elif azione == "nuova_domanda":
            sezione = get_object_or_404(ChecklistSezione, pk=request.POST.get("id"), modello=modello)
            form = ChecklistDomandaForm(request.POST, instance=ChecklistDomanda(sezione=sezione), prefix=f"n{sezione.pk}")
            ancora = f"sez-{sezione.pk}"
        elif azione == "rimuovi_domanda":
            domanda = get_object_or_404(ChecklistDomanda, pk=request.POST.get("id"), sezione__modello=modello)
            ancora = f"sez-{domanda.sezione_id}"
            service.rimuovi_domanda(domanda)
            log_action(request, "checklist_domanda_rimossa", MODULE, {"punti": domanda.punti}, oggetto=modello)
            messages.success(request, "Domanda rimossa.")
            return redirect(_url(modello, ancora))
        elif azione == "rimuovi_sezione":
            sezione = get_object_or_404(ChecklistSezione, pk=request.POST.get("id"), modello=modello)
            service.rimuovi_sezione(sezione)
            log_action(request, "checklist_sezione_rimossa", MODULE, {"codice": sezione.codice}, oggetto=modello)
            messages.success(request, "Sezione rimossa con le sue domande.")
            return redirect(_url(modello))
        else:
            raise Http404
        if not form.is_valid():
            messages.error(request, "Dati non validi: " + " ".join(sum(form.errors.values(), [])))
            return redirect(_url(modello, ancora))
        oggetto = form.save(commit=False)
        if isinstance(oggetto, ChecklistSezione):
            service.salva_sezione(oggetto)
        else:
            service.salva_domanda(oggetto)
    except service.ChecklistNonModificabile as exc:
        messages.error(request, str(exc))
        return redirect(_url(modello))
    except ValidationError as exc:
        messages.error(request, "Dati non validi: " + " ".join(exc.messages))
        return redirect(_url(modello))
    log_action(request, "checklist_modificata", MODULE, {"azione": azione}, oggetto=modello)
    messages.success(request, "Salvato.")
    return redirect(_url(modello, ancora))


@login_required
@require_POST
@transaction.atomic
def checklist_revisione(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    modello = get_object_or_404(ChecklistModello, pk=pk)
    azione = request.POST.get("azione", "")
    try:
        if azione == "nuova":
            nuovo = service.nuova_revisione(modello, utente=request.user, motivo=request.POST.get("motivo", ""))
            log_action(request, "checklist_nuova_revisione", MODULE,
                       {"da": modello.revisione, "a": nuovo.revisione, "motivo": nuovo.motivo}, oggetto=nuovo)
            messages.success(request, f"Aperta la Rev.{nuovo.revisione}, inattiva: modificala e poi attivala.")
            return redirect(_url(nuovo))
        if azione == "attiva":
            service.attiva(modello, utente=request.user)
            log_action(request, "checklist_attivata", MODULE, {"revisione": modello.revisione}, oggetto=modello)
            messages.success(request, "Revisione attiva: verrà caricata negli audit avviati da ora con questa norma.")
        elif azione == "disattiva":
            service.disattiva(modello)
            log_action(request, "checklist_disattivata", MODULE, {"revisione": modello.revisione}, oggetto=modello)
            messages.success(request, "Revisione disattivata: gli audit avviati da ora non caricano domande per questa norma.")
        else:
            raise Http404
    except service.ChecklistNonModificabile as exc:
        messages.error(request, str(exc))
    return redirect(_url(modello))
