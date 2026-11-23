"""Integrazione attrezzature nelle attivita' KICK-OFF."""
from __future__ import annotations

import logging

from django.utils.text import slugify

from attrezzature.models import (
    AttrezzaturaTaskTipo as GestioneAttrezzaturaTaskTipo,
)
from attrezzature.services import kickoff_integration as attrezzature_kickoff

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
