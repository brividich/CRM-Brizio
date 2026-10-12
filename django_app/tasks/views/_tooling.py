"""Integrazione attrezzature nelle attivita' KICK-OFF."""
from __future__ import annotations

import logging

from django.contrib import messages
from django.urls import reverse
from django.utils.text import slugify

from core.audit import log_action
from attrezzature.models import (
    AttrezzaturaStato,
    AttrezzaturaTaskStato as GestioneAttrezzaturaTaskStato,
    AttrezzaturaTaskTipo as GestioneAttrezzaturaTaskTipo,
    DisponibilitaStato,
)
from attrezzature.services import kickoff_integration as attrezzature_kickoff

from ..forms import (
    TaskForm,
)
from ..models import (
    Task,
)

logger = logging.getLogger(__name__)
ATTREZZATURA_KICKOFF_TASK_TYPES = {
    "creazione_attrezzo": GestioneAttrezzaturaTaskTipo.CREAZIONE_ATTREZZO,
    "verifica_disponibilita": GestioneAttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
    "aggiorna_avanzamento": GestioneAttrezzaturaTaskTipo.AGGIORNA_AVANZAMENTO,
    "controllo_ritardo": GestioneAttrezzaturaTaskTipo.CONTROLLO_RITARDO,
    "conferma_pronta_produzione": GestioneAttrezzaturaTaskTipo.CONFERMA_PRONTA_PRODUZIONE,
}


def _task_attrezzatura_part_number(task: Task) -> str:
    if task.project_id and task.project.part_number:
        return attrezzature_kickoff.normalize_part_number(task.project.part_number)
    data = task.extra_data or {}
    for key in ("part_number", "pn", "p_n", "particolare"):
        if data.get(key):
            return attrezzature_kickoff.normalize_part_number(data.get(key))
    return ""


def _task_attrezzatura_tipo(task: Task) -> str:
    data = task.extra_data or {}
    explicit = str(data.get("attrezzatura_task_type") or data.get("tipo_attrezzatura") or "").strip().lower()
    if explicit in ATTREZZATURA_KICKOFF_TASK_TYPES:
        return ATTREZZATURA_KICKOFF_TASK_TYPES[explicit]
    category = getattr(task, "category", None)
    if category is None:
        return ""
    for candidate in (category.slug, category.name):
        normalized = slugify(str(candidate or "").strip()).replace("-", "_")
        if normalized in ATTREZZATURA_KICKOFF_TASK_TYPES:
            return ATTREZZATURA_KICKOFF_TASK_TYPES[normalized]
    return ""


def _ensure_attrezzatura_task_link_for_kickoff_task(task: Task, user=None):
    part_number = _task_attrezzatura_part_number(task)
    tipo = _task_attrezzatura_tipo(task)
    if not part_number or not tipo:
        return None
    title = f"{task.title} - Gestione Attrezzatura"
    linked, _created = attrezzature_kickoff.get_or_create_attrezzatura_task_for_kickoff_activity(
        tipo=tipo,
        part_number=part_number,
        titolo=title,
        descrizione=task.description,
        kickoff_ref=task.project_id,
        kickoff_activity_ref=task.id,
        user=user,
    )
    return linked


def _handle_task_tooling_form_action(request, task: Task, form: TaskForm) -> None:
    _apply_task_tooling_action(
        request,
        task,
        mode=form.cleaned_data.get("tooling_mode") or TaskForm.TOOLING_NONE,
        existing_attrezzatura=form.cleaned_data.get("tooling_existing_attrezzatura"),
        part_number=form.cleaned_data.get("tooling_part_number"),
        code=form.cleaned_data.get("tooling_code"),
        description=form.cleaned_data.get("tooling_description"),
    )


def _apply_task_tooling_action(
    request,
    task: Task,
    *,
    mode: str,
    existing_attrezzatura=None,
    part_number: str = "",
    code: str = "",
    description: str = "",
) -> None:
    """Azione attrezzatura su un'attivita': collega, richiedi, verifica.

    Estratto da `_handle_task_tooling_form_action` perche' lo stesso gesto
    serve anche fuori dal form completo, dal mini-form dell'incontro: la
    logica di dominio e' una sola e non va riscritta due volte.
    """
    mode = mode or TaskForm.TOOLING_NONE
    if mode == TaskForm.TOOLING_NONE:
        return
    part_number = attrezzature_kickoff.normalize_part_number(
        part_number
        or (task.project.part_number if task.project_id else "")
        or _task_attrezzatura_part_number(task)
    )
    if mode == TaskForm.TOOLING_LINK_EXISTING:
        tool = existing_attrezzatura
        if not tool:
            return
        linked, _created = attrezzature_kickoff.get_or_create_attrezzatura_task_for_kickoff_activity(
            tipo=GestioneAttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
            part_number=part_number or tool.part_number,
            attrezzatura=tool,
            titolo=f"Gestire attrezzatura per {task.title}",
            descrizione=task.description,
            kickoff_ref=task.project_id,
            kickoff_activity_ref=task.id,
            user=request.user,
        )
        attrezzature_kickoff.link_attrezzatura_to_kickoff_activity(
            tool,
            kickoff_ref=task.project_id,
            kickoff_activity_ref=task.id,
            task=linked,
        )
        log_action(request, "tooling_linked_from_task_form", "tasks", {"task_id": task.id, "attrezzatura_id": tool.id})
        messages.success(request, f"Attrezzatura {tool.codice or tool.pk} collegata all'attivita.")
    elif mode == TaskForm.TOOLING_REQUEST_NEW:
        tool = attrezzature_kickoff.create_draft_attrezzatura_from_kickoff(
            part_number=part_number,
            description=description or task.description,
            codice=code or "",
            kickoff_ref=task.project_id,
            kickoff_activity_ref=task.id,
            user=request.user,
        )
        log_action(request, "tooling_requested_from_task_form", "tasks", {"task_id": task.id, "attrezzatura_id": tool.id})
        messages.success(request, f"Richiesta attrezzatura creata per P/N {tool.part_number}.")
    elif mode == TaskForm.TOOLING_VERIFICATION_REQUIRED:
        linked, created = attrezzature_kickoff.get_or_create_attrezzatura_task_for_kickoff_activity(
            tipo=GestioneAttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
            part_number=part_number,
            titolo=f"Verificare disponibilita attrezzatura per {task.title}",
            descrizione=description or task.description,
            kickoff_ref=task.project_id,
            kickoff_activity_ref=task.id,
            user=request.user,
        )
        log_action(request, "tooling_verification_requested_from_task_form", "tasks", {"task_id": task.id, "attrezzatura_task_id": linked.id})
        messages.success(request, "Verifica disponibilita attrezzatura creata." if created else "Verifica disponibilita gia collegata.")


def _build_task_attrezzatura_context(task: Task) -> dict | None:
    part_number = _task_attrezzatura_part_number(task)
    if not part_number:
        return None
    context = attrezzature_kickoff.build_kickoff_attrezzatura_context(
        part_number,
        kickoff_ref=task.project_id,
        kickoff_activity_ref=task.id,
    )
    context.update(
        {
            "action_url": reverse("tasks:attrezzature_action", kwargs={"task_id": task.id}),
            "source_task": task,
            "stato_choices": AttrezzaturaStato.choices,
            "disponibilita_choices": DisponibilitaStato.choices,
            "task_status_choices": GestioneAttrezzaturaTaskStato.choices,
        }
    )
    return context
