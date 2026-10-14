"""«Le mie azioni»: azioni e problemi d'incontro assegnati all'utente, e la guida."""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from ..access import can_manage_project, scoped_projects_queryset, task_permissions_required
from ..models import (
    MeetingActionItem,
    MeetingActionStatus,
    MeetingIssue,
    MeetingIssueStatus,
)
from ._shared import _safe_int, _tasks_shell_context

KIND_ACTION = "azione"
KIND_ISSUE = "problema"


def _row(item, kind: str, today) -> dict:
    is_open = (
        item.status == MeetingActionStatus.OPEN if kind == KIND_ACTION
        else item.status == MeetingIssueStatus.OPEN
    )
    meeting = item.source_meeting
    return {
        "kind": kind,
        "obj": item,
        "title": item.title,
        "description": item.description,
        "project": item.project,
        "meeting": meeting,
        "due_date": item.due_date,
        "is_open": is_open,
        "is_overdue": bool(is_open and item.due_date and item.due_date < today),
        "linked_task": item.linked_task,
    }


def mie_voci_aperte_count(request) -> int:
    """Quante azioni e problemi aperti l'utente ha in carico (per i richiami)."""
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return 0
    projects = scoped_projects_queryset(request).values("id")
    return (
        MeetingActionItem.objects.filter(
            assigned_to=user, status=MeetingActionStatus.OPEN, project_id__in=projects
        ).count()
        + MeetingIssue.objects.filter(
            assigned_to=user, status=MeetingIssueStatus.OPEN, project_id__in=projects
        ).count()
    )


@task_permissions_required("tasks_view")
def mie_azioni(request):
    """Elenco personale: prima chi riceveva un'azione non aveva un posto dove vederla."""
    today = timezone.localdate()
    projects = scoped_projects_queryset(request)
    stato = (request.GET.get("stato") or "aperte").strip()
    tipo = (request.GET.get("tipo") or "").strip()
    scadenza = (request.GET.get("scadenza") or "").strip()
    progetto = _safe_int(request.GET.get("progetto"))
    q_text = (request.GET.get("q") or "").strip()

    common = {"assigned_to": request.user, "project_id__in": projects.values("id")}
    actions = MeetingActionItem.objects.filter(**common)
    issues = MeetingIssue.objects.filter(**common)
    if stato == "aperte":
        actions = actions.filter(status=MeetingActionStatus.OPEN)
        issues = issues.filter(status=MeetingIssueStatus.OPEN)
    elif stato == "chiuse":
        actions = actions.exclude(status=MeetingActionStatus.OPEN)
        issues = issues.exclude(status=MeetingIssueStatus.OPEN)
    if progetto:
        actions = actions.filter(project_id=progetto)
        issues = issues.filter(project_id=progetto)
    if scadenza == "scadute":
        actions = actions.filter(due_date__lt=today)
        issues = issues.filter(due_date__lt=today)
    elif scadenza == "settimana":
        window = Q(due_date__gte=today, due_date__lte=today + timedelta(days=7))
        actions = actions.filter(window)
        issues = issues.filter(window)
    elif scadenza == "senza":
        actions = actions.filter(due_date__isnull=True)
        issues = issues.filter(due_date__isnull=True)
    if q_text:
        text = Q(title__icontains=q_text) | Q(description__icontains=q_text) | Q(project__name__icontains=q_text)
        actions = actions.filter(text)
        issues = issues.filter(text)

    related = ("project", "source_meeting", "linked_task")
    rows: list[dict] = []
    if tipo in ("", KIND_ACTION):
        rows += [_row(a, KIND_ACTION, today) for a in actions.select_related(*related)]
    if tipo in ("", KIND_ISSUE):
        rows += [_row(i, KIND_ISSUE, today) for i in issues.select_related(*related)]
    # Aperte prima, poi per scadenza (le senza data in fondo).
    rows.sort(key=lambda r: (not r["is_open"], r["due_date"] is None, r["due_date"] or today, r["title"].casefold()))

    my_projects = projects.filter(
        Q(meeting_actions__assigned_to=request.user) | Q(meeting_issues__assigned_to=request.user)
    ).distinct().order_by("name")
    return render(
        request,
        "tasks/mie_azioni.html",
        {
            **_tasks_shell_context(request, active="mie_azioni"),
            "page_title": "Le mie azioni",
            "rows": rows,
            "open_count": sum(1 for r in rows if r["is_open"]),
            "overdue_count": sum(1 for r in rows if r["is_overdue"]),
            "filters": {"stato": stato, "tipo": tipo, "scadenza": scadenza, "progetto": progetto or "", "q": q_text},
            "my_projects": my_projects,
        },
    )


@require_POST
@task_permissions_required("tasks_view")
def mia_voce_stato(request, kind: str, pk: int):
    """Il responsabile chiude o riapre la propria azione o il proprio problema."""
    back = redirect("tasks:mie_azioni")
    model = MeetingActionItem if kind == KIND_ACTION else MeetingIssue if kind == KIND_ISSUE else None
    if model is None:
        messages.error(request, "Voce non valida.")
        return back
    item = get_object_or_404(model.objects.select_related("project"), pk=pk, project__in=scoped_projects_queryset(request))
    if not (item.assigned_to_id == request.user.pk or can_manage_project(request, item.project)):
        messages.error(request, "Puoi aggiornare solo le voci di cui sei responsabile.")
        return back

    verb = (request.POST.get("action") or "").strip()
    if kind == KIND_ACTION:
        if verb == "done":
            item.mark_done(user=request.user)
        elif verb == "reopen":
            item.reopen()
        else:
            messages.error(request, "Azione non valida.")
            return back
        item.save(update_fields=["status", "done_by", "done_at", "updated_at"])
        etichetta = "Azione segnata come fatta." if verb == "done" else "Azione riaperta."
    else:
        if verb == "done":
            # Chiuso fuori da un incontro: nessun incontro di risoluzione.
            item.mark_resolved(meeting=None, user=request.user, note=request.POST.get("nota", ""))
        elif verb == "reopen":
            item.reopen()
        else:
            messages.error(request, "Azione non valida.")
            return back
        item.save(update_fields=[
            "status", "resolution_meeting", "resolved_by", "resolved_at", "resolution_note", "updated_at",
        ])
        etichetta = "Problema segnato come risolto." if verb == "done" else "Problema riaperto."
    log_action(request, f"kickoff_mia_voce_{verb}", "tasks", {
        "kind": kind, "id": item.pk, "project_id": item.project_id,
    })
    messages.success(request, etichetta)
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/tasks/") and "//" not in next_url:
        return redirect(next_url)
    return back


@task_permissions_required("tasks_view")
def guida(request):
    """Guida d'uso del modulo KICK-OFF (pulsante «? Guida»)."""
    from ..guida import SEZIONI

    return render(
        request,
        "tasks/guida.html",
        {
            **_tasks_shell_context(request, active="guida"),
            "page_title": "Guida KICK-OFF",
            "sezioni": SEZIONI,
        },
    )
