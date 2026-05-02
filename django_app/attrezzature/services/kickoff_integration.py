from __future__ import annotations

from django.db.models import Q

from attrezzature.models import (
    Attrezzatura,
    AttrezzaturaKickoffLink,
    AttrezzaturaKickoffRelationType,
    AttrezzaturaPartNumber,
    AttrezzaturaStato,
    AttrezzaturaTask,
    AttrezzaturaTaskOrigine,
    AttrezzaturaTaskStato,
    AttrezzaturaTaskTipo,
    DisponibilitaStato,
)
from attrezzature.services import workflow


def normalize_part_number(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def upsert_kickoff_link(
    *,
    attrezzatura,
    kickoff_ref=None,
    kickoff_activity_ref=None,
    attrezzatura_task=None,
    relationship_type=AttrezzaturaKickoffRelationType.LINKED_EXISTING,
    user=None,
    notes="",
):
    project_id = _int_or_none(kickoff_ref)
    task_id = _int_or_none(kickoff_activity_ref)
    if attrezzatura is None or (project_id is None and task_id is None):
        return None
    lookup = {
        "attrezzatura": attrezzatura,
        "task_id": task_id,
        "relationship_type": relationship_type,
    }
    defaults = {
        "project_id": project_id,
        "attrezzatura_task": attrezzatura_task,
        "part_number_snapshot": normalize_part_number(attrezzatura.part_number),
        "notes": notes or "",
        "created_by": user,
    }
    link, created = AttrezzaturaKickoffLink.objects.get_or_create(**lookup, defaults=defaults)
    updates = []
    for field, value in defaults.items():
        if field == "created_by" and not created:
            continue
        if getattr(link, field) != value:
            setattr(link, field, value)
            updates.append(field)
    if updates:
        link.save(update_fields=[*updates, "updated_at"])
    return link


def get_attrezzature_for_part_number(part_number: str):
    pn = normalize_part_number(part_number)
    if not pn:
        return Attrezzatura.objects.none()
    return (
        Attrezzatura.objects.filter(
            Q(part_number__iexact=pn) | Q(part_numbers__part_number__iexact=pn)
        )
        .distinct()
        .order_by("codice", "id")
    )


def get_attrezzature_summary_for_part_number(part_number: str) -> dict:
    tools = list(get_attrezzature_for_part_number(part_number))
    return {
        "part_number": normalize_part_number(part_number),
        "count": len(tools),
        "available_count": sum(1 for item in tools if item.disponibilita_stato == DisponibilitaStato.DISPONIBILE),
        "ready_count": sum(1 for item in tools if item.is_pronta_produzione),
        "late_count": sum(1 for item in tools if item.is_in_ritardo),
        "tools": tools,
    }


def build_kickoff_attrezzatura_context(part_number: str, kickoff_ref=None, kickoff_activity_ref=None) -> dict:
    pn = normalize_part_number(part_number)
    tools = list(get_attrezzature_for_part_number(pn))
    link_q = Q()
    if kickoff_ref:
        link_q |= Q(project_id=_int_or_none(kickoff_ref))
    if kickoff_activity_ref:
        link_q |= Q(task_id=_int_or_none(kickoff_activity_ref))
    links = []
    if link_q:
        links = list(
            AttrezzaturaKickoffLink.objects.filter(link_q)
            .select_related("attrezzatura", "project", "task", "attrezzatura_task")
            .order_by("-updated_at", "-id")
        )
        linked_tools = [link.attrezzatura for link in links if link.attrezzatura_id]
        existing_ids = {tool.id for tool in tools}
        tools.extend(tool for tool in linked_tools if tool.id not in existing_ids)
    task_q = Q(part_number__iexact=pn)
    if kickoff_ref:
        task_q |= Q(external_kickoff_id=str(kickoff_ref))
    if kickoff_activity_ref:
        task_q |= Q(external_kickoff_activity_id=str(kickoff_activity_ref))
    tasks = list(AttrezzaturaTask.objects.filter(task_q).select_related("attrezzatura", "assegnato_a").order_by("scadenza", "-created_at").distinct())
    return {
        "part_number": pn,
        "kickoff_ref": str(kickoff_ref or ""),
        "kickoff_activity_ref": str(kickoff_activity_ref or ""),
        "attrezzature": tools,
        "links": links,
        "tasks": tasks,
        "open_tasks": [task for task in tasks if task.is_open],
        "summary": get_attrezzature_summary_for_part_number(pn),
        "can_create_draft": True,
        "can_link_existing": True,
        "can_update_progress": True,
        "can_manage_tasks": True,
        "source_of_truth": "attrezzature",
    }


def get_or_create_attrezzatura_task_for_kickoff_activity(
    *,
    tipo,
    part_number,
    attrezzatura=None,
    titolo="",
    descrizione="",
    kickoff_ref=None,
    kickoff_activity_ref=None,
    user=None,
):
    pn = normalize_part_number(part_number or getattr(attrezzatura, "part_number", ""))
    qs = AttrezzaturaTask.objects.filter(
        tipo=tipo,
        external_kickoff_activity_id=str(kickoff_activity_ref or ""),
    )
    if not kickoff_activity_ref:
        qs = AttrezzaturaTask.objects.none()
    existing = qs.first()
    if existing:
        return existing, False
    task = AttrezzaturaTask.objects.create(
        attrezzatura=attrezzatura,
        part_number=pn,
        codice_attrezzo=getattr(attrezzatura, "codice", "") or "",
        tipo=tipo,
        titolo=titolo or dict(AttrezzaturaTaskTipo.choices).get(tipo, "Attivita attrezzatura"),
        descrizione=descrizione or "",
        origine=AttrezzaturaTaskOrigine.KICKOFF,
        external_kickoff_id=str(kickoff_ref or ""),
        external_kickoff_activity_id=str(kickoff_activity_ref or ""),
        created_by=user,
    )
    if attrezzatura is not None:
        upsert_kickoff_link(
            attrezzatura=attrezzatura,
            kickoff_ref=kickoff_ref,
            kickoff_activity_ref=kickoff_activity_ref,
            attrezzatura_task=task,
            relationship_type=AttrezzaturaKickoffRelationType.VERIFICATION_REQUIRED,
            user=user,
        )
    return task, True


def link_attrezzatura_to_kickoff_activity(attrezzatura, kickoff_ref=None, kickoff_activity_ref=None, task=None):
    if task is None:
        task = AttrezzaturaTask.objects.filter(external_kickoff_activity_id=str(kickoff_activity_ref or "")).first()
    if task is not None:
        task.attrezzatura = attrezzatura
        task.part_number = attrezzatura.part_number or task.part_number
        task.codice_attrezzo = attrezzatura.codice or task.codice_attrezzo
        if kickoff_ref is not None:
            task.external_kickoff_id = str(kickoff_ref)
        if kickoff_activity_ref is not None:
            task.external_kickoff_activity_id = str(kickoff_activity_ref)
        task.save(update_fields=["attrezzatura", "part_number", "codice_attrezzo", "external_kickoff_id", "external_kickoff_activity_id", "updated_at"])
    upsert_kickoff_link(
        attrezzatura=attrezzatura,
        kickoff_ref=kickoff_ref,
        kickoff_activity_ref=kickoff_activity_ref,
        attrezzatura_task=task,
        relationship_type=AttrezzaturaKickoffRelationType.LINKED_EXISTING,
    )
    return task


def create_draft_attrezzatura_from_kickoff(*, part_number, description="", codice="", kickoff_ref=None, kickoff_activity_ref=None, user=None):
    pn = normalize_part_number(part_number)
    tool = Attrezzatura.objects.create(
        codice=str(codice or "").strip(),
        descrizione=description or "",
        part_number=pn,
        stato=AttrezzaturaStato.TO_CREATE if not codice else AttrezzaturaStato.REQUESTED,
        disponibilita_stato=DisponibilitaStato.DA_CREARE if not codice else DisponibilitaStato.DA_VERIFICARE,
        origine_import="kickoff",
        created_by=user,
        updated_by=user,
    )
    if pn:
        AttrezzaturaPartNumber.objects.get_or_create(attrezzatura=tool, part_number=pn, defaults={"fonte": "kickoff"})
    gestione_task = workflow.create_new_tool_task(
        pn,
        description=description,
        codice_attrezzo=codice,
        kickoff_ref=kickoff_ref,
        kickoff_activity_ref=kickoff_activity_ref,
        user=user,
    )
    link_attrezzatura_to_kickoff_activity(
        tool,
        kickoff_ref=kickoff_ref,
        kickoff_activity_ref=kickoff_activity_ref,
        task=gestione_task,
    )
    upsert_kickoff_link(
        attrezzatura=tool,
        kickoff_ref=kickoff_ref,
        kickoff_activity_ref=kickoff_activity_ref,
        attrezzatura_task=gestione_task,
        relationship_type=AttrezzaturaKickoffRelationType.CREATED_FROM_KICKOFF,
        user=user,
        notes=description,
    )
    return tool


def update_attrezzatura_progress_from_kickoff(attrezzatura, percentuale=None, stato=None, user=None, note="", kickoff_ref=None, kickoff_activity_ref=None):
    result = workflow.update_attrezzatura_progress(attrezzatura, percentuale=percentuale, stato=stato, user=user, note=note, origine="kickoff")
    if kickoff_activity_ref:
        get_or_create_attrezzatura_task_for_kickoff_activity(
            tipo=AttrezzaturaTaskTipo.AGGIORNA_AVANZAMENTO,
            part_number=result.part_number,
            attrezzatura=result,
            titolo=f"Aggiornare avanzamento attrezzatura {result.codice or result.part_number}",
            kickoff_ref=kickoff_ref,
            kickoff_activity_ref=kickoff_activity_ref,
            user=user,
        )
        upsert_kickoff_link(
            attrezzatura=result,
            kickoff_ref=kickoff_ref,
            kickoff_activity_ref=kickoff_activity_ref,
            relationship_type=AttrezzaturaKickoffRelationType.LINKED_EXISTING,
            user=user,
            notes=note,
        )
    return result


def confirm_attrezzatura_ready_from_kickoff(attrezzatura, user=None, note="", kickoff_ref=None, kickoff_activity_ref=None):
    result = workflow.confirm_ready_for_production(attrezzatura, user=user, note=note)
    if kickoff_activity_ref:
        task, _ = get_or_create_attrezzatura_task_for_kickoff_activity(
            tipo=AttrezzaturaTaskTipo.CONFERMA_PRONTA_PRODUZIONE,
            part_number=result.part_number,
            attrezzatura=result,
            titolo=f"Confermare pronta produzione {result.codice or result.part_number}",
            kickoff_ref=kickoff_ref,
            kickoff_activity_ref=kickoff_activity_ref,
            user=user,
        )
        if task.stato != AttrezzaturaTaskStato.COMPLETATA:
            workflow.complete_task(task, user=user, note=note)
        upsert_kickoff_link(
            attrezzatura=result,
            kickoff_ref=kickoff_ref,
            kickoff_activity_ref=kickoff_activity_ref,
            attrezzatura_task=task,
            relationship_type=AttrezzaturaKickoffRelationType.LINKED_EXISTING,
            user=user,
            notes=note,
        )
    return result


def block_attrezzatura_task_from_kickoff(task, user=None, reason=""):
    return workflow.block_task(task, user=user, reason=reason)


def complete_attrezzatura_task_from_kickoff(task, user=None, note=""):
    return workflow.complete_task(task, user=user, note=note)
