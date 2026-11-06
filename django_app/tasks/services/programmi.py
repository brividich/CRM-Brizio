"""L'attività di programmazione e il programma che deve produrre sono la stessa cosa."""
from __future__ import annotations

from django.db.models import Q

from ..models import ProjectTechRef, Task, TaskStatus, TechRefKind, TechRefStatus
from .fai import allinea_da_riga


def senza_attivita_aperta(righe):
    """Finché l'attività è aperta la voce è lei: la riga non va contata una seconda volta."""
    return righe.filter(Q(task__isnull=True) | Q(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED]))


def sgancia(ref: ProjectTechRef) -> None:
    """Una riga vuota sparisce con l'attività; un programma già inserito resta."""
    if ref.ha_contenuto:
        ref.task = None
        ref.save(update_fields=["task", "updated_at"])
    else:
        ref.delete()


def _riga_libera(task: Task, kind: str) -> ProjectTechRef | None:
    """Una riga assegnata in riunione diventa quella dell'attività, senza doppioni."""
    return (
        ProjectTechRef.objects.filter(
            Q(assigned_to__isnull=True) | Q(assigned_to_id=task.assigned_to_id),
            project_id=task.project_id, kind=kind, task__isnull=True, status=TechRefStatus.OPEN,
        )
        .order_by("id")
        .first()
    )


def allinea_da_attivita(task: Task) -> ProjectTechRef | None:
    ref = ProjectTechRef.objects.filter(task=task).first()
    categoria = task.category if task.category_id else None
    kind = categoria.richiede if categoria and task.project_id and task.status != TaskStatus.CANCELED else ""
    if ref is not None and ref.kind != kind:
        sgancia(ref)
        ref = None
    if not kind:
        return None
    if ref is None:
        ref = _riga_libera(task, kind) or ProjectTechRef(
            project_id=task.project_id, kind=kind, created_by=task.created_by
        )
    ref.task = task
    ref.project_id = task.project_id
    ref.assigned_to_id = task.assigned_to_id
    ref.due_date = task.due_date
    # Il FAI con la sua scheda ha un avanzamento proprio.
    if not (kind == TechRefKind.FAI and getattr(ref, "fai_record", None)):
        if task.status == TaskStatus.DONE:
            if ref.is_open and ref.ha_contenuto:
                ref.mark_done()
        elif not ref.is_open:
            ref.reopen()
    ref.save()
    allinea_da_riga(ref)
    return ref


def chiudi_se_pronta(ref: ProjectTechRef, user=None) -> None:
    """Attività già chiusa e programma inserito dopo: ora la riga è a posto."""
    if ref.task_id and ref.is_open and ref.task.status == TaskStatus.DONE and ref.ha_contenuto:
        ref.mark_done(user=user)
        ref.save(update_fields=["status", "done_by", "done_at", "updated_at"])
