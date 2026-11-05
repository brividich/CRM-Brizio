"""Registro FAI: prende il posto del file «Situazione FAI-ISIR» (MT CN 15 §5.10)."""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.audit import log_action
from core.csv_export import csv_download_response

from ..access import can_manage_project, has_task_permission, scoped_projects_queryset, task_permissions_required
from ..fai_regole import CAUSALI, serve_motivo, tipo_proposto
from ..models import FaiPiano, FaiRecord, FaiStato, FaiTipo, ProjectTechRef, TechRefKind
from ..services.fai import allinea_riga, numero_piano_interno, righe_registro, trova_o_crea_articolo
from ..services.notify import notify_user
from ..tech_paths import normalizza_percorso
from ._shared import _tasks_shell_context, _utenti_riga_rapida

VISTE = (
    ("", "Tutti"),
    ("da_ripetere", "Da ripetere"),
    ("da_verificare", "Oltre 18 mesi"),
    ("in_corso", "In corso"),
    ("date_mancanti", "Senza date"),
)


class FaiForm(forms.Form):
    client_name = forms.CharField(max_length=180, required=False)
    part_number = forms.CharField(max_length=120)
    causale = forms.ChoiceField(choices=[(c[0], c[1]) for c in CAUSALI])
    tipo = forms.ChoiceField(choices=FaiTipo.choices)
    motivo = forms.CharField(required=False, max_length=1000)
    piano_tipo = forms.ChoiceField(choices=FaiPiano.choices)
    piano_numero = forms.CharField(max_length=160, required=False)
    stato = forms.ChoiceField(choices=FaiStato.choices)
    data_invio = forms.DateField(required=False)
    path = forms.CharField(max_length=500, required=False)
    responsabile = forms.IntegerField(required=False)
    ultima_produzione = forms.DateField(required=False)
    ultima_spedizione = forms.DateField(required=False)
    scadenza_cliente = forms.DateField(required=False)
    note = forms.CharField(required=False, max_length=4000)

    def clean_path(self):
        try:
            return normalizza_percorso(self.cleaned_data.get("path"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_responsabile(self):
        pk = self.cleaned_data.get("responsabile")
        if pk is None:
            return None
        from ..forms import task_active_users_queryset

        utente = task_active_users_queryset().filter(pk=pk).first()
        if utente is None:
            raise forms.ValidationError("Responsabile non valido.")
        return utente

    def clean(self):
        dati = super().clean()
        if serve_motivo(dati.get("causale", ""), dati.get("tipo", "")) and not (dati.get("motivo") or "").strip():
            self.add_error("motivo", "La MT CN 15 qui chiede il FAI completo: scrivi perché basta un Delta FAI.")
        return dati


def _vede_tutto(request) -> bool:
    return has_task_permission(request, "tasks_admin")


def _fai_visibili(request):
    """Cliente e P/N sono dati commerciali: fuori dal proprio ambito si vedono solo con la gestione."""
    records = FaiRecord.objects.select_related("articolo", "project", "responsabile")
    if _vede_tutto(request):
        return records
    return records.filter(project__in=scoped_projects_queryset(request))


def _puo_modificare(request, record: FaiRecord) -> bool:
    if _vede_tutto(request) or record.responsabile_id == request.user.pk:
        return True
    return bool(record.project and can_manage_project(request, record.project))


def _puo_creare(request, project) -> bool:
    if _vede_tutto(request):
        return True
    if project is None:
        return False
    return can_manage_project(request, project) or request.user.pk in project.team_user_ids


def _esporta(righe):
    response, writer = csv_download_response("registro_fai.csv", delimiter=";")
    writer.writerow([
        "Cliente", "P/N", "Numero piano", "Tipo", "Causale", "Stato FAI", "Data invio",
        "Fine ultima produzione", "Ultima spedizione", "Situazione", "Responsabile",
    ])
    for riga in righe:
        fai, articolo = riga["fai"], riga["articolo"]
        writer.writerow([
            articolo.client_name, articolo.part_number, fai.piano_numero, fai.get_tipo_display(), fai.causale_label,
            fai.get_stato_display(), fai.data_invio or "", articolo.ultima_produzione or "",
            articolo.ultima_spedizione or "", riga["situazione"].etichetta,
            fai.responsabile.get_full_name() or fai.responsabile.username if fai.responsabile else "",
        ])
    return response


@task_permissions_required("tasks_view")
def fai_registro(request):
    tutte = righe_registro(_fai_visibili(request))
    conteggi = {}
    for riga in tutte:
        conteggi[riga["situazione"].codice] = conteggi.get(riga["situazione"].codice, 0) + 1

    vista = request.GET.get("vista", "")
    vista = vista if vista in dict(VISTE) else ""
    q = (request.GET.get("q") or "").strip()
    righe = [r for r in tutte if not vista or r["situazione"].codice == vista]
    if q:
        testo = q.lower()
        righe = [
            r for r in righe
            if testo in f"{r['articolo'].client_name} {r['articolo'].part_number} {r['fai'].piano_numero}".lower()
        ]
    # Prima quello che richiede una decisione, poi il resto.
    ordine = {"da_ripetere": 0, "da_verificare": 1, "in_corso": 2, "date_mancanti": 3, "in_regola": 4}
    righe.sort(key=lambda r: (ordine[r["situazione"].codice], r["articolo"].part_number.lower()))

    if request.GET.get("formato") == "csv":
        log_action(request, "kickoff_fai_esporta", "tasks", {"vista": vista, "righe": len(righe)})
        return _esporta(righe)

    return render(request, "tasks/fai_registro.html", {
        **_tasks_shell_context(request, active="fai"),
        "page_title": "Registro FAI",
        "righe": righe,
        "viste": [
            {"codice": codice, "etichetta": etichetta, "conta": conteggi.get(codice, 0) if codice else len(tutte)}
            for codice, etichetta in VISTE
        ],
        "vista": vista,
        "q": q,
        "fai_puo_creare": _vede_tutto(request),
    })


def _utenti(project) -> dict:
    if project:
        return _utenti_riga_rapida(project)
    from ..forms import task_active_users_queryset, user_display_label

    return {"team": [], "altri": [(u.pk, user_display_label(u)) for u in task_active_users_queryset()]}


def _intero(valore):
    return int(valore) if str(valore or "").isdigit() else None


def _iso(giorno) -> str:
    """Il campo date vuole l'ISO, sia dal record sia dal POST da ripresentare."""
    return giorno.isoformat() if giorno else ""


def _contesto_scheda(request, form, record, project, ref, *, modificabile: bool) -> dict:
    articolo = record.articolo if record else None
    return {
        **_tasks_shell_context(request, active="tech_refs" if project else "fai", project=project),
        "page_title": "Scheda FAI",
        "form": form,
        "record": record,
        "fai_project": project,
        "fai_ref": ref,
        "modificabile": modificabile,
        "causali": [
            {"valore": c[0], "breve": c[1], "esteso": c[2], "tipo": tipo_proposto(c[0])} for c in CAUSALI
        ],
        "piani": FaiPiano.choices,
        "stati": FaiStato.choices,
        "utenti": _utenti(project),
        "responsabile_scelto": _intero(form["responsabile"].value()),
        "storico": articolo.fai.exclude(pk=record.pk) if articolo else [],
    }


def _iniziali(record, project, ref, richiesta) -> dict:
    if record:
        articolo = record.articolo
        return {
            "client_name": articolo.client_name, "part_number": articolo.part_number, "causale": record.causale,
            "tipo": record.tipo, "motivo": record.motivo, "piano_tipo": record.piano_tipo,
            "piano_numero": record.piano_numero, "stato": record.stato, "data_invio": _iso(record.data_invio),
            "path": record.path, "responsabile": record.responsabile_id,
            "ultima_produzione": _iso(articolo.ultima_produzione), "ultima_spedizione": _iso(articolo.ultima_spedizione),
            "scadenza_cliente": _iso(articolo.scadenza_cliente), "note": record.note,
        }
    causale = richiesta.GET.get("causale", "")
    causale = causale if causale in {c[0] for c in CAUSALI} else ""
    return {
        "client_name": project.client_name if project else "",
        "part_number": project.part_number if project else "",
        "causale": causale,
        "tipo": tipo_proposto(causale) if causale else "",
        "piano_tipo": FaiPiano.CLIENTE,
        "piano_numero": ref.code if ref else "",
        "stato": FaiStato.DA_ESEGUIRE,
        "path": ref.path if ref else "",
        "responsabile": ref.assigned_to_id if ref else None,
    }


@task_permissions_required("tasks_view")
def fai_scheda(request, fai_id: int | None = None):
    """Nuovo FAI (dal registro o da una commessa) oppure scheda di quello esistente."""
    record = get_object_or_404(_fai_visibili(request), pk=fai_id) if fai_id else None
    project = record.project if record else None
    ref = None
    if record is None:
        sorgente = request.POST if request.method == "POST" else request.GET
        if (sorgente.get("project") or "").isdigit():
            project = scoped_projects_queryset(request).filter(pk=int(sorgente["project"])).first()
            if project is None:
                raise Http404
        if project and (sorgente.get("ref") or "").isdigit():
            ref = ProjectTechRef.objects.filter(
                pk=int(sorgente["ref"]), project=project, kind=TechRefKind.FAI, fai_record__isnull=True
            ).first()

    modificabile = _puo_modificare(request, record) if record else _puo_creare(request, project)
    if not record and not modificabile:
        raise PermissionDenied

    if request.method == "POST":
        if not modificabile:
            raise PermissionDenied
        form = FaiForm(request.POST)
        if form.is_valid():
            record = _salva(request, form.cleaned_data, record, project, ref)
            messages.success(request, f"FAI di {record.articolo.part_number} salvato.")
            if project:
                return redirect("tasks:project_tech_refs", project.pk)
            return redirect("tasks:fai_registro")
    else:
        form = FaiForm(initial=_iniziali(record, project, ref, request))
    return render(
        request, "tasks/fai_scheda.html", _contesto_scheda(request, form, record, project, ref, modificabile=modificabile)
    )


def _salva(request, dati, record, project, ref) -> FaiRecord:
    prima = record.responsabile_id if record else None
    with transaction.atomic():
        articolo = trova_o_crea_articolo(dati["client_name"], dati["part_number"])
        articolo.ultima_produzione = dati["ultima_produzione"]
        articolo.ultima_spedizione = dati["ultima_spedizione"]
        articolo.scadenza_cliente = dati["scadenza_cliente"]
        articolo.save()

        nuovo = record is None
        if nuovo:
            record = FaiRecord(project=project, tech_ref=ref, created_by=request.user)
        record.articolo = articolo
        for campo in ("causale", "tipo", "motivo", "piano_tipo", "stato", "path", "note"):
            setattr(record, campo, dati[campo])
        record.data_invio = dati["data_invio"]
        record.responsabile = dati["responsabile"]
        record.piano_numero = dati["piano_numero"].strip()
        if not record.piano_numero and record.piano_tipo == FaiPiano.INTERNO:
            record.piano_numero = numero_piano_interno(articolo)
        record.save()
        allinea_riga(record, request.user)

    log_action(request, "kickoff_fai_salva", "tasks", {
        "id": record.pk, "project_id": record.project_id, "nuovo": nuovo, "tipo": record.tipo,
        "causale": record.causale, "stato": record.stato,
    })
    if record.responsabile and record.responsabile_id not in (prima, request.user.pk):
        notify_user(
            record.responsabile,
            f"Sei responsabile del FAI di {articolo.part_number}.",
            reverse("tasks:fai_scheda", args=[record.pk]),
        )
    return record

