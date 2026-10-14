"""Registro azioni unificato per una commessa KICK-OFF."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging

from django.urls import reverse
from django.utils import timezone

from .models import MeetingActionStatus, MeetingIssueStatus, SubTask, TaskStatus

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
    owner_id: int | None = None


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
                owner_id=issue.assigned_to_id,
                due_date=issue.due_date,
                is_open=is_open,
                is_overdue=bool(is_open and issue.due_date and issue.due_date < today),
                source_label=source_label,
                url=f"{url}#issue-{issue.pk}",
            )
        )
    return rows


def _collect_meeting_actions(project, *, include_closed: bool) -> list[ActionRow]:
    """Azioni decise negli incontri: prima mancavano dal registro di commessa."""
    queryset = project.meeting_actions.select_related("assigned_to", "source_meeting")
    if not include_closed:
        queryset = queryset.filter(status=MeetingActionStatus.OPEN)

    today = timezone.localdate()
    rows = []
    for action in queryset:
        is_open = action.status == MeetingActionStatus.OPEN
        if action.source_meeting is None:
            source_label = "Azione senza incontro"
            url = reverse("tasks:project_meetings", args=[project.pk])
        else:
            source_label = f"Azione dell'incontro {action.source_meeting.numero}"
            url = reverse("tasks:project_meeting_detail", args=[project.pk, action.source_meeting_id])
        rows.append(
            ActionRow(
                origin="action",
                obj_id=action.pk,
                title=action.title,
                owner_label=_owner_label(action.assigned_to),
                owner_id=action.assigned_to_id,
                due_date=action.due_date,
                is_open=is_open,
                is_overdue=bool(is_open and action.due_date and action.due_date < today),
                source_label=source_label,
                url=f"{url}#action-{action.pk}",
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
            owner_id=task.assigned_to_id,
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
                owner_id=subtask.assigned_to_id,
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
        ("action", _collect_meeting_actions),
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


ACTION_ORIGIN_CHOICES = (
    ("action", "Azione d'incontro"),
    ("issue", "Problema"),
    ("task", "Attività"),
    ("subtask", "Sotto-attività"),
)


def filter_action_rows(
    rows: list[ActionRow], *, tipo: str = "", responsabile: str = "", scadenza: str = "", q: str = "",
) -> list[ActionRow]:
    """Filtri del registro: tipo, responsabile («nessuno» = non assegnate), scadenza, testo."""
    from datetime import timedelta

    today = timezone.localdate()
    out = rows
    if tipo in {code for code, _label in ACTION_ORIGIN_CHOICES}:
        out = [row for row in out if row.origin == tipo]
    if responsabile == "nessuno":
        out = [row for row in out if not row.owner_id]
    elif responsabile.isdigit():
        out = [row for row in out if row.owner_id == int(responsabile)]
    if scadenza == "scadute":
        out = [row for row in out if row.is_overdue]
    elif scadenza == "settimana":
        limite = today + timedelta(days=7)
        out = [row for row in out if row.is_open and row.due_date and today <= row.due_date <= limite]
    elif scadenza == "senza":
        out = [row for row in out if row.is_open and row.due_date is None]
    if q:
        needle = q.casefold()
        out = [row for row in out if needle in row.title.casefold() or needle in row.source_label.casefold()]
    return out


def annotate_open_action_counts(projects_qs):
    """Annota `open_action_count`/`overdue_action_count` sul queryset di progetti.

    Usa sottoquery correlate (una per sorgente/metrica) invece di `Count()` in
    catena sullo stesso queryset: annotare piu' `Count()` su relazioni diverse
    nella stessa query causa un fan-out dei JOIN che gonfia i conteggi. Le
    sottoquery restano nella singola query generata (nessun N+1 per riga).
    """
    from django.db.models import Count, F, IntegerField, OuterRef, Subquery
    from django.db.models.functions import Coalesce

    from .models import MeetingActionItem, MeetingIssue, SubTask, Task

    today = timezone.localdate()
    closed_statuses = (TaskStatus.DONE, TaskStatus.CANCELED)

    def _count_subquery(queryset, group_field):
        return Subquery(
            queryset.order_by().values(group_field).annotate(c=Count("id")).values("c"),
            output_field=IntegerField(),
        )

    issue_open = _count_subquery(
        MeetingIssue.objects.filter(project=OuterRef("pk"), status=MeetingIssueStatus.OPEN),
        "project",
    )
    issue_overdue = _count_subquery(
        MeetingIssue.objects.filter(
            project=OuterRef("pk"),
            status=MeetingIssueStatus.OPEN,
            due_date__isnull=False,
            due_date__lt=today,
        ),
        "project",
    )
    action_open = _count_subquery(
        MeetingActionItem.objects.filter(project=OuterRef("pk"), status=MeetingActionStatus.OPEN),
        "project",
    )
    action_overdue = _count_subquery(
        MeetingActionItem.objects.filter(
            project=OuterRef("pk"),
            status=MeetingActionStatus.OPEN,
            due_date__isnull=False,
            due_date__lt=today,
        ),
        "project",
    )
    task_open = _count_subquery(
        Task.objects.filter(project=OuterRef("pk")).exclude(status__in=closed_statuses),
        "project",
    )
    task_overdue = _count_subquery(
        Task.objects.filter(
            project=OuterRef("pk"), due_date__isnull=False, due_date__lt=today
        ).exclude(status__in=closed_statuses),
        "project",
    )
    subtask_open = _count_subquery(
        SubTask.objects.filter(task__project=OuterRef("pk")).exclude(status__in=closed_statuses),
        "task__project",
    )
    subtask_overdue = _count_subquery(
        SubTask.objects.filter(
            task__project=OuterRef("pk"), due_date__isnull=False, due_date__lt=today
        ).exclude(status__in=closed_statuses),
        "task__project",
    )

    return projects_qs.annotate(
        _oa_issue_open=Coalesce(issue_open, 0),
        _oa_action_open=Coalesce(action_open, 0),
        _oa_action_overdue=Coalesce(action_overdue, 0),
        _oa_task_open=Coalesce(task_open, 0),
        _oa_subtask_open=Coalesce(subtask_open, 0),
        _oa_issue_overdue=Coalesce(issue_overdue, 0),
        _oa_task_overdue=Coalesce(task_overdue, 0),
        _oa_subtask_overdue=Coalesce(subtask_overdue, 0),
    ).annotate(
        open_action_count=(
            F("_oa_issue_open") + F("_oa_action_open") + F("_oa_task_open") + F("_oa_subtask_open")
        ),
        overdue_action_count=(
            F("_oa_issue_overdue") + F("_oa_action_overdue") + F("_oa_task_overdue")
            + F("_oa_subtask_overdue")
        ),
    )


def count_project_open_actions(project) -> int:
    """Conta le azioni aperte senza materializzare le righe del registro."""
    closed_statuses = {TaskStatus.DONE, TaskStatus.CANCELED}
    return (
        project.meeting_issues.filter(status=MeetingIssueStatus.OPEN).count()
        + project.meeting_actions.filter(status=MeetingActionStatus.OPEN).count()
        + project.tasks.exclude(status__in=closed_statuses).count()
        + SubTask.objects.filter(task__project=project)
        .exclude(status__in=closed_statuses)
        .count()
    )
