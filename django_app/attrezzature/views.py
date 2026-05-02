from __future__ import annotations

import os
import tempfile
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone

from core.audit import log_action
from core.legacy_utils import get_legacy_user, is_legacy_admin

from .forms import (
    AttrezzaturaForm,
    AttrezzaturaBlockForm,
    AttrezzaturaTaskForm,
    EmbeddedPreviewForm,
    ImportUploadForm,
    ProgressUpdateForm,
    TaskBlockForm,
    TaskCompleteForm,
)
from .models import (
    Attrezzatura,
    AttrezzaturaPartNumber,
    AttrezzaturaStato,
    AttrezzaturaTask,
    AttrezzaturaTaskStato,
    AttrezzaturaTaskTipo,
    AttrezzaturaTaskOrigine,
    AttrezzaturaTaskPriorita,
    DisponibilitaStato,
)
from .services import excel_import, kickoff_integration, workflow


def _dashboard_counters() -> dict:
    today = timezone.localdate()
    open_statuses = [AttrezzaturaTaskStato.APERTA, AttrezzaturaTaskStato.IN_LAVORAZIONE, AttrezzaturaTaskStato.BLOCCATA]
    return {
        "totali": Attrezzatura.objects.count(),
        "in_corso": Attrezzatura.objects.filter(stato=AttrezzaturaStato.IN_CORSO).count(),
        "da_verificare": Attrezzatura.objects.filter(disponibilita_stato=DisponibilitaStato.DA_VERIFICARE).count(),
        "non_disponibili": Attrezzatura.objects.filter(disponibilita_stato=DisponibilitaStato.NON_DISPONIBILE).count(),
        "da_creare": Attrezzatura.objects.filter(stato=AttrezzaturaStato.DA_CREARE).count(),
        "in_ritardo": Attrezzatura.objects.filter(
            data_consegna_prevista__lt=today
        ).exclude(stato__in=[AttrezzaturaStato.FINITA, AttrezzaturaStato.ANNULLATA, AttrezzaturaStato.PRONTA_PRODUZIONE]).count(),
        "finite": Attrezzatura.objects.filter(stato=AttrezzaturaStato.FINITA).count(),
        "pronte_produzione": Attrezzatura.objects.filter(stato=AttrezzaturaStato.PRONTA_PRODUZIONE).count(),
        "task_aperte": AttrezzaturaTask.objects.filter(stato__in=open_statuses).count(),
        "task_scadute": AttrezzaturaTask.objects.filter(stato__in=open_statuses, scadenza__lt=today).count(),
        "verifiche_disponibilita_aperte": AttrezzaturaTask.objects.filter(tipo=AttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA, stato__in=open_statuses).count(),
        "creazioni_attrezzo_aperte": AttrezzaturaTask.objects.filter(tipo=AttrezzaturaTaskTipo.CREAZIONE_ATTREZZO, stato__in=open_statuses).count(),
    }


def _base_context(active: str = "list") -> dict:
    return {
        "active": active,
        "counters": _dashboard_counters(),
        "stato_choices": AttrezzaturaStato.choices,
        "disponibilita_choices": DisponibilitaStato.choices,
        "task_tipo_choices": AttrezzaturaTaskTipo.choices,
        "task_stato_choices": AttrezzaturaTaskStato.choices,
        "task_priorita_choices": AttrezzaturaTaskPriorita.choices,
        "task_origine_choices": AttrezzaturaTaskOrigine.choices,
    }


def _can_delete_attrezzature(request) -> bool:
    if bool(getattr(request.user, "is_superuser", False)):
        return True
    legacy_user = get_legacy_user(request)
    return bool(legacy_user and is_legacy_admin(legacy_user))


def _admin_required_response(request):
    messages.error(request, "Eliminazione consentita solo agli amministratori.")
    return HttpResponseForbidden("Eliminazione consentita solo agli amministratori.")


def _audit(request, action: str, attrezzatura: Attrezzatura | None = None, payload: dict | None = None) -> None:
    detail = dict(payload or {})
    if attrezzatura is not None:
        detail.setdefault("attrezzatura_id", attrezzatura.id)
        detail.setdefault("codice", attrezzatura.codice)
        detail.setdefault("part_number", attrezzatura.part_number)
    log_action(request, action, "attrezzature", detail)


def _kickoff_preview_suggestions(embedded_context: dict | None) -> list[str]:
    if not embedded_context:
        return [
            "Inserisci un P/N per vedere lo stato attrezzature che comparirebbe nel KICK-OFF.",
        ]
    summary = embedded_context.get("summary") or {}
    suggestions = []
    if not summary.get("count"):
        suggestions.append("Nessuna attrezzatura collegata: valuta una bozza attrezzo o una task di verifica disponibilita.")
    elif not summary.get("available_count"):
        suggestions.append("Nessuna attrezzatura disponibile: apri una verifica disponibilita prima di avanzare il KICK-OFF.")
    if summary.get("late_count"):
        suggestions.append("Sono presenti attrezzature in ritardo: controlla consegna prevista e avanzamento.")
    if embedded_context.get("open_tasks"):
        suggestions.append("Ci sono task operative aperte: chiudile o aggiornale per tenere allineato il KICK-OFF.")
    if summary.get("ready_count"):
        suggestions.append("Almeno un'attrezzatura e pronta produzione: puoi usarla come riferimento nella scheda KICK-OFF.")
    if not suggestions:
        suggestions.append("Situazione allineata: attrezzature e task non mostrano criticita immediate per questo P/N.")
    return suggestions


def _existing_part_numbers(limit: int = 200) -> list[str]:
    values = set()
    for value in Attrezzatura.objects.exclude(part_number="").values_list("part_number", flat=True).distinct()[:limit]:
        normalized = kickoff_integration.normalize_part_number(value)
        if normalized:
            values.add(normalized)
    for value in AttrezzaturaPartNumber.objects.exclude(part_number="").values_list("part_number", flat=True).distinct()[:limit]:
        normalized = kickoff_integration.normalize_part_number(value)
        if normalized:
            values.add(normalized)
    return sorted(values)[:limit]


@login_required
def attrezzatura_list(request):
    qs = Attrezzatura.objects.all().annotate(task_count=Count("tasks"), kickoff_link_count=Count("kickoff_links", distinct=True))
    if request.GET.get("stato"):
        qs = qs.filter(stato=request.GET["stato"])
    if request.GET.get("disponibilita_stato"):
        qs = qs.filter(disponibilita_stato=request.GET["disponibilita_stato"])
    if request.GET.get("part_number"):
        qs = qs.filter(part_number__icontains=request.GET["part_number"].strip())
    if request.GET.get("codice"):
        qs = qs.filter(codice__icontains=request.GET["codice"].strip())
    if request.GET.get("in_ritardo"):
        qs = qs.filter(data_consegna_prevista__lt=timezone.localdate()).exclude(
            stato__in=[AttrezzaturaStato.FINITA, AttrezzaturaStato.ANNULLATA, AttrezzaturaStato.PRONTA_PRODUZIONE]
        )
    if request.GET.get("pronta_produzione"):
        qs = qs.filter(stato__in=[AttrezzaturaStato.PRONTA_PRODUZIONE, AttrezzaturaStato.READY_FOR_PRODUCTION])
    ready = request.GET.get("ready")
    if ready == "1":
        qs = qs.filter(stato__in=[AttrezzaturaStato.PRONTA_PRODUZIONE, AttrezzaturaStato.READY_FOR_PRODUCTION])
    elif ready == "0":
        qs = qs.exclude(stato__in=[AttrezzaturaStato.PRONTA_PRODUZIONE, AttrezzaturaStato.READY_FOR_PRODUCTION])
    linked = request.GET.get("linked_kickoff")
    if linked == "1":
        qs = qs.filter(kickoff_links__isnull=False).distinct()
    elif linked == "0":
        qs = qs.filter(kickoff_links__isnull=True)
    page = Paginator(qs.order_by("codice", "part_number", "id"), 50).get_page(request.GET.get("page"))
    return render(request, "attrezzature/pages/list.html", {**_base_context("list"), "page": page, "can_delete_attrezzature": _can_delete_attrezzature(request)})


@login_required
def attrezzatura_detail(request, pk: int):
    attrezzatura = get_object_or_404(
        Attrezzatura.objects.prefetch_related("part_numbers", "avanzamenti", "tasks", "note", "import_rows", "kickoff_links"),
        pk=pk,
    )
    return render(
        request,
        "attrezzature/pages/detail.html",
        {
            **_base_context("list"),
            "attrezzatura": attrezzatura,
            "progress_form": ProgressUpdateForm(),
            "block_form": AttrezzaturaBlockForm(),
            "can_delete_attrezzature": _can_delete_attrezzature(request),
        },
    )


@login_required
def attrezzatura_create(request):
    if request.method == "POST":
        form = AttrezzaturaForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.updated_by = request.user
            obj.save()
            _audit(request, "tooling_created", obj)
            messages.success(request, "Attrezzatura creata.")
            return redirect("attrezzature:detail", pk=obj.pk)
    else:
        form = AttrezzaturaForm()
    return render(request, "attrezzature/pages/form.html", {**_base_context("create"), "form": form, "mode": "create"})


@login_required
def attrezzatura_edit(request, pk: int):
    obj = get_object_or_404(Attrezzatura, pk=pk)
    if request.method == "POST":
        form = AttrezzaturaForm(request.POST, instance=obj)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.updated_by = request.user
            saved.save()
            _audit(request, "tooling_updated", saved)
            messages.success(request, "Attrezzatura aggiornata.")
            return redirect("attrezzature:detail", pk=obj.pk)
    else:
        form = AttrezzaturaForm(instance=obj)
    return render(request, "attrezzature/pages/form.html", {**_base_context("list"), "form": form, "attrezzatura": obj, "mode": "edit"})


@require_POST
@login_required
def attrezzatura_delete(request, pk: int):
    if not _can_delete_attrezzature(request):
        return _admin_required_response(request)
    obj = get_object_or_404(Attrezzatura, pk=pk)
    label = str(obj)
    _audit(request, "tooling_deleted", obj)
    obj.delete()
    messages.success(request, f"Attrezzatura eliminata: {label}.")
    return redirect("attrezzature:list")


@require_POST
@login_required
def attrezzatura_bulk_delete(request):
    if not _can_delete_attrezzature(request):
        return _admin_required_response(request)
    ids = [value for value in request.POST.getlist("selected_ids") if str(value).isdigit()]
    if not ids:
        messages.warning(request, "Seleziona almeno una attrezzatura da eliminare.")
        return redirect("attrezzature:list")
    qs = Attrezzatura.objects.filter(pk__in=ids)
    count = qs.count()
    for obj in qs:
        _audit(request, "tooling_deleted", obj, {"bulk": True})
    qs.delete()
    messages.success(request, f"Attrezzature eliminate: {count}.")
    return redirect("attrezzature:list")


@login_required
def import_page(request):
    return render(request, "attrezzature/pages/import.html", {**_base_context("import"), "form": ImportUploadForm()})


@login_required
def import_preview(request):
    if request.method != "POST":
        return redirect("attrezzature:import")
    form = ImportUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "File Excel non valido.")
        return redirect("attrezzature:import")
    upload = form.cleaned_data["file"]
    token = uuid.uuid4().hex
    suffix = os.path.splitext(upload.name)[1] or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(
        prefix=f"attrezzature_{token}_",
        suffix=suffix,
        delete=False,
    )
    try:
        tmp.write(upload.read())
        tmp.flush()
        saved_path = tmp.name
    finally:
        tmp.close()
    with open(saved_path, "rb") as fh:
        preview = excel_import.build_import_preview(fh, filename=upload.name, user=request.user)
    request.session["attrezzature_import_preview_path"] = saved_path
    request.session["attrezzature_import_preview_name"] = upload.name
    return render(request, "attrezzature/pages/import_preview.html", {**_base_context("import"), "preview": preview})


@require_POST
@login_required
def import_confirm(request):
    path = request.session.get("attrezzature_import_preview_path")
    name = request.session.get("attrezzature_import_preview_name") or "import_attrezzature.xlsx"
    if not path or not os.path.exists(path):
        messages.error(request, "Preview import non trovata. Carica di nuovo il file.")
        return redirect("attrezzature:import")
    with open(path, "rb") as fh:
        result = excel_import.confirm_import(fh, filename=name, user=request.user)
    try:
        os.unlink(path)
    except Exception:
        pass
    request.session.pop("attrezzature_import_preview_path", None)
    request.session.pop("attrezzature_import_preview_name", None)
    messages.success(request, f"Import confermato: {result['summary']['created']} create, {result['summary']['updated']} aggiornate.")
    return redirect("attrezzature:import")


@login_required
def task_list(request):
    qs = AttrezzaturaTask.objects.select_related("attrezzatura", "assegnato_a")
    for field in ["tipo", "stato", "priorita", "origine"]:
        if request.GET.get(field):
            qs = qs.filter(**{field: request.GET[field]})
    if request.GET.get("part_number"):
        qs = qs.filter(part_number__icontains=request.GET["part_number"].strip())
    if request.GET.get("scadute"):
        qs = qs.filter(scadenza__lt=timezone.localdate()).exclude(stato=AttrezzaturaTaskStato.COMPLETATA)
    page = Paginator(qs.order_by("scadenza", "-created_at"), 50).get_page(request.GET.get("page"))
    return render(request, "attrezzature/pages/task_list.html", {**_base_context("tasks"), "page": page})


@login_required
def task_detail(request, pk: int):
    task = get_object_or_404(AttrezzaturaTask.objects.select_related("attrezzatura", "assegnato_a", "completed_by"), pk=pk)
    return render(request, "attrezzature/pages/task_detail.html", {**_base_context("tasks"), "task": task, "complete_form": TaskCompleteForm(), "block_form": TaskBlockForm()})


@login_required
def task_create(request):
    if request.method == "POST":
        form = AttrezzaturaTaskForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            messages.success(request, "Task attrezzatura creato.")
            return redirect("attrezzature:task_detail", pk=obj.pk)
    else:
        form = AttrezzaturaTaskForm()
    return render(request, "attrezzature/pages/task_form.html", {**_base_context("tasks"), "form": form})


@require_POST
@login_required
def task_complete(request, pk: int):
    task = get_object_or_404(AttrezzaturaTask, pk=pk)
    form = TaskCompleteForm(request.POST)
    if form.is_valid():
        workflow.complete_task(task, user=request.user, note=form.cleaned_data.get("note", ""))
        messages.success(request, "Task completato.")
    return redirect("attrezzature:task_detail", pk=pk)


@require_POST
@login_required
def task_block(request, pk: int):
    task = get_object_or_404(AttrezzaturaTask, pk=pk)
    form = TaskBlockForm(request.POST)
    if form.is_valid():
        workflow.block_task(task, user=request.user, reason=form.cleaned_data["reason"])
        messages.success(request, "Task bloccato.")
    return redirect("attrezzature:task_detail", pk=pk)


@require_POST
@login_required
def update_progress(request, pk: int):
    attrezzatura = get_object_or_404(Attrezzatura, pk=pk)
    form = ProgressUpdateForm(request.POST)
    if form.is_valid():
        workflow.update_attrezzatura_progress(
            attrezzatura,
            percentuale=form.cleaned_data.get("avanzamento_percentuale"),
            stato=form.cleaned_data.get("stato") or None,
            user=request.user,
            note=form.cleaned_data.get("note", ""),
            origine="manuale",
        )
        _audit(
            request,
            "tooling_progress_updated",
            attrezzatura,
            {
                "stato": form.cleaned_data.get("stato") or attrezzatura.stato,
                "avanzamento_percentuale": form.cleaned_data.get("avanzamento_percentuale"),
            },
        )
        messages.success(request, "Avanzamento aggiornato.")
    return redirect("attrezzature:detail", pk=pk)


@require_POST
@login_required
def attrezzatura_action(request, pk: int):
    attrezzatura = get_object_or_404(Attrezzatura, pk=pk)
    action = (request.POST.get("action") or "").strip()
    note = request.POST.get("note", "")
    if action == "start_availability_check":
        workflow.mark_availability_check_started(attrezzatura, user=request.user, note=note)
        _audit(request, "tooling_availability_check_started", attrezzatura)
        messages.success(request, "Verifica disponibilita avviata.")
    elif action == "mark_available":
        workflow.mark_available(attrezzatura, user=request.user, note=note)
        _audit(request, "tooling_marked_available", attrezzatura)
        messages.success(request, "Attrezzatura segnata disponibile.")
    elif action == "mark_to_create":
        workflow.mark_to_create(attrezzatura, user=request.user, note=note)
        _audit(request, "tooling_marked_to_create", attrezzatura)
        messages.success(request, "Attrezzatura segnata da creare.")
    elif action == "mark_blocked":
        form = AttrezzaturaBlockForm(request.POST)
        if form.is_valid():
            workflow.mark_blocked(attrezzatura, user=request.user, reason=form.cleaned_data["reason"])
            _audit(request, "tooling_blocked", attrezzatura, {"reason": form.cleaned_data["reason"]})
            messages.success(request, "Attrezzatura bloccata.")
        else:
            messages.error(request, "Indica il motivo del blocco.")
    elif action == "close":
        workflow.close_attrezzatura(attrezzatura, user=request.user, note=note)
        _audit(request, "tooling_closed", attrezzatura)
        messages.success(request, "Attrezzatura chiusa.")
    elif action == "archive":
        workflow.archive_attrezzatura(attrezzatura, user=request.user, note=note)
        _audit(request, "tooling_archived", attrezzatura)
        messages.success(request, "Attrezzatura archiviata.")
    else:
        messages.error(request, "Azione attrezzatura non riconosciuta.")
    return redirect("attrezzature:detail", pk=pk)


@require_POST
@login_required
def confirm_ready(request, pk: int):
    attrezzatura = get_object_or_404(Attrezzatura, pk=pk)
    workflow.confirm_ready_for_production(attrezzatura, user=request.user, note=request.POST.get("note", ""))
    _audit(request, "tooling_ready_for_production", attrezzatura)
    messages.success(request, "Attrezzatura confermata pronta per produzione.")
    return redirect("attrezzature:detail", pk=pk)


@login_required
def embedded_preview(request):
    form = EmbeddedPreviewForm(request.GET or None)
    part_number = request.GET.get("part_number", "")
    embedded_context = kickoff_integration.build_kickoff_attrezzatura_context(part_number) if part_number else None
    suggestions = _kickoff_preview_suggestions(embedded_context)
    part_numbers = _existing_part_numbers()
    return render(
        request,
        "attrezzature/pages/embedded_preview.html",
        {
            **_base_context("embedded"),
            "form": form,
            "embedded_context": embedded_context,
            "suggestions": suggestions,
            "part_numbers": part_numbers,
        },
    )
