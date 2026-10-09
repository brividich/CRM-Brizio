"""Casi SOC (ticket gestibili) e azioni massive sugli alert."""
import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import SecurityAlert, SecurityCaseTask, SecurityRemediationTicket, Severity, Status
from .services.alert_lifecycle import ACTIVE_ALERT_STATUSES, acknowledge_alert, close_alert, mark_false_positive
from .services.cases import (
    ACTIVE_CASE_STATUSES,
    CASE_STATUSES,
    CLOSED_CASE_STATUSES,
    CaseConflict,
    actor_name,
    add_alerts_to_case,
    add_note,
    add_task,
    assign_case,
    case_alerts,
    case_timeline,
    delete_task,
    open_case_from_alerts,
    set_case_status,
    toggle_task,
)
from .services.investigation import playbook

# Azioni di stato proposte nella scheda, nell'ordine in cui servono.
CASE_STATUS_ACTIONS = [
    (Status.IN_PROGRESS, "In lavorazione"),
    (Status.RESOLVED, "Risolto"),
    (Status.CLOSED, "Chiuso"),
    (Status.FALSE_POSITIVE, "Falso positivo"),
]


def _assignable_users():
    return get_user_model().objects.filter(is_active=True).order_by("username")


def _parse_ids(values):
    return [int(value) for value in values if str(value).isdigit()]


def _back(request):
    """Torna alla coda con i filtri correnti; mai verso un host esterno."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return "security:alerts_list"


@ensure_csrf_cookie
def tickets_list(request):
    cases = (
        SecurityRemediationTicket.objects.select_related("source", "alert", "assignee")
        .annotate(open_tasks=Count("tasks", filter=Q(tasks__done=False)), task_total=Count("tasks"))
        .order_by("-updated_at")
    )
    status = request.GET.get("status", "active")
    if status == "active":
        cases = cases.filter(status__in=ACTIVE_CASE_STATUSES)
    elif status in CASE_STATUSES:
        cases = cases.filter(status=status)
    severity = request.GET.get("severity", "")
    if severity in {s[0] for s in Severity.choices}:
        cases = cases.filter(severity=severity)
    assignee = request.GET.get("assignee", "")
    if assignee == "me":
        cases = cases.filter(assignee=request.user)
    elif assignee == "none":
        cases = cases.filter(assignee__isnull=True)
    origin = request.GET.get("origin", "")
    if origin in {SecurityRemediationTicket.ORIGIN_AUTO, SecurityRemediationTicket.ORIGIN_MANUAL}:
        cases = cases.filter(origin=origin)
    query = request.GET.get("q", "").strip()
    if query:
        cases = cases.filter(Q(title__icontains=query) | Q(cve__icontains=query) | Q(affected_product__icontains=query))
    total = cases.count()
    return render(
        request,
        "security/tickets_list.html",
        {
            "tickets": cases[:200],
            "total": total,
            "filters": {"status": status, "severity": severity, "assignee": assignee, "origin": origin, "q": query},
            "status_choices": [(value, value) for value in CASE_STATUSES],
            "severity_choices": Severity.choices,
            "users": _assignable_users(),
        },
    )


@ensure_csrf_cookie
def case_detail(request, pk):
    case = get_object_or_404(SecurityRemediationTicket.objects.select_related("source", "assignee", "created_by"), pk=pk)
    alerts = case_alerts(case)
    tasks = list(case.tasks.select_related("done_by"))
    book = playbook(alerts[0]) if alerts else None
    if book:
        existing = {task.title.strip().lower() for task in tasks}
        book["missing"] = [step for step in book["steps"] if step.lower() not in existing]
    return render(
        request,
        "security/case_detail.html",
        {
            "case": case,
            "alerts": alerts,
            "active_alerts_count": sum(1 for alert in alerts if alert.status in ACTIVE_ALERT_STATUSES),
            "tasks": tasks,
            "tasks_done": sum(1 for task in tasks if task.done),
            "timeline": case_timeline(case),
            "is_active": case.status in ACTIVE_CASE_STATUSES,
            "status_actions": [(value, label) for value, label in CASE_STATUS_ACTIONS if value != case.status],
            "closed_statuses": CLOSED_CASE_STATUSES,
            "users": _assignable_users(),
            "book": book,
        },
    )


@require_POST
def case_create(request):
    alerts = list(SecurityAlert.objects.filter(pk__in=_parse_ids(request.POST.getlist("alert_ids"))).order_by("-created_at"))
    if not alerts:
        messages.error(request, "Seleziona almeno un alert per aprire un caso.")
        return redirect(_back(request))
    assignee = request.user if request.POST.get("assign_to_me") else None
    case = open_case_from_alerts(
        alerts, user=request.user, title=request.POST.get("title", ""),
        description=request.POST.get("description", ""), assignee=assignee,
    )
    added = 0
    if request.POST.get("with_playbook"):
        for step in playbook(alerts[0])["steps"]:
            add_task(case, step, user=request.user)
            added += 1
    messages.success(request, f"Caso #{case.pk} aperto con {len(alerts)} alert" + (f" e {added} passi della procedura." if added else "."))
    return redirect("security:case_detail", pk=case.pk)


@require_POST
def case_tasks_add_many(request, pk):
    """Aggiunge le attivita' scelte (passi della procedura o proposti dall'AI e confermati dall'operatore)."""
    case = get_object_or_404(SecurityRemediationTicket, pk=pk)
    existing = {task.title.strip().lower() for task in case.tasks.all()}
    added = 0
    for title in request.POST.getlist("titles"):
        title = (title or "").strip()[:255]
        if title and title.lower() not in existing:
            add_task(case, title, user=request.user)
            existing.add(title.lower())
            added += 1
    if added:
        messages.success(request, f"{added} attività aggiunte al ticket.")
    else:
        messages.info(request, "Nessuna attività nuova da aggiungere.")
    return redirect("security:case_detail", pk=case.pk)


def _ai_allowed(request):
    from .permissions import can_view_security_center

    return can_view_security_center(request.user)


@require_POST
def case_ai_steps(request, pk):
    """Prossimi passi proposti dall'AI locale: diventano attivita' solo se l'operatore li spunta e conferma."""
    from .services.ai_explain import propose_case_steps

    if not _ai_allowed(request):
        return HttpResponseForbidden("Accesso negato")
    case = get_object_or_404(SecurityRemediationTicket, pk=pk)
    ai = propose_case_steps(case, user=request.user, refresh=request.POST.get("refresh") == "1")
    return render(request, "security/partials/case_ai_steps.html", {"ai": ai, "case": case})


@require_POST
def case_ai_resolution(request, pk):
    """Bozza dell'esito di chiusura scritta dall'AI locale, da rileggere e correggere prima di chiudere."""
    from .services.ai_explain import draft_resolution

    if not _ai_allowed(request):
        return HttpResponseForbidden("Accesso negato")
    case = get_object_or_404(SecurityRemediationTicket, pk=pk)
    ai = draft_resolution(case, user=request.user, refresh=request.POST.get("refresh") == "1")
    return render(request, "security/partials/case_ai_resolution.html", {"ai": ai})


@require_POST
def case_status(request, pk):
    case = get_object_or_404(SecurityRemediationTicket, pk=pk)
    new_status = request.POST.get("status", "")
    reason = request.POST.get("reason", "").strip()
    if new_status in CLOSED_CASE_STATUSES and not reason:
        messages.error(request, "Per chiudere il caso scrivi l'esito (cosa è stato fatto o perché si chiude).")
        return redirect("security:case_detail", pk=case.pk)
    try:
        set_case_status(case, new_status, user=request.user, reason=reason, close_alerts=bool(request.POST.get("close_alerts")))
    except CaseConflict as exc:
        messages.error(request, str(exc))
    except ValueError:
        messages.error(request, "Stato non valido.")
    else:
        messages.success(request, "Stato del caso aggiornato.")
    return redirect("security:case_detail", pk=case.pk)


@require_POST
def case_assign(request, pk):
    case = get_object_or_404(SecurityRemediationTicket, pk=pk)
    value = request.POST.get("assignee", "")
    if value == "me":
        assignee = request.user
    elif value.isdigit():
        assignee = get_object_or_404(_assignable_users(), pk=int(value))
    else:
        assignee = None
    assign_case(case, assignee, user=request.user)
    messages.success(request, f"Caso assegnato a {assignee.get_username()}." if assignee else "Assegnazione rimossa.")
    return redirect("security:case_detail", pk=case.pk)


@require_POST
def case_note(request, pk):
    case = get_object_or_404(SecurityRemediationTicket, pk=pk)
    try:
        add_note(case, request.POST.get("body", ""), user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("security:case_detail", pk=case.pk)


@require_POST
def case_task_add(request, pk):
    case = get_object_or_404(SecurityRemediationTicket, pk=pk)
    try:
        add_task(case, request.POST.get("title", ""), user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("security:case_detail", pk=case.pk)


@require_POST
def case_task_toggle(request, pk, task_id):
    task = get_object_or_404(SecurityCaseTask, pk=task_id, ticket_id=pk)
    toggle_task(task, user=request.user)
    return redirect("security:case_detail", pk=pk)


@require_POST
def case_task_delete(request, pk, task_id):
    task = get_object_or_404(SecurityCaseTask, pk=task_id, ticket_id=pk)
    delete_task(task, user=request.user)
    return redirect("security:case_detail", pk=pk)


@require_POST
def alerts_bulk(request):
    """Azioni sugli alert selezionati nella coda: presa in carico, chiusura, caso."""
    ids = _parse_ids(request.POST.getlist("alert_ids"))
    alerts = list(SecurityAlert.objects.filter(pk__in=ids).order_by("-created_at"))
    back = _back(request)
    if not alerts:
        messages.error(request, "Nessun alert selezionato.")
        return redirect(back)
    action = request.POST.get("action", "")
    actor = actor_name(request.user)
    reason = request.POST.get("reason", "").strip()

    if action == "open_case":
        case = open_case_from_alerts(alerts, user=request.user, title=request.POST.get("title", ""), assignee=request.user)
        messages.success(request, f"Caso #{case.pk} aperto con {len(alerts)} alert e assegnato a te.")
        return redirect("security:case_detail", pk=case.pk)
    if action == "add_to_case":
        case_id = request.POST.get("case_id", "")
        case = SecurityRemediationTicket.objects.filter(pk=int(case_id), status__in=ACTIVE_CASE_STATUSES).first() if case_id.isdigit() else None
        if case is None:
            messages.error(request, "Scegli un caso aperto a cui aggiungere gli alert.")
            return redirect(back)
        added = add_alerts_to_case(case, alerts, user=request.user)
        messages.success(request, f"{added} alert aggiunti al caso #{case.pk}.")
        return redirect("security:case_detail", pk=case.pk)

    # Le disattivazioni (falso positivo) chiedono un motivo vero; un'azione massiva conta una
    # volta sola per la soppressione appresa (stesso ``batch``).
    if action == "false_positive" and not reason:
        messages.error(request, "Per marcare come falso positivo scrivi il motivo.")
        return redirect(back)
    batch = f"bulk-{uuid.uuid4().hex[:20]}"
    handlers = {
        "acknowledge": (lambda alert: acknowledge_alert(alert, actor=actor, reason=reason or "Presa in carico massiva"), {Status.NEW, Status.OPEN}),
        "close": (lambda alert: close_alert(alert, actor=actor, reason=reason or "Chiusura massiva"), set(ACTIVE_ALERT_STATUSES)),
        "false_positive": (lambda alert: mark_false_positive(alert, actor=actor, reason=reason, batch=batch), set(ACTIVE_ALERT_STATUSES)),
    }
    if action not in handlers:
        messages.error(request, "Azione non supportata.")
        return redirect(back)
    handler, allowed = handlers[action]
    done = 0
    for alert in alerts:
        if alert.status in allowed:
            handler(alert)
            done += 1
    skipped = len(alerts) - done
    messages.success(request, f"Azione applicata a {done} alert" + (f"; {skipped} saltati perché già in uno stato non compatibile." if skipped else "."))
    return redirect(back)
