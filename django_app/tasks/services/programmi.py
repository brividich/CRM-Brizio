"""L'attività di programmazione e il programma che deve produrre sono la stessa cosa."""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from ..models import ProjectTechRef, Task, TaskCategory, TaskPriority, TaskStatus, TechRefKind, TechRefStatus
from .fai import allinea_da_riga


def senza_attivita_aperta(righe):
    """Finché l'attività è aperta la voce è lei: la riga non va contata una seconda volta."""
    return righe.filter(Q(task__isnull=True) | Q(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED]))


def sgancia(ref: ProjectTechRef) -> None:
    """Una riga vuota sparisce con l'attività; restano il programma inserito e l'assegnazione in riunione."""
    if ref.ha_contenuto or ref.source_meeting_id:
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
    if ref is not None and ref.project_id != task.project_id and kind:
        # Attività spostata: il programma la segue, la scheda FAI appartiene all'articolo di prima.
        if getattr(ref, "fai_record", None):
            sgancia(ref)
            ref = None
        else:
            ref.source_meeting = None
    if ref is not None and ref.kind != kind:
        sgancia(ref)
        ref = None
    if not kind:
        return None
    if ref is None:
        # La riga che ha chiesto l'attività (vedi ``attivita_per_riga``) viene prima di ogni altra libera.
        ref = getattr(task, "_riga_programma", None) or _riga_libera(task, kind) or ProjectTechRef(
            project_id=task.project_id, kind=kind, created_by=task.created_by
        )
    ref.task = task
    ref.project_id = task.project_id
    ref.assigned_to_id = task.assigned_to_id
    # Senza data sull'attività resta quella data in riunione.
    ref.due_date = task.due_date or ref.due_date
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


def allinea_stato_riga(ref: ProjectTechRef, user=None) -> None:
    """Attività già chiusa: la riga è a posto solo finché il programma c'è."""
    if not ref.task_id or ref.task.status != TaskStatus.DONE or getattr(ref, "fai_record", None):
        return
    if ref.is_open and ref.ha_contenuto:
        ref.mark_done(user=user)
    elif not ref.is_open and not ref.ha_contenuto:
        ref.reopen()
    else:
        return
    ref.save(update_fields=["status", "done_by", "done_at", "updated_at"])


def tipo_per(kind: str) -> TaskCategory | None:
    """Il tipo di attività che produce questo programma (Impostazioni → Tipi, «Richiede»)."""
    return TaskCategory.objects.filter(is_active=True, richiede=kind).order_by("order_index", "id").first()


def attivita_per_riga(ref: ProjectTechRef, user=None, *, notifica: bool = True) -> Task | None:
    """Riga assegnata in «Programmi e FAI»: diventa un'attività del kickoff.

    Prima la riga restava una voce a parte: niente Gantt, niente «In corso», niente
    mail a chi la riceveva. Ora nasce l'attività del tipo che «richiede» quel
    programma, con stesso responsabile e stessa data; la riga si chiude con lei.
    Non crea nulla se la riga non ha responsabile, è già chiusa o collegata, se
    nessun tipo attivo la richiede o se il kickoff è bloccato per VRF.
    """
    from .meeting_tasks import kickoff_bloccato_vrf, meeting_task_marker, notify_task_assignment, titolo_attivita

    if ref.task_id or not ref.assigned_to_id or not ref.is_open or not ref.project_id:
        return None
    tipo = tipo_per(ref.kind)
    if tipo is None or kickoff_bloccato_vrf(ref.project):
        return None
    autore = user if getattr(user, "is_authenticated", False) else (ref.created_by or ref.project.created_by)
    if autore is None:
        return None
    oggi = timezone.localdate()
    inizio = min(oggi, ref.due_date) if ref.due_date else oggi
    meeting = ref.source_meeting
    if meeting is not None:
        data = f"{meeting.data:%d-%m-%Y}" if hasattr(meeting.data, "strftime") else str(meeting.data or "")
        descrizione = f"{meeting_task_marker(meeting)}{data}). Riga di «Programmi e FAI»."
    else:
        descrizione = "Dalla scheda «Programmi e FAI» della commessa."
    task = Task(
        title=titolo_attivita(f"{tipo.name} {ref.code}".strip()),
        project_id=ref.project_id,
        assigned_to_id=ref.assigned_to_id,
        category=tipo,
        next_step_due=inizio,
        due_date=ref.due_date,
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
        created_by=autore,
        description=descrizione,
    )
    task._riga_programma = ref
    task.save()
    ref.refresh_from_db()
    if notifica:
        notify_task_assignment(task, actor=user)
    return task
