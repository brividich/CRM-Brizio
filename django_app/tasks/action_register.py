"""Registro azioni unificato per una commessa KICK-OFF."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging

from django.urls import reverse
from django.utils import timezone

from .models import MeetingIssueStatus, SubTask, TaskStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionRow:
    origin: str
    obj_id: int
    title: str
    owner_label: str
    due_date: date | None
    is_open: bool
    is_overdue: bool
    source_label: str
    url: str


def _owner_label(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.get_username()).strip()


def _collect_issues(project, *, include_closed: bool) -> list[ActionRow]:
    queryset = project.meeting_issues.select_related("assigned_to", "source_meeting")
    if not include_closed:
        queryset = queryset.filter(status=MeetingIssueStatus.OPEN)

    today = timezone.localdate()
    rows = []
    for issue in queryset:
        is_open = issue.status == MeetingIssueStatus.OPEN
        if issue.source_meeting is None:
            source_label = "Senza incontro"
            url = reverse("tasks:project_meetings", args=[project.pk])
        else:
            source_label = f"Incontro {issue.source_meeting.numero}"
            url = reverse(
                "tasks:project_meeting_detail",
                args=[project.pk, issue.source_meeting_id],
            )
        rows.append(
            ActionRow(
                origin="issue",
                obj_id=issue.pk,
                title=issue.title,
                owner_label=_owner_label(issue.assigned_to),
                due_date=issue.due_date,
                is_open=is_open,
                is_overdue=bool(is_open and issue.due_date and issue.due_date < today),
                source_label=source_label,
                url=f"{url}#issue-{issue.pk}",
            )
        )
    return rows


def _collect_tasks(project, *, include_closed: bool) -> list[ActionRow]:
    closed_statuses = {TaskStatus.DONE, TaskStatus.CANCELED}
    queryset = project.tasks.select_related("assigned_to")
    if not include_closed:
        queryset = queryset.exclude(status__in=closed_statuses)

    return [
        ActionRow(
            origin="task",
            obj_id=task.pk,
            title=task.title,
            owner_label=_owner_label(task.assigned_to),
            due_date=task.due_date,
            is_open=task.status not in closed_statuses,
            is_overdue=task.is_overdue,
            source_label="Attivita",
            url=reverse("tasks:detail", args=[task.pk]),
        )
        for task in queryset
    ]


def _collect_subtasks(project, *, include_closed: bool) -> list[ActionRow]:
    closed_statuses = {TaskStatus.DONE, TaskStatus.CANCELED}
    queryset = SubTask.objects.filter(task__project=project).select_related("assigned_to", "task")
    if not include_closed:
        queryset = queryset.exclude(status__in=closed_statuses)

    today = timezone.localdate()
    rows = []
    for subtask in queryset:
        is_open = subtask.status not in closed_statuses
        rows.append(
            ActionRow(
                origin="subtask",
                obj_id=subtask.pk,
                title=subtask.title,
                owner_label=_owner_label(subtask.assigned_to),
                due_date=subtask.due_date,
                is_open=is_open,
                is_overdue=bool(is_open and subtask.due_date and subtask.due_date < today),
                source_label=f"Sotto-attivita di «{subtask.task.title}»",
                url=reverse("tasks:detail", args=[subtask.task_id]),
            )
        )
    return rows


def _sort_key(row: ActionRow):
    if row.is_open and row.is_overdue:
        bucket = 0
    elif row.is_open and row.due_date is not None:
        bucket = 1
    elif row.is_open:
        bucket = 2
    else:
        bucket = 3

    if bucket in {0, 1}:
        secondary = row.due_date or date.max
        title_key = ""
    elif bucket == 2:
        secondary = date.max
        title_key = row.title.casefold()
    else:
        secondary = date.max
        title_key = ""
    return (bucket, secondary, title_key, row.origin, row.obj_id)


def build_project_actions(project, *, include_closed: bool = False) -> list[ActionRow]:
    """Restituisce le azioni ordinate, mantenendo isolate le tre sorgenti."""
    rows: list[ActionRow] = []
    collectors = (
        ("issue", _collect_issues),
        ("task", _collect_tasks),
        ("subtask", _collect_subtasks),
    )
    for source_name, collector in collectors:
        try:
            rows.extend(collector(project, include_closed=include_closed))
        except Exception:
            logger.exception(
                "Impossibile raccogliere le azioni %s per il progetto %s",
                source_name,
                project.pk,
            )
    return sorted(rows, key=_sort_key)


def count_project_open_actions(project) -> int:
    """Conta le azioni aperte senza materializzare le righe del registro."""
    closed_statuses = {TaskStatus.DONE, TaskStatus.CANCELED}
    return (
        project.meeting_issues.filter(status=MeetingIssueStatus.OPEN).count()
        + project.tasks.exclude(status__in=closed_statuses).count()
        + SubTask.objects.filter(task__project=project)
        .exclude(status__in=closed_statuses)
        .count()
    )
