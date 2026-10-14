"""Attivita' nate dagli incontri e legami fra attivita', azioni e problemi.

Prima tre punti diversi creavano un'attivita' da un incontro (conduzione,
dettaglio/esito, next steps della minuta), ognuno con regole sue: uno
controllava il blocco VRF e gli altri no, uno tagliava il titolo a 220
caratteri su un campo da 200 (errore 500 su SQL Server), uno non lo tagliava
affatto. Qui le regole stanno in un posto solo.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from ..models import (
    MeetingActionItem,
    MeetingActionStatus,
    MeetingIssue,
    MeetingIssueStatus,
    Task,
    TaskImpostazioni,
    TaskPriority,
    TaskStatus,
)
from .notify import notify_user

logger = logging.getLogger(__name__)

TASK_TITLE_MAX = Task._meta.get_field("title").max_length


class KickoffBloccatoVRF(Exception):
    """Il kickoff e' bloccato per VRF mancante: niente attivita' nuove."""


def titolo_attivita(value: str) -> str:
    return (value or "").strip()[:TASK_TITLE_MAX]


def meeting_task_marker(meeting) -> str:
    """Firma dell'incontro nella descrizione dell'attivita'.

    Con la parentesi: «#1 (» non e' contenuto in «#12 (», quindi l'antidoppione
    dei next steps non confonde piu' l'incontro 1 con il 12.
    """
    return f"Dall'incontro #{meeting.numero} ("


def kickoff_bloccato_vrf(project) -> bool:
    from ..views._shared import _vrf_status_detail

    return bool(_vrf_status_detail(project, TaskImpostazioni.get_singleton())["is_blocked"])


def crea_attivita_da_incontro(
    *,
    project,
    meeting,
    user,
    title: str,
    assigned_to=None,
    start_date=None,
    due_date=None,
    priority: str = TaskPriority.MEDIUM,
    category=None,
    nota: str = "",
    notifica: bool = True,
) -> Task:
    """Crea un'attivita' del kickoff a partire da un incontro.

    Solleva ``KickoffBloccatoVRF`` se il kickoff e' bloccato e ``ValueError``
    se manca il titolo. Avvisa l'assegnatario (se non e' chi crea).
    """
    title = titolo_attivita(title)
    if not title:
        raise ValueError("title_required")
    if kickoff_bloccato_vrf(project):
        raise KickoffBloccatoVRF()
    if priority not in TaskPriority.values:
        priority = TaskPriority.MEDIUM

    data = meeting.data
    data_label = data.strftime("%d-%m-%Y") if hasattr(data, "strftime") else str(data or "")
    descrizione = f"{meeting_task_marker(meeting)}{data_label})"
    nota = (nota or "").strip()
    if nota:
        descrizione = f"{descrizione}\n\n{nota}"

    task = Task.objects.create(
        title=title,
        project=project,
        assigned_to=assigned_to,
        category=category,
        next_step_due=start_date,
        due_date=due_date,
        priority=priority,
        status=TaskStatus.TODO,
        created_by=user,
        description=descrizione,
    )
    if notifica:
        notify_task_assignment(task, actor=user)
    return task


def _user_pk(user):
    return getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None


def notify_task_assignment(task: Task, *, actor=None) -> None:
    """Avvisa chi riceve un'attivita'. Chi si assegna da solo non viene avvisato."""
    assignee = task.assigned_to
    if assignee is None or assignee.pk == _user_pk(actor):
        return
    progetto = f" [{task.project.name}]" if task.project_id else ""
    scadenza = f", entro il {task.due_date:%d/%m/%Y}" if task.due_date else ""
    try:
        notify_user(
            assignee,
            f"Ti è stata assegnata l'attività «{task.title}»{progetto}{scadenza}.",
            reverse("tasks:detail", kwargs={"task_id": task.pk}),
        )
    except Exception:
        logger.exception("Notifica assegnazione attivita' fallita (task=%s)", task.pk)


def notify_meeting_item_assignment(item, *, actor=None) -> None:
    """Avvisa il responsabile di un'azione o di un problema nato in un incontro.

    Prima chi riceveva un'azione lo scopriva solo dal sollecito del lunedi', e
    soltanto a scadenza gia' passata.
    """
    assignee = getattr(item, "assigned_to", None)
    if assignee is None or assignee.pk == _user_pk(actor):
        return
    from ..minute_email import meeting_url

    tipo = "del problema" if isinstance(item, MeetingIssue) else "dell'azione"
    scadenza = f", entro il {item.due_date:%d/%m/%Y}" if item.due_date else ""
    meeting = getattr(item, "source_meeting", None)
    try:
        url = meeting_url(meeting) if meeting is not None else reverse(
            "tasks:project_actions", kwargs={"project_id": item.project_id}
        )
    except Exception:
        url = ""
    try:
        notify_user(
            assignee,
            f"Sei responsabile {tipo} «{item.title}» [{item.project.name}]{scadenza}.",
            url,
            tipo="generico",
        )
    except Exception:
        logger.exception("Notifica responsabile voce incontro fallita (%s=%s)", type(item).__name__, item.pk)


def chiudi_voci_collegate(task: Task) -> int:
    """Attivita' completata: chiude le azioni e i problemi che vi puntano.

    Senza questo legame un'azione «fatta» attraverso la sua attivita' restava
    aperta e tornava nell'ordine del giorno dell'incontro successivo.
    Idempotente: tocca solo le voci ancora aperte.
    """
    if task.pk is None or task.status != TaskStatus.DONE:
        return 0
    now = timezone.now()
    closed = 0
    with transaction.atomic():
        for action in MeetingActionItem.objects.filter(linked_task=task, status=MeetingActionStatus.OPEN):
            action.status = MeetingActionStatus.DONE
            action.done_at = now
            action.done_by = task.assigned_to
            action.save(update_fields=["status", "done_at", "done_by", "updated_at"])
            closed += 1
        for issue in MeetingIssue.objects.filter(linked_task=task, status=MeetingIssueStatus.OPEN):
            issue.status = MeetingIssueStatus.RESOLVED
            issue.resolved_at = now
            issue.resolved_by = task.assigned_to
            issue.resolution_note = f"Risolto con il completamento dell'attività «{task.title}»."
            issue.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_note", "updated_at"])
            closed += 1
    return closed
