"""Incontri di commessa: convocazione, conduzione, minuta, problemi, azioni."""
from __future__ import annotations

import json
import logging
import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from attrezzature.models import (
    Attrezzatura,
)

from ..forms import (
    KickoffMeetingForm,
    KickoffMeetingMinuteForm,
    TaskForm,
    task_active_users_queryset,
)
from ..minute_email import note_generali
from ..models import (
    KickoffMeeting,
    MeetingActionItem,
    MeetingAgendaItem,
    MeetingAgendaProposal,
    MeetingAgendaTemplate,
    MeetingDecision,
    MeetingDecisionImpact,
    MeetingIssue,
    MeetingIssueStatus,
    MeetingProposalStatus,
    MeetingRoom,
    MeetingStatus,
    Project,
    Task,
    TaskCategory,
    TaskImpostazioni,
    TaskPriority,
)
from ..access import (
    can_manage_project,
    scoped_projects_queryset,
    task_permissions_required,
)
from ..services.agenda import (
    _agenda_templates_payload,
    _agenda_title_suggestions,
    _carry_over_agenda_items,
    _ensure_unique_agenda_item_ids,
    _meeting_action_agenda_item,
    _meeting_actions_for_form,
    _meeting_issue_agenda_item,
    _meeting_issue_ids_from_agenda,
    _meeting_issues_for_form,
    _meeting_public_url,
    _open_meeting_actions_for_project,
    _open_meeting_issues_for_project,
    _parse_optional_date,
    _previous_meeting_agenda,
    _project_tasks_for_picker,
    _set_meeting_agenda_issue_done,
)
from ..services.meeting_tasks import (
    KickoffBloccatoVRF,
    crea_attivita_da_incontro,
    notify_meeting_item_assignment,
    notify_task_assignment,
    titolo_attivita,
)
from ..services.notify import (
    notify_user,
)
from ._shared import (
    _safe_int,
    _tasks_shell_context,
)
from ._tooling import (
    _apply_task_tooling_action,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@task_permissions_required("tasks_view")
def incontri_calendario(request):
    # KickoffMeeting e' gia' importato a livello modulo
    from tasks.calendario import build_meetings_calendar

    today = timezone.localdate()
    year, month = today.year, today.month
    m_param = (request.GET.get("m") or "").strip()
    if m_param:
        try:
            y_str, mo_str = m_param.split("-")
            y, mo = int(y_str), int(mo_str)
            if 1 <= mo <= 12:
                year, month = y, mo
        except (ValueError, TypeError):
            pass
    meetings = (
        KickoffMeeting.objects
        .filter(project__in=scoped_projects_queryset(request), data__year=year, data__month=month)
        .select_related("project")
        .order_by("data", "ora")
    )
    cal = build_meetings_calendar(list(meetings), year, month, today=today)
    return render(
        request,
        "tasks/incontri_calendario.html",
        {
            **_tasks_shell_context(request, active="calendario"),
            "page_title": "Calendario incontri",
            "cal": cal,
        },
    )


@task_permissions_required("tasks_view")
def incontri_lista(request):
    """Elenco trasversale degli incontri: «i miei», filtri e ricerca nelle minute.

    Il calendario mostra un mese alla volta e il dettaglio commessa un kickoff
    alla volta: mancava il modo di trovare un incontro passato senza sapere gia'
    dove fosse.
    """
    projects = scoped_projects_queryset(request)
    meetings = (
        KickoffMeeting.objects
        .filter(project__in=projects)
        .select_related("project")
        .prefetch_related("partecipanti_utenti")
    )

    mine = (request.GET.get("mine") or "1") == "1"
    stato = (request.GET.get("stato") or "").strip()
    periodo = (request.GET.get("periodo") or "tutti").strip()
    q_text = (request.GET.get("q") or "").strip()
    progetto = _safe_int(request.GET.get("progetto"))
    minuta = (request.GET.get("minuta") or "").strip()
    today = timezone.localdate()

    if mine and request.user.is_authenticated:
        from ..meeting_alerts import _mine_filter

        meetings = meetings.filter(_mine_filter(request.user)).distinct()
    if stato in dict(MeetingStatus.choices):
        meetings = meetings.filter(stato=stato)
    if periodo == "prossimi":
        meetings = meetings.filter(data__gte=today)
    elif periodo == "passati":
        meetings = meetings.filter(data__lt=today)
    elif periodo == "settimana":
        from datetime import timedelta

        meetings = meetings.filter(data__gte=today, data__lte=today + timedelta(days=7))
    if progetto:
        meetings = meetings.filter(project_id=progetto)
    # Incontri che aspettano qualcosa: esito non registrato o minuta da approvare.
    if minuta == "da_registrare":
        meetings = meetings.filter(stato=MeetingStatus.PIANIFICATO, data__lt=today)
    elif minuta == "da_approvare":
        meetings = meetings.filter(stato=MeetingStatus.SVOLTO, minuta_chiusa_at__isnull=True)
    elif minuta == "approvata":
        meetings = meetings.filter(minuta_chiusa_at__isnull=False)
    if q_text:
        meetings = meetings.filter(
            Q(titolo__icontains=q_text)
            | Q(note__icontains=q_text)
            | Q(ordine_del_giorno__icontains=q_text)
            | Q(next_steps__icontains=q_text)
            | Q(problemi_aperti__icontains=q_text)
            | Q(luogo__icontains=q_text)
            | Q(project__name__icontains=q_text)
        )

    meetings = meetings.order_by("-data", "-ora", "-numero")[:200]
    return render(
        request,
        "tasks/incontri_lista.html",
        {
            **_tasks_shell_context(request, active="calendario"),
            "page_title": "Elenco incontri",
            "meetings": meetings,
            "filter_mine": mine,
            "filter_stato": stato,
            "filter_periodo": periodo,
            "filter_q": q_text,
            "filter_progetto": progetto or "",
            "filter_minuta": minuta,
            "projects_choices": list(projects.order_by("name").values("id", "name")),
            "stato_choices": MeetingStatus.choices,
        },
    )


# ---------------------------------------------------------------------------
# Incontri kickoff
# ---------------------------------------------------------------------------

def _sync_meeting_outlook(request, meeting) -> None:
    from ..meeting_outlook import sync_meeting_outlook_event
    level, msg = sync_meeting_outlook_event(request=request, meeting=meeting)
    if level == "success":
        messages.success(request, msg)
    elif level in ("warning", "error"):
        messages.warning(request, msg)
    elif level == "info":
        messages.info(request, msg)


def _meeting_task_modal_context(project: Project, *, project_id: int, meeting_id: int) -> dict:
    """Dati del mini-form «attivita' kickoff» usato dentro un incontro.

    Dettaglio incontro e registrazione esito montano lo stesso pannello:
    il contesto sta qui perche' aggiungere un campo non richieda di ricordarsi
    di toccare due view.
    """
    return {
        "project_tasks_json": _project_tasks_for_picker(project),
        "task_categories": TaskCategory.objects.filter(is_active=True).order_by("name"),
        "attrezzature": Attrezzatura.objects.order_by("codice", "part_number", "id"),
        "task_from_step_url": reverse(
            "tasks:project_meeting_task_from_step",
            kwargs={"project_id": project_id, "meeting_id": meeting_id},
        ),
    }


def meeting_is_deletable(meeting: KickoffMeeting) -> bool:
    """Eliminabile solo se mai svolto e senza decisioni registrate."""
    if meeting.stato == MeetingStatus.SVOLTO or meeting.minuta_chiusa:
        return False
    return not meeting.decisions.exists()


def _next_meeting_initial(previous: KickoffMeeting) -> dict:
    """Dati di partenza del prossimo incontro, presi dal precedente.

    La data proposta e' una settimana dopo il precedente, mai nel passato.
    """
    from datetime import timedelta

    today = timezone.localdate()
    proposta = previous.data + timedelta(days=7) if previous.data else today
    if proposta < today:
        proposta = today + timedelta(days=7)
    return {
        "data": proposta,
        "ora": previous.ora,
        "luogo": previous.luogo,
        "partecipanti_utenti": list(previous.partecipanti_utenti.values_list("pk", flat=True)),
        "partecipanti_email_extra": previous.partecipanti_email_extra,
        "cc_utenti": list(previous.cc_utenti.values_list("pk", flat=True)),
        "cc_email_extra": previous.cc_email_extra,
        "sync_outlook": previous.sync_outlook,
        "outlook_organizer_email": previous.outlook_organizer_email,
    }


def _send_invite_if_requested(request, form, meeting: KickoffMeeting) -> None:
    """Spunta «Invia la convocazione» del form: parte subito dopo il salvataggio."""
    if not form.cleaned_data.get("invia_convocazione") or meeting.stato != MeetingStatus.PIANIFICATO:
        return
    from ..minute_email import send_meeting_invite

    try:
        outcome = send_meeting_invite(meeting, sent_by=request.user)
    except Exception:
        logger.exception("Invio convocazione fallito (meeting=%s)", meeting.pk)
        outcome = {"sent": False, "reason": "send_error"}
    _meeting_mail_feedback(request, outcome, kind="Convocazione")
    log_action(
        request, "kickoff_meeting_send_invite", "tasks",
        {"meeting_id": meeting.pk, "project_id": meeting.project_id, "sent": bool(outcome.get("sent")), "da_form": True},
    )


def _vrf_blocked_response(project: Project) -> JsonResponse:
    """Kickoff bloccato per VRF: le scorciatoie dall'incontro non lo aggirano."""
    return JsonResponse({
        "ok": False,
        "reason": "vrf_blocked",
        "message": "Kickoff bloccato: carica il documento VRF prima di creare attività.",
        "vrf_upload_url": reverse("tasks:project_vrf_upload", kwargs={"project_id": project.pk}),
    }, status=409)


def _sync_meeting_issues_from_post(request, project: Project, meeting: KickoffMeeting) -> None:
    displayed_ids: set[int] = set()
    for raw in request.POST.getlist("meeting_issue_ids"):
        try:
            displayed_ids.add(int(raw))
        except (TypeError, ValueError):
            continue

    resolved_ids: set[int] = set()
    for raw in request.POST.getlist("resolved_issue_ids"):
        try:
            resolved_ids.add(int(raw))
        except (TypeError, ValueError):
            continue

    if displayed_ids:
        for issue in MeetingIssue.objects.filter(project=project, pk__in=displayed_ids):
            note = request.POST.get(f"issue_resolution_{issue.pk}", "")
            if issue.pk in resolved_ids:
                issue.mark_resolved(meeting=meeting, user=request.user, note=note)
                issue.save(update_fields=[
                    "status",
                    "resolution_meeting",
                    "resolved_by",
                    "resolved_at",
                    "resolution_note",
                    "updated_at",
                ])
            elif issue.resolution_meeting_id == meeting.pk and issue.status == MeetingIssueStatus.RESOLVED:
                issue.reopen()
                issue.save(update_fields=[
                    "status",
                    "resolution_meeting",
                    "resolved_by",
                    "resolved_at",
                    "resolution_note",
                    "updated_at",
                ])

        agenda_changed = False
        agenda_items = meeting.agenda_items or []
        if isinstance(agenda_items, list):
            for item in agenda_items:
                if not isinstance(item, dict):
                    continue
                try:
                    item_issue_id = int(item.get("issue_id") or 0)
                except (TypeError, ValueError):
                    item_issue_id = 0
                if item_issue_id in displayed_ids:
                    next_done = item_issue_id in resolved_ids
                    if bool(item.get("done", False)) != next_done:
                        item["done"] = next_done
                        agenda_changed = True
        if agenda_changed:
            meeting.agenda_items = agenda_items
            meeting.save(update_fields=["agenda_items", "updated_at"])

    titles = request.POST.getlist("new_issue_title")
    descriptions = request.POST.getlist("new_issue_description")
    assigned_to_ids = request.POST.getlist("new_issue_assigned_to")
    due_dates = request.POST.getlist("new_issue_due_date")
    linked_task_ids = request.POST.getlist("new_issue_task")

    for idx, raw_title in enumerate(titles):
        title = (raw_title or "").strip()
        if not title:
            continue
        description = (descriptions[idx] if idx < len(descriptions) else "").strip()
        assigned_to = None
        assigned_to_id = (assigned_to_ids[idx] if idx < len(assigned_to_ids) else "").strip()
        if assigned_to_id:
            try:
                assigned_to = User.objects.get(pk=int(assigned_to_id))
            except (User.DoesNotExist, ValueError):
                assigned_to = None
        linked_task = None
        linked_task_id = (linked_task_ids[idx] if idx < len(linked_task_ids) else "").strip()
        if linked_task_id:
            try:
                linked_task = project.tasks.get(pk=int(linked_task_id))
            except (Task.DoesNotExist, ValueError):
                linked_task = None
        issue = MeetingIssue.objects.create(
            project=project,
            source_meeting=meeting,
            title=title[:220],
            description=description,
            assigned_to=assigned_to,
            due_date=_parse_optional_date(due_dates[idx] if idx < len(due_dates) else ""),
            linked_task=linked_task,
            created_by=request.user if request.user.is_authenticated else None,
        )
        notify_meeting_item_assignment(issue, actor=request.user)


def _sync_meeting_actions_from_post(request, project: Project, meeting: KickoffMeeting) -> None:
    """Chiude/riapre le azioni mostrate e crea quelle nuove decise nell'incontro."""
    displayed_ids: set[int] = set()
    for raw in request.POST.getlist("meeting_action_ids"):
        try:
            displayed_ids.add(int(raw))
        except (TypeError, ValueError):
            continue
    done_ids: set[int] = set()
    for raw in request.POST.getlist("done_action_ids"):
        try:
            done_ids.add(int(raw))
        except (TypeError, ValueError):
            continue

    for action in MeetingActionItem.objects.filter(project=project, pk__in=displayed_ids):
        if action.pk in done_ids and not action.is_done:
            action.mark_done(user=request.user)
            action.save(update_fields=["status", "done_by", "done_at", "updated_at"])
        elif action.pk not in done_ids and action.is_done:
            action.reopen()
            action.save(update_fields=["status", "done_by", "done_at", "updated_at"])

    titles = request.POST.getlist("new_action_title")
    descriptions = request.POST.getlist("new_action_description")
    assigned_to_ids = request.POST.getlist("new_action_assigned_to")
    due_dates = request.POST.getlist("new_action_due_date")
    linked_task_ids = request.POST.getlist("new_action_task")

    for idx, raw_title in enumerate(titles):
        title = (raw_title or "").strip()
        if not title:
            continue
        assigned_to = None
        assigned_to_id = (assigned_to_ids[idx] if idx < len(assigned_to_ids) else "").strip()
        if assigned_to_id:
            try:
                assigned_to = User.objects.get(pk=int(assigned_to_id))
            except (User.DoesNotExist, ValueError):
                assigned_to = None
        linked_task = None
        linked_task_id = (linked_task_ids[idx] if idx < len(linked_task_ids) else "").strip()
        if linked_task_id:
            try:
                linked_task = project.tasks.get(pk=int(linked_task_id))
            except (Task.DoesNotExist, ValueError):
                linked_task = None
        action = MeetingActionItem.objects.create(
            project=project,
            source_meeting=meeting,
            title=title[:220],
            description=(descriptions[idx] if idx < len(descriptions) else "").strip(),
            assigned_to=assigned_to,
            due_date=_parse_optional_date(due_dates[idx] if idx < len(due_dates) else ""),
            linked_task=linked_task,
            created_by=request.user if request.user.is_authenticated else None,
        )
        notify_meeting_item_assignment(action, actor=request.user)


def _sync_meeting_decisions_from_post(request, project: Project, meeting: KickoffMeeting) -> None:
    """Registra le decisioni prese nell'incontro (append-only, mai riscritte)."""
    testi = request.POST.getlist("new_decision_testo")
    dettagli = request.POST.getlist("new_decision_dettaglio")
    autori = request.POST.getlist("new_decision_decisa_da")
    impatti = request.POST.getlist("new_decision_impatto")
    valid_impacts = {value for value, _ in MeetingDecisionImpact.choices}

    for idx, raw_testo in enumerate(testi):
        testo = (raw_testo or "").strip()
        if not testo:
            continue
        decisa_da = None
        autore_id = (autori[idx] if idx < len(autori) else "").strip()
        if autore_id:
            try:
                decisa_da = User.objects.get(pk=int(autore_id))
            except (User.DoesNotExist, ValueError):
                decisa_da = None
        impatto = (impatti[idx] if idx < len(impatti) else "").strip().upper()
        MeetingDecision.objects.create(
            project=project,
            meeting=meeting,
            testo=testo[:400],
            dettaglio=(dettagli[idx] if idx < len(dettagli) else "").strip(),
            decisa_da=decisa_da,
            impatto=impatto if impatto in valid_impacts else MeetingDecisionImpact.MEDIO,
            created_by=request.user if request.user.is_authenticated else None,
        )


@task_permissions_required("tasks_view")
def project_meetings(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meetings = list(
        project.meetings.select_related("created_by")
        .prefetch_related("partecipanti_utenti")
        .annotate(
            partecipanti_count=Count("partecipanti_utenti", distinct=True),
            open_issue_count=Count(
                "issues_created",
                filter=Q(issues_created__status=MeetingIssueStatus.OPEN),
                distinct=True,
            ),
        )
        .order_by("numero")
    )
    can_manage = can_manage_project(request, project)
    open_issue_count = project.meeting_issues.filter(status=MeetingIssueStatus.OPEN).count()

    # Data di inizio della commessa = primo incontro non annullato; «prossimo»
    # e' il primo pianificato da oggi in avanti (evidenziato in elenco).
    today = timezone.localdate()
    valid = [m for m in meetings if m.stato != MeetingStatus.ANNULLATO]
    first_meeting_date = min((m.data for m in valid), default=None)
    next_meeting = next(
        (
            m
            for m in sorted(valid, key=lambda m: m.data)
            if m.stato == MeetingStatus.PIANIFICATO and m.data >= today
        ),
        None,
    )
    for meeting in meetings:
        meeting.is_next = bool(next_meeting and meeting.pk == next_meeting.pk)

    return render(
        request,
        "tasks/project_meetings.html",
        {
            **_tasks_shell_context(request, active="meetings", project=project),
            "page_title": f"Incontri - {project.name}",
            "project": project,
            "meetings": meetings,
            "can_manage": can_manage,
            "open_issue_count": open_issue_count,
            "first_meeting_date": first_meeting_date,
            "next_meeting": next_meeting,
        },
    )


@task_permissions_required("tasks_create")
def project_meeting_create(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per aggiungere incontri a questo kickoff.")
        return redirect("tasks:project_meetings", project_id=project_id)
    meeting_issues = list(_open_meeting_issues_for_project(project))
    if request.method == "POST":
        form = KickoffMeetingForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                meeting = form.save(commit=False)
                meeting.project = project
                meeting.created_by = request.user
                meeting.save()
                form.save_m2m()
            _sync_meeting_outlook(request, meeting)
            log_action(request, "kickoff_meeting_create", "tasks", {"meeting_id": meeting.pk, "meeting_numero": meeting.numero, "project_id": project_id})
            messages.success(request, f"Incontro {meeting.numero} aggiunto.")
            _send_invite_if_requested(request, form, meeting)
            return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting.pk)
    else:
        auto_agenda = [_meeting_issue_agenda_item(issue) for issue in meeting_issues]
        auto_agenda += [
            _meeting_action_agenda_item(action)
            for action in _open_meeting_actions_for_project(project)
        ]
        auto_agenda += _carry_over_agenda_items(project)
        initial = {
            "data": timezone.localdate(),
            "agenda_items_raw": json.dumps(auto_agenda),
            "partecipanti_utenti": project.team_user_ids,
        }
        # «Pianifica prossimo incontro»: si riparte dal precedente (convocati,
        # copia, luogo, ora), non solo dal team di commessa.
        previous = project.meetings.filter(pk=_safe_int(request.GET.get("da"))).first() if request.GET.get("da") else None
        if previous is not None:
            initial.update(_next_meeting_initial(previous))
        form = KickoffMeetingForm(initial=initial)
    project_tasks = _project_tasks_for_picker(project)
    meeting_rooms = list(MeetingRoom.objects.values_list("nome", flat=True))
    active_users = task_active_users_queryset()
    cc_predefiniti = TaskImpostazioni.get_singleton().get_cc_predefiniti()
    previous_agenda = _previous_meeting_agenda(project)
    return render(
        request,
        "tasks/project_meeting_form.html",
        {
            **_tasks_shell_context(request, active="meetings", project=project),
            "page_title": f"Nuovo incontro - {project.name}",
            "project": project,
            "form": form,
            "is_edit": False,
            # `json_script` serializa da solo: passargli una stringa gia' in JSON
            # la incapsula una seconda volta e in pagina si ottiene una stringa,
            # non una lista (rompeva i menu «Task collegato» delle righe nuove).
            "project_tasks_json": project_tasks,
            "meeting_rooms_json": meeting_rooms,
            "carried_issues": meeting_issues,
            "active_users": active_users,
            "cc_predefiniti": cc_predefiniti,
            "agenda_templates": list(MeetingAgendaTemplate.objects.filter(is_active=True)),
            "agenda_templates_json": _agenda_templates_payload(),
            "previous_agenda_json": previous_agenda,
            "has_previous_agenda": bool(previous_agenda),
            "agenda_suggestions_json": _agenda_title_suggestions(),
        },
    )


@task_permissions_required("tasks_view")
def project_meeting_detail(request, project_id: int, meeting_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(
        KickoffMeeting.objects.prefetch_related("partecipanti_utenti"),
        pk=meeting_id, project=project,
    )
    can_manage = can_manage_project(request, project)
    # Righe next_steps non vuote (per CTA "Crea task da questo step")
    next_steps_lines = [l.strip() for l in (meeting.next_steps or "").splitlines() if l.strip()]
    agenda_issue_ids = _meeting_issue_ids_from_agenda(meeting)
    meeting_issues = list(
        project.meeting_issues
        .filter(
            Q(source_meeting=meeting)
            | Q(resolution_meeting=meeting)
            | Q(pk__in=agenda_issue_ids)
        )
        .select_related("source_meeting", "resolution_meeting", "assigned_to", "linked_task", "resolved_by")
        .distinct()
        .order_by("status", "due_date", "created_at", "id")
    )
    open_issue_count = sum(1 for issue in meeting_issues if not issue.is_resolved)
    return render(
        request,
        "tasks/project_meeting_detail.html",
        {
            **_tasks_shell_context(request, active="meetings", project=project),
            "page_title": f"Incontro {meeting.numero} - {project.name}",
            "project": project,
            "meeting": meeting,
            "note_generali": note_generali(meeting),
            "can_manage": can_manage,
            "can_delete": can_manage and meeting_is_deletable(meeting),
            "meeting_issues": meeting_issues,
            "open_issue_count": open_issue_count,
            "meeting_actions": list(_meeting_actions_for_form(project, meeting)),
            "meeting_decisions": list(meeting.decisions.select_related("decisa_da")),
            "meeting_proposals": list(meeting.agenda_proposals.select_related("proposed_by")),
            "is_convocato": meeting.partecipanti_utenti.filter(pk=request.user.pk).exists(),
            "next_steps_lines": next_steps_lines,
            "active_users": task_active_users_queryset() if can_manage else [],
            "agenda_toggle_url_base": f"/tasks/projects/{project_id}/incontri/{meeting_id}/agenda-toggle/",
            **_meeting_task_modal_context(project, project_id=project_id, meeting_id=meeting_id),
        },
    )


@task_permissions_required("tasks_create")
def project_meeting_edit(request, project_id: int, meeting_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per modificare questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    if request.method == "POST":
        old_data, old_stato = meeting.data, meeting.stato
        form = KickoffMeetingForm(request.POST, instance=meeting)
        if form.is_valid():
            with transaction.atomic():
                meeting = form.save(commit=False)
                # Incontro rinviato: il promemoria del giorno prima va rifatto
                # sulla data nuova, anche se era gia' partito per quella vecchia.
                if meeting.data != old_data:
                    meeting.reminder_sent_at = None
                # Incontro annullato ripristinato: via i dati dell'annullamento.
                # Anche la convocazione torna «da inviare»: i convocati hanno
                # ricevuto l'annullamento, non devono leggere un «aggiornamento».
                if old_stato == MeetingStatus.ANNULLATO and meeting.stato == MeetingStatus.PIANIFICATO:
                    meeting.annullato_at = None
                    meeting.annullato_da = None
                    meeting.annullato_motivo = ""
                    meeting.convocazione_inviata_at = None
                    meeting.convocazione_firma = ""
                    meeting.reminder_sent_at = None
                meeting.save()
                form.save_m2m()
            if meeting.stato != MeetingStatus.ANNULLATO:
                _sync_meeting_outlook(request, meeting)
            log_action(request, "kickoff_meeting_edit", "tasks", {"meeting_id": meeting.pk, "meeting_numero": meeting.numero, "project_id": project_id})
            messages.success(request, "Incontro aggiornato.")
            _send_invite_if_requested(request, form, meeting)
            return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    else:
        form = KickoffMeetingForm(instance=meeting)
    project_tasks = _project_tasks_for_picker(project)
    meeting_rooms = list(MeetingRoom.objects.values_list("nome", flat=True))
    active_users = task_active_users_queryset()
    cc_predefiniti = TaskImpostazioni.get_singleton().get_cc_predefiniti()
    previous_agenda = _previous_meeting_agenda(project, exclude_meeting_id=meeting.pk)
    return render(
        request,
        "tasks/project_meeting_form.html",
        {
            **_tasks_shell_context(request, active="meetings", project=project),
            "page_title": f"Modifica incontro {meeting.numero} - {project.name}",
            "project": project,
            "meeting": meeting,
            "form": form,
            "is_edit": True,
            # `json_script` serializa da solo: passargli una stringa gia' in JSON
            # la incapsula una seconda volta e in pagina si ottiene una stringa,
            # non una lista (rompeva i menu «Task collegato» delle righe nuove).
            "project_tasks_json": project_tasks,
            "meeting_rooms_json": meeting_rooms,
            "carried_issues": _open_meeting_issues_for_project(project),
            "active_users": active_users,
            "cc_predefiniti": cc_predefiniti,
            "agenda_templates": list(MeetingAgendaTemplate.objects.filter(is_active=True)),
            "agenda_templates_json": _agenda_templates_payload(),
            "previous_agenda_json": previous_agenda,
            "has_previous_agenda": bool(previous_agenda),
            "agenda_suggestions_json": _agenda_title_suggestions(),
        },
    )


@task_permissions_required("tasks_create")
def project_meeting_minutes(request, project_id: int, meeting_id: int):
    """Registrazione dell'esito: verbale, problemi e next steps DOPO l'incontro.

    Seconda meta' del flusso, complementare alla convocazione
    (`project_meeting_edit`). Salvando, l'incontro passa in stato «Svolto».
    """
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per registrare l'esito di questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    # Minuta approvata = documento chiuso: si modifica solo dopo una riapertura
    # esplicita, che resta a registro.
    if meeting.minuta_chiusa:
        messages.warning(
            request,
            "La minuta è approvata e non è modificabile. Riaprila dal dettaglio incontro per correggerla.",
        )
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    if request.method == "POST":
        form = KickoffMeetingMinuteForm(request.POST, instance=meeting)
        if form.is_valid():
            with transaction.atomic():
                meeting = form.save(commit=False)
                already_svolto = meeting.stato == MeetingStatus.SVOLTO
                meeting.stato = MeetingStatus.SVOLTO
                if not already_svolto:
                    meeting.svolto_at = timezone.now()
                # Registrare l'esito significa aver fatto l'appello: da qui in poi
                # «nessun presente» e' un dato, non un incontro storico senza presenze.
                meeting.presenze_registrate_at = timezone.now()
                meeting.save()
                form.save_m2m()
                _sync_meeting_issues_from_post(request, project, meeting)
                _sync_meeting_actions_from_post(request, project, meeting)
                _sync_meeting_decisions_from_post(request, project, meeting)
            log_action(
                request, "kickoff_meeting_minutes", "tasks",
                {"meeting_id": meeting.pk, "meeting_numero": meeting.numero, "project_id": project_id},
            )
            messages.success(request, f"Esito dell'incontro {meeting.numero} registrato.")
            return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    else:
        form = KickoffMeetingMinuteForm(instance=meeting)
        # Minute storiche: le note dei punti erano ricopiate nel verbale e ora
        # stanno gia' nell'ordine del giorno, quindi qui non si riproducono.
        form.initial["note"] = note_generali(meeting)

    return render(
        request,
        "tasks/project_meeting_minutes.html",
        {
            **_tasks_shell_context(request, active="meetings", project=project),
            "page_title": f"Esito incontro {meeting.numero} - {project.name}",
            "project": project,
            "meeting": meeting,
            "form": form,
            "meeting_issues": list(_meeting_issues_for_form(project, meeting)),
            "meeting_actions": list(_meeting_actions_for_form(project, meeting)),
            "meeting_decisions": list(meeting.decisions.select_related("decisa_da")),
            "decision_impacts": MeetingDecisionImpact.choices,
            "active_users": task_active_users_queryset(),
            **_meeting_task_modal_context(project, project_id=project_id, meeting_id=meeting_id),
        },
    )


def _meeting_mail_feedback(request, outcome: dict, *, kind: str) -> None:
    """Traduce l'esito di send_meeting_invite/minute in un messaggio utente."""
    if outcome.get("sent"):
        recipients = outcome.get("recipients") or []
        if outcome.get("aggiornamento"):
            messages.success(request, f"Aggiornamento della convocazione inviato a {len(recipients)} destinatari.")
        else:
            messages.success(request, f"{kind} inviata a {len(recipients)} destinatari.")
        return
    reason = outcome.get("reason") or ""
    if reason == "no_recipients":
        messages.warning(
            request,
            f"{kind} non inviata: l'incontro non ha partecipanti con un indirizzo email.",
        )
    else:
        messages.error(request, f"{kind} non inviata: errore durante l'invio.")


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_send_invite(request, project_id: int, meeting_id: int):
    """Invia ai partecipanti la convocazione con l'ordine del giorno (+ .ics)."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per inviare la convocazione di questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    from ..minute_email import send_meeting_invite

    try:
        outcome = send_meeting_invite(meeting, sent_by=request.user)
    except Exception:
        logger.exception("Invio convocazione fallito (meeting=%s)", meeting.pk)
        outcome = {"sent": False, "reason": "send_error"}
    _meeting_mail_feedback(request, outcome, kind="Convocazione")
    log_action(
        request, "kickoff_meeting_send_invite", "tasks",
        {"meeting_id": meeting.pk, "project_id": project_id, "sent": bool(outcome.get("sent"))},
    )
    return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_send_minute(request, project_id: int, meeting_id: int):
    """Invia ai partecipanti la minuta dell'incontro (+ PDF allegato)."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per inviare la minuta di questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    from ..minute_email import send_meeting_minute

    try:
        outcome = send_meeting_minute(meeting, sent_by=request.user)
    except Exception:
        logger.exception("Invio minuta fallito (meeting=%s)", meeting.pk)
        outcome = {"sent": False, "reason": "send_error"}
    _meeting_mail_feedback(request, outcome, kind="Minuta")
    log_action(
        request, "kickoff_meeting_send_minute", "tasks",
        {"meeting_id": meeting.pk, "project_id": project_id, "sent": bool(outcome.get("sent"))},
    )
    return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)


@task_permissions_required("tasks_view")
def project_meeting_minute_pdf(request, project_id: int, meeting_id: int):
    """Scarica la minuta dell'incontro in PDF (stesso documento allegato alla mail)."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)

    from django.http import HttpResponse

    from ..minute_email import build_minute_pdf

    try:
        pdf = build_minute_pdf(meeting)
    except Exception:
        logger.exception("Generazione PDF minuta fallita (meeting=%s)", meeting.pk)
        messages.error(request, "Impossibile generare il PDF della minuta.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    kickoff = getattr(project, "kickoff_number", "") or project.pk
    filename = f"minuta-kickoff-{kickoff}-inc{meeting.numero}.pdf"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    log_action(
        request, "kickoff_meeting_minute_pdf", "tasks",
        {"meeting_id": meeting.pk, "project_id": project_id},
    )
    return response


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_minute_close(request, project_id: int, meeting_id: int):
    """Approva e chiude la minuta: da qui in poi l'esito e' in sola lettura."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per approvare la minuta di questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    if not meeting.is_svolto:
        messages.error(request, "Registra prima l'esito dell'incontro: una minuta vuota non si approva.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    if meeting.minuta_chiusa:
        messages.info(request, "La minuta era già approvata.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    meeting.minuta_chiusa_at = timezone.now()
    meeting.minuta_chiusa_da = request.user
    meeting.save(update_fields=["minuta_chiusa_at", "minuta_chiusa_da", "updated_at"])
    from ..ai_kickoff import registra_esito

    registra_esito(meeting, user=request.user)
    log_action(
        request, "kickoff_meeting_minute_close", "tasks",
        {"meeting_id": meeting.pk, "meeting_numero": meeting.numero, "project_id": project_id},
    )
    messages.success(request, "Minuta approvata: l'esito è ora in sola lettura.")
    return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_minute_reopen(request, project_id: int, meeting_id: int):
    """Riapre una minuta approvata. Il motivo e' obbligatorio e finisce a registro."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per riaprire la minuta di questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    if not meeting.minuta_chiusa:
        messages.info(request, "La minuta non è approvata: è già modificabile.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    motivo = (request.POST.get("motivo") or "").strip()
    if not motivo:
        messages.error(request, "Per riaprire la minuta serve un motivo: resta a registro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    meeting.minuta_chiusa_at = None
    meeting.minuta_chiusa_da = None
    meeting.minuta_riaperture = (meeting.minuta_riaperture or 0) + 1
    meeting.save(update_fields=[
        "minuta_chiusa_at", "minuta_chiusa_da", "minuta_riaperture", "updated_at",
    ])
    log_action(
        request, "kickoff_meeting_minute_reopen", "tasks",
        {
            "meeting_id": meeting.pk,
            "meeting_numero": meeting.numero,
            "project_id": project_id,
            "motivo": motivo[:500],
            "riaperture": meeting.minuta_riaperture,
        },
    )
    messages.success(request, "Minuta riaperta: l'esito è di nuovo modificabile.")
    return redirect("tasks:project_meeting_minutes", project_id=project_id, meeting_id=meeting_id)


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_delete(request, project_id: int, meeting_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per eliminare questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    # Un incontro tenuto e' un fatto documentato: con lui spariscono le decisioni
    # del registro di commessa. Si eliminano solo incontri mai svolti.
    if not meeting_is_deletable(meeting):
        messages.error(
            request,
            "Questo incontro è stato svolto: non si può eliminare, perché con lui sparirebbero "
            "verbale e decisioni. Se non si è tenuto davvero, riapri la minuta e correggi l'esito.",
        )
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    numero = meeting.numero
    # Prima di cancellare il record va rimosso l'evento dal calendario dei
    # partecipanti: `sync_meeting_outlook_event` cancella su Graph quando
    # `sync_outlook` e' falso. Senza questo passaggio l'invito restava orfano.
    if meeting.outlook_event_id:
        meeting.sync_outlook = False
        _sync_meeting_outlook(request, meeting)
    meeting.delete()
    log_action(request, "kickoff_meeting_delete", "tasks", {"meeting_numero": numero, "project_id": project_id})
    messages.success(request, f"Incontro {numero} eliminato.")
    return redirect("tasks:project_meetings", project_id=project_id)


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_cancel(request, project_id: int, meeting_id: int):
    """Annulla un incontro pianificato: motivo obbligatorio, Outlook e convocati avvisati.

    Prima «Annullato» era una voce del menu Stato: l'evento restava nei
    calendari e nessuno sapeva che l'incontro non si teneva piu'.
    """
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    detail = redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per annullare questo incontro.")
        return detail
    if meeting.stato != MeetingStatus.PIANIFICATO:
        messages.info(request, "Si possono annullare solo gli incontri pianificati.")
        return detail
    motivo = (request.POST.get("motivo") or "").strip()
    if not motivo:
        messages.error(request, "Per annullare l'incontro serve un motivo: lo ricevono i convocati.")
        return detail

    meeting.stato = MeetingStatus.ANNULLATO
    meeting.annullato_at = timezone.now()
    meeting.annullato_da = request.user
    meeting.annullato_motivo = motivo[:2000]
    meeting.save(update_fields=["stato", "annullato_at", "annullato_da", "annullato_motivo", "updated_at"])

    # Evento Outlook: con `sync_outlook` falso il sync lo cancella da Graph.
    if meeting.outlook_event_id:
        meeting.sync_outlook = False
        _sync_meeting_outlook(request, meeting)
        meeting.save(update_fields=["sync_outlook"])

    avvisa = request.POST.get("avvisa") not in ("0", "false", "off")
    sent = False
    if avvisa:
        from ..minute_email import send_meeting_cancellation

        try:
            outcome = send_meeting_cancellation(meeting, sent_by=request.user)
        except Exception:
            logger.exception("Invio annullamento fallito (meeting=%s)", meeting.pk)
            outcome = {"sent": False, "reason": "send_error"}
        sent = bool(outcome.get("sent"))
        _meeting_mail_feedback(request, outcome, kind="Comunicazione di annullamento")
    log_action(request, "kickoff_meeting_cancel", "tasks", {
        "meeting_id": meeting.pk, "meeting_numero": meeting.numero, "project_id": project_id,
        "motivo": motivo[:500], "avvisati": sent,
    })
    messages.success(request, f"Incontro {meeting.numero} annullato.")
    return detail


@require_POST
@task_permissions_required("tasks_view")
def project_meeting_issue_status(request, project_id: int, meeting_id: int, issue_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    issue = get_object_or_404(MeetingIssue, pk=issue_id, project=project)
    # Il responsabile chiude da se' il proprio problema: prima doveva chiederlo
    # a chi gestisce la commessa.
    if not (can_manage_project(request, project) or issue.assigned_to_id == request.user.pk):
        messages.error(request, "Non hai i permessi per aggiornare i problemi di questo kickoff.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    action = (request.POST.get("action") or "").strip()
    if action == "resolve":
        issue.mark_resolved(
            meeting=meeting,
            user=request.user,
            note=request.POST.get("resolution_note", ""),
        )
        issue.save(update_fields=[
            "status",
            "resolution_meeting",
            "resolved_by",
            "resolved_at",
            "resolution_note",
            "updated_at",
        ])
        _set_meeting_agenda_issue_done(meeting, issue.pk, True)
        log_action(request, "kickoff_meeting_issue_resolve", "tasks", {"issue_id": issue.pk, "meeting_id": meeting.pk, "project_id": project.pk})
        messages.success(request, "Problema segnato come risolto.")
    elif action == "reopen":
        issue.reopen()
        issue.save(update_fields=[
            "status",
            "resolution_meeting",
            "resolved_by",
            "resolved_at",
            "resolution_note",
            "updated_at",
        ])
        _set_meeting_agenda_issue_done(meeting, issue.pk, False)
        log_action(request, "kickoff_meeting_issue_reopen", "tasks", {"issue_id": issue.pk, "meeting_id": meeting.pk, "project_id": project.pk})
        messages.info(request, "Problema riaperto e riportato nei prossimi incontri.")
    else:
        messages.error(request, "Azione non valida.")
    return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)


@require_POST
@task_permissions_required("tasks_view")
def project_meeting_proposal_create(request, project_id: int, meeting_id: int):
    """Un convocato propone un punto all'ordine del giorno."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    detail = redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    is_convocato = meeting.partecipanti_utenti.filter(pk=request.user.pk).exists()
    if not (is_convocato or can_manage_project(request, project)):
        messages.error(request, "Solo chi è convocato può proporre un punto per questo incontro.")
        return detail

    titolo = (request.POST.get("titolo") or "").strip()
    if not titolo:
        messages.error(request, "Indica il punto che vuoi proporre.")
        return detail

    proposal = MeetingAgendaProposal.objects.create(
        meeting=meeting,
        proposed_by=request.user,
        titolo=titolo[:200],
        nota=(request.POST.get("nota") or "").strip(),
    )
    log_action(request, "kickoff_meeting_proposal_create", "tasks", {
        "proposal_id": proposal.pk, "meeting_id": meeting.pk, "project_id": project.pk,
    })
    autore = request.user.get_full_name() or request.user.username
    referenti = project.team_members("project_managers") + project.team_members("capi_commessa")
    for manager in {u.pk: u for u in referenti}.values():
        if manager.pk != request.user.pk:
            notify_user(
                manager,
                f'{autore} propone un punto per l\'incontro {meeting.numero}: "{titolo}".',
                _meeting_public_url(meeting),
                tipo="generico",
            )
    messages.success(request, "Punto proposto: lo vedrà chi gestisce la commessa.")
    return detail


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_proposal_decide(request, project_id: int, meeting_id: int, proposal_id: int):
    """Accetta (l'item entra in agenda) o rifiuta una proposta."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    proposal = get_object_or_404(MeetingAgendaProposal, pk=proposal_id, meeting=meeting)
    detail = redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per decidere sulle proposte di questo incontro.")
        return detail
    if not proposal.is_pending:
        messages.info(request, "Questa proposta è già stata valutata.")
        return detail

    verb = (request.POST.get("action") or "").strip()
    nota_decisione = (request.POST.get("nota_decisione") or "").strip()[:255]
    if verb not in ("accept", "reject"):
        messages.error(request, "Azione non valida.")
        return detail

    if verb == "accept":
        proposta_autore = proposal.proposed_by
        etichetta = (
            proposta_autore.get_full_name() or proposta_autore.username
            if proposta_autore is not None else ""
        )
        items = list(meeting.agenda_items or [])
        items.append({
            "id": f"proposal-{proposal.pk}",
            "titolo": proposal.titolo,
            "nota": proposal.nota,
            "task_id": None,
            "task_label": "",
            "issue_id": None,
            "action_id": None,
            "source": "proposal",
            "locked": False,
            "responsabile_id": None,
            "responsabile_label": "",
            "durata_minuti": None,
            "custom_fields": [{"label": "Proposto da", "value": etichetta}] if etichetta else [],
            "done": False,
        })
        meeting.agenda_items = items
        meeting.save(update_fields=["agenda_items", "updated_at"])
        proposal.stato = MeetingProposalStatus.ACCEPTED
        esito_msg = "accettata: è nell'ordine del giorno"
    else:
        proposal.stato = MeetingProposalStatus.REJECTED
        esito_msg = "non accettata"

    proposal.nota_decisione = nota_decisione
    proposal.decided_by = request.user
    proposal.decided_at = timezone.now()
    proposal.save(update_fields=["stato", "nota_decisione", "decided_by", "decided_at"])
    log_action(request, "kickoff_meeting_proposal_decide", "tasks", {
        "proposal_id": proposal.pk, "meeting_id": meeting.pk,
        "project_id": project.pk, "stato": proposal.stato,
    })
    if proposal.proposed_by is not None and proposal.proposed_by.pk != request.user.pk:
        notify_user(
            proposal.proposed_by,
            f'La tua proposta "{proposal.titolo}" per l\'incontro {meeting.numero} è {esito_msg}.',
            _meeting_public_url(meeting),
            tipo="generico",
        )
    messages.success(request, f"Proposta {proposal.get_stato_display().lower()}.")
    return detail


@require_POST
@task_permissions_required("tasks_view")
def project_meeting_action_status(request, project_id: int, meeting_id: int, action_id: int):
    """Chiude o riapre un'azione dell'incontro dal dettaglio."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    action = get_object_or_404(MeetingActionItem, pk=action_id, project=project)
    if not (can_manage_project(request, project) or action.assigned_to_id == request.user.pk):
        messages.error(request, "Non hai i permessi per aggiornare le azioni di questo kickoff.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    verb = (request.POST.get("action") or "").strip()
    if verb == "done":
        action.mark_done(user=request.user)
        action.save(update_fields=["status", "done_by", "done_at", "updated_at"])
        log_action(request, "kickoff_meeting_action_done", "tasks", {
            "action_id": action.pk, "meeting_id": meeting.pk, "project_id": project.pk,
        })
        messages.success(request, "Azione segnata come fatta.")
    elif verb == "reopen":
        action.reopen()
        action.save(update_fields=["status", "done_by", "done_at", "updated_at"])
        log_action(request, "kickoff_meeting_action_reopen", "tasks", {
            "action_id": action.pk, "meeting_id": meeting.pk, "project_id": project.pk,
        })
        messages.info(request, "Azione riaperta e riportata nei prossimi incontri.")
    else:
        messages.error(request, "Azione non valida.")
    return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)


@task_permissions_required("tasks_view")
def project_decisions(request, project_id: int):
    """Registro decisioni della commessa: cosa e' stato deciso, da chi, quando."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    decisions = (
        project.meeting_decisions
        .select_related("meeting", "decisa_da")
        .order_by("-created_at", "-id")
    )
    return render(
        request,
        "tasks/project_decisions.html",
        {
            **_tasks_shell_context(request, active="meetings", project=project),
            "page_title": f"Registro decisioni - {project.name}",
            "project": project,
            "decisions": decisions,
        },
    )


@task_permissions_required("tasks_create")
def project_meeting_run(request, project_id: int, meeting_id: int):
    """Schermata di conduzione: un punto alla volta, tempi e cattura rapida.

    Prima esisteva solo il «dopo»: si conduceva la riunione altrove e si
    riportava tutto a mano nella pagina esito.
    """
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        messages.error(request, "Non hai i permessi per condurre questo incontro.")
        return redirect("tasks:project_meeting_detail", project_id=project_id, meeting_id=meeting_id)

    items = _ensure_unique_agenda_item_ids(meeting)
    planned_minutes = sum(int(item.get("durata_minuti") or 0) for item in items)
    presenti_ids = set(meeting.presenti_utenti.values_list("pk", flat=True))
    presenti_email = set(meeting.get_presenti_email_list())
    appello = [
        {"user_id": user.pk, "email": "", "label": user.get_full_name() or user.username,
         "presente": user.pk in presenti_ids}
        for user in meeting.partecipanti_utenti.all()
    ] + [
        {"user_id": "", "email": email, "label": email, "presente": email in presenti_email}
        for email in meeting.get_partecipanti_email_list()
    ]
    return render(
        request,
        "tasks/project_meeting_run.html",
        {
            **_tasks_shell_context(request, active="meetings", project=project),
            "page_title": f"Conduci incontro {meeting.numero} - {project.name}",
            "project": project,
            "meeting": meeting,
            "appello": appello,
            "attendance_url": reverse(
                "tasks:project_meeting_attendance",
                kwargs={"project_id": project_id, "meeting_id": meeting_id},
            ),
            "agenda_items": items,
            "planned_minutes": planned_minutes,
            "done_count": sum(1 for item in items if item.get("done")),
            "active_users": task_active_users_queryset(),
            "decision_impacts": MeetingDecisionImpact.choices,
            "item_update_url": reverse(
                "tasks:project_meeting_agenda_item_update",
                kwargs={"project_id": project_id, "meeting_id": meeting_id},
            ),
            "quick_capture_url": reverse(
                "tasks:project_meeting_quick_capture",
                kwargs={"project_id": project_id, "meeting_id": meeting_id},
            ),
            "item_task_create_url": reverse(
                "tasks:project_meeting_agenda_item_task_create",
                kwargs={"project_id": project_id, "meeting_id": meeting_id},
            ),
            "project_tasks_json": _project_tasks_for_picker(project),
        },
    )


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_attendance(request, project_id: int, meeting_id: int):
    """Appello dalla conduzione: segna presente/assente un convocato (autosave).

    Le presenze prima si registravano solo nell'esito, a incontro finito e a
    memoria. Il dato e' lo stesso che l'esito mostra e la minuta usa.
    """
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    presente = (request.POST.get("presente") or "").lower() in ("1", "true", "on")
    user_id = _safe_int(request.POST.get("user_id"))
    email = (request.POST.get("email") or "").strip()
    with transaction.atomic():
        if user_id:
            user = meeting.partecipanti_utenti.filter(pk=user_id).first()
            if user is None:
                return JsonResponse({"ok": False, "reason": "not_convocato"}, status=404)
            if presente:
                meeting.presenti_utenti.add(user)
            else:
                meeting.presenti_utenti.remove(user)
        elif email:
            if email not in meeting.get_partecipanti_email_list():
                return JsonResponse({"ok": False, "reason": "not_convocato"}, status=404)
            presenti = [e for e in meeting.get_presenti_email_list() if e != email]
            if presente:
                presenti.append(email)
            meeting.presenti_email_extra = "\n".join(presenti)
        else:
            return JsonResponse({"ok": False, "reason": "missing_target"}, status=400)
        if not meeting.presenze_registrate_at:
            meeting.presenze_registrate_at = timezone.now()
        meeting.save(update_fields=["presenti_email_extra", "presenze_registrate_at", "updated_at"])
    return JsonResponse({"ok": True, "presente": presente, "presenti": meeting.presenti_count})


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_agenda_item_update(request, project_id: int, meeting_id: int):
    """Autosave di nota, spunta e tempo effettivo su un punto dell'agenda."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    item_id = (request.POST.get("item_id") or "").strip()
    # Si aggiorna solo la riga del punto: riscrivere tutto l'ordine del giorno a
    # ogni autosave faceva perdere una nota se nel frattempo arrivava una spunta.
    row = MeetingAgendaItem.objects.filter(meeting=meeting, item_id=item_id).first()
    if row is None:
        return JsonResponse({"ok": False, "reason": "item_not_found"}, status=404)

    changed: list[str] = []
    if "nota" in request.POST:
        row.nota = (request.POST.get("nota") or "").strip()[:1000]
        changed.append("nota")
    if "done" in request.POST:
        row.done = (request.POST.get("done") or "").lower() in ("1", "true", "on")
        changed.append("done")
    if "tempo_effettivo_minuti" in request.POST:
        try:
            minuti = int(request.POST.get("tempo_effettivo_minuti") or 0)
        except (TypeError, ValueError):
            minuti = 0
        row.tempo_effettivo_minuti = minuti if 0 < minuti <= 480 else None
        changed.append("tempo_effettivo_minuti")
    if "task_id" in request.POST:
        # Collegamento all'attivita' anche durante la conduzione: mentre si
        # parla si capisce quale attivita' copre il punto, e prima lo si poteva
        # dire solo tornando nella convocazione.
        raw_task_id = (request.POST.get("task_id") or "").strip()
        if not raw_task_id:
            row.task = None
            row.task_label = ""
        else:
            task = project.tasks.filter(pk=_safe_int(raw_task_id)).first()
            if task is None:
                return JsonResponse({"ok": False, "reason": "task_not_found"}, status=404)
            row.task = task
            row.task_label = task.title[:200]
        changed += ["task", "task_label"]

    if changed:
        row.save(update_fields=changed)
        KickoffMeeting.objects.filter(pk=meeting.pk).update(updated_at=timezone.now())
    return JsonResponse({
        "ok": True,
        "item_id": item_id,
        "done": bool(row.done),
        "tempo_effettivo_minuti": row.tempo_effettivo_minuti,
        "task_id": row.task_id,
        "task_label": row.task_label or "",
    })


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_agenda_item_task_create(request, project_id: int, meeting_id: int):
    """Crea un'attivita' di commessa e la collega al punto ODG, dalla conduzione.

    Durante l'incontro il punto spesso diventa un'attivita': senza questo
    passaggio bisognava uscire dalla pagina, creare il task altrove e tornare a
    collegarlo a mano.
    """
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    item_id = (request.POST.get("item_id") or "").strip()
    items = meeting.agenda_items or []
    target = None
    for item in items:
        if isinstance(item, dict) and str(item.get("id", "")) == item_id:
            target = item
            break
    if target is None:
        return JsonResponse({"ok": False, "reason": "item_not_found"}, status=404)

    title = (request.POST.get("title") or "").strip()
    if not title:
        return JsonResponse({"ok": False, "reason": "title_required"}, status=400)

    assigned_to = None
    assigned_to_id = (request.POST.get("assigned_to") or "").strip()
    if assigned_to_id:
        assigned_to = User.objects.filter(pk=_safe_int(assigned_to_id)).first()
    due_date = _parse_optional_date(request.POST.get("due_date") or "")
    priority = (request.POST.get("priority") or TaskPriority.MEDIUM).strip().upper()

    try:
        with transaction.atomic():
            task = crea_attivita_da_incontro(
                project=project,
                meeting=meeting,
                user=request.user,
                title=title,
                assigned_to=assigned_to,
                due_date=due_date,
                priority=priority,
                nota=str(target.get("nota") or ""),
            )
            MeetingAgendaItem.objects.filter(meeting=meeting, item_id=item_id).update(
                task=task, task_label=task.title[:200]
            )
    except KickoffBloccatoVRF:
        return _vrf_blocked_response(project)

    log_action(request, "kickoff_task_from_agenda_item", "tasks", {
        "task_id": task.pk, "item_id": item_id,
        "meeting_id": meeting.pk, "project_id": project.pk,
    })
    return JsonResponse({
        "ok": True,
        "item_id": item_id,
        "task_id": task.pk,
        "task_label": task.title,
        "task_url": reverse("tasks:detail", kwargs={"task_id": task.pk}),
    })


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_quick_capture(request, project_id: int, meeting_id: int):
    """Cattura rapida durante la riunione: azione, decisione o problema."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    kind = (request.POST.get("kind") or "").strip()
    titolo = (request.POST.get("titolo") or "").strip()
    if not titolo:
        return JsonResponse({"ok": False, "reason": "title_required"}, status=400)

    owner = None
    owner_id = (request.POST.get("owner_id") or "").strip()
    if owner_id:
        try:
            owner = User.objects.get(pk=int(owner_id))
        except (User.DoesNotExist, ValueError):
            owner = None
    due_date = _parse_optional_date(request.POST.get("due_date") or "")

    if kind == "action":
        record = MeetingActionItem.objects.create(
            project=project, source_meeting=meeting, title=titolo[:220],
            assigned_to=owner, due_date=due_date,
            created_by=request.user if request.user.is_authenticated else None,
        )
        label = "Azione"
    elif kind == "issue":
        record = MeetingIssue.objects.create(
            project=project, source_meeting=meeting, title=titolo[:220],
            assigned_to=owner, due_date=due_date,
            created_by=request.user if request.user.is_authenticated else None,
        )
        label = "Problema"
    elif kind == "decision":
        impatto = (request.POST.get("impatto") or "").strip().upper()
        valid = {value for value, _ in MeetingDecisionImpact.choices}
        record = MeetingDecision.objects.create(
            project=project, meeting=meeting, testo=titolo[:400],
            decisa_da=owner,
            impatto=impatto if impatto in valid else MeetingDecisionImpact.MEDIO,
            created_by=request.user if request.user.is_authenticated else None,
        )
        label = "Decisione"
    else:
        return JsonResponse({"ok": False, "reason": "invalid_kind"}, status=400)

    if kind in ("action", "issue"):
        notify_meeting_item_assignment(record, actor=request.user)
    log_action(request, "kickoff_meeting_quick_capture", "tasks", {
        "kind": kind, "record_id": record.pk, "meeting_id": meeting.pk, "project_id": project.pk,
    })
    return JsonResponse({"ok": True, "kind": kind, "label": label, "titolo": titolo, "id": record.pk})


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_agenda_toggle(request, project_id: int, meeting_id: int, item_id: str):
    """Toggle done/undone su un singolo punto agenda dell'incontro."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    row = MeetingAgendaItem.objects.filter(meeting=meeting, item_id=item_id).first()
    if row is None:
        return JsonResponse({"ok": False, "reason": "item_not_found"}, status=404)

    row.done = not row.done
    row.save(update_fields=["done"])
    KickoffMeeting.objects.filter(pk=meeting.pk).update(updated_at=timezone.now())
    return JsonResponse({"ok": True, "done": row.done, "item_id": item_id})


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_task_from_step(request, project_id: int, meeting_id: int):
    """Crea (o aggiorna) un'attivita' kickoff da un punto dell'incontro.

    Con `task_id` valorizzato non nasce un doppione: si aggiorna l'attivita'
    gia' creata - tipicamente per correggerne la data inizio senza uscire
    dall'incontro. L'attrezzatura passa dallo stesso gesto, perche' in
    riunione decidere l'attivita' e decidere l'attrezzo sono una frase sola.
    """
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    existing_task = None
    existing_task_id = (request.POST.get("task_id") or "").strip()
    if existing_task_id:
        try:
            existing_task = project.tasks.get(pk=int(existing_task_id))
        except (Task.DoesNotExist, ValueError):
            return JsonResponse({"ok": False, "reason": "Attivita non trovata in questo kickoff."}, status=404)

    title = (request.POST.get("title") or "").strip()
    if not title and existing_task is None:
        return JsonResponse({"ok": False, "reason": "title_required"}, status=400)

    # Assegnatario (opzionale)
    assigned_to = None
    assigned_to_id = (request.POST.get("assigned_to") or "").strip()
    if assigned_to_id:
        try:
            assigned_to = User.objects.get(pk=int(assigned_to_id))
        except (User.DoesNotExist, ValueError):
            pass

    start_date = _parse_optional_date(request.POST.get("next_step_due") or "")
    due_date = _parse_optional_date(request.POST.get("due_date") or "")
    # Stessa regola di `Task.clean()`: la data fine non precede la data inizio
    # (stesso giorno ammesso). Qui si verifica sul risultato finale, non solo su
    # cio' che arriva nel POST, perche' in aggiornamento una sola delle due puo' cambiare.
    effective_start = start_date or (existing_task.next_step_due if existing_task else None)
    effective_due = due_date or (existing_task.due_date if existing_task else None)
    if effective_start and effective_due and effective_due < effective_start:
        return JsonResponse(
            {"ok": False, "reason": "La data fine non può precedere la data inizio."},
            status=400,
        )

    # Priorita
    priority_raw = (request.POST.get("priority") or "MEDIUM").strip().upper()
    if priority_raw not in (TaskPriority.LOW, TaskPriority.MEDIUM, TaskPriority.HIGH):
        priority_raw = TaskPriority.MEDIUM

    category = None
    category_id = (request.POST.get("category") or "").strip()
    if category_id:
        try:
            category = TaskCategory.objects.get(pk=int(category_id), is_active=True)
        except (TaskCategory.DoesNotExist, ValueError):
            category = None

    if existing_task is not None:
        task = existing_task
        updated_fields: list[str] = []
        assignee_changed = assigned_to is not None and assigned_to.pk != task.assigned_to_id
        if title and titolo_attivita(title) != task.title:
            task.title = titolo_attivita(title)
            updated_fields.append("title")
        if start_date:
            task.next_step_due = start_date
            updated_fields.append("next_step_due")
        if due_date:
            task.due_date = due_date
            updated_fields.append("due_date")
        if assigned_to is not None:
            task.assigned_to = assigned_to
            updated_fields.append("assigned_to")
        if category is not None:
            task.category = category
            updated_fields.append("category")
        if updated_fields:
            task.save(update_fields=[*updated_fields, "updated_at"])
        if assignee_changed:
            notify_task_assignment(task, actor=request.user)
        created = False
    else:
        try:
            task = crea_attivita_da_incontro(
                project=project,
                meeting=meeting,
                user=request.user,
                title=title,
                assigned_to=assigned_to,
                category=category,
                start_date=start_date,
                due_date=due_date,
                priority=priority_raw,
            )
        except KickoffBloccatoVRF:
            return _vrf_blocked_response(project)
        created = True

    tooling_mode = (request.POST.get("tooling_mode") or TaskForm.TOOLING_NONE).strip()
    valid_tooling = {value for value, _ in TaskForm.TOOLING_MODE_CHOICES}
    if tooling_mode in valid_tooling and tooling_mode != TaskForm.TOOLING_NONE:
        tool = None
        tool_id = (request.POST.get("tooling_existing_attrezzatura") or "").strip()
        if tool_id:
            try:
                tool = Attrezzatura.objects.get(pk=int(tool_id))
            except (Attrezzatura.DoesNotExist, ValueError):
                tool = None
        try:
            _apply_task_tooling_action(
                request,
                task,
                mode=tooling_mode,
                existing_attrezzatura=tool,
                part_number=(request.POST.get("tooling_part_number") or "").strip(),
                code=(request.POST.get("tooling_code") or "").strip(),
                description=(request.POST.get("tooling_description") or "").strip(),
            )
        except Exception:
            # L'attivita' e' gia' salvata: un inciampo sull'attrezzatura non
            # deve far sembrare all'utente che non sia stato creato nulla.
            logger.exception("Azione attrezzatura fallita da incontro (task=%s)", task.pk)

    log_action(
        request,
        "kickoff_task_from_step" if created else "kickoff_task_from_step_update",
        "tasks",
        {
            "task_id": task.pk,
            "title": task.title,
            "meeting_id": meeting.pk,
            "meeting_numero": meeting.numero,
            "project_id": project_id,
            "tooling_mode": tooling_mode,
        },
    )

    task_url = reverse("tasks:detail", kwargs={"task_id": task.pk})
    return JsonResponse({
        "ok": True,
        "task_id": task.pk,
        "task_url": task_url,
        "title": task.title,
        "created": created,
        "next_step_due": task.next_step_due.isoformat() if task.next_step_due else "",
        "due_date": task.due_date.isoformat() if task.due_date else "",
    })


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_ai_punti(request, project_id: int, meeting_id: int):
    """Copilota: commesse simili e punti proposti per l'ordine del giorno. Non cambia l'agenda."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return HttpResponseForbidden("Non hai i permessi per preparare questo incontro.")
    from ..ai_kickoff import proponi_punti

    proposta = proponi_punti(project, meeting, user=request.user, scope_queryset=scoped_projects_queryset(request))
    log_action(request, "kickoff_ai_punti", "tasks", {
        "meeting_id": meeting.pk, "simili": len(proposta["simili"]), "punti": len(proposta["punti"]),
        "ai_disponibile": proposta["ai_disponibile"],
    })
    return render(request, "tasks/_meeting_ai_punti.html", {"p": proposta, "project": project, "meeting": meeting})


@require_POST
@task_permissions_required("tasks_create")
def project_meeting_agenda_item_add(request, project_id: int, meeting_id: int):
    """Aggiunge un punto all'ordine del giorno mentre l'incontro e' in corso.

    Serve sia in conduzione sia in registrazione dell'esito: i punti nati in
    riunione finivano finora nelle note libere, fuori dall'agenda e quindi
    fuori da spunte, tempi e minuta.
    """
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting, pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    titolo = (request.POST.get("titolo") or "").strip()
    if not titolo:
        return JsonResponse({"ok": False, "reason": "title_required"}, status=400)

    responsabile = None
    responsabile_id = (request.POST.get("responsabile_id") or "").strip()
    if responsabile_id:
        try:
            responsabile = User.objects.get(pk=int(responsabile_id))
        except (User.DoesNotExist, ValueError):
            responsabile = None

    try:
        durata = int(request.POST.get("durata_minuti") or 0)
    except (TypeError, ValueError):
        durata = 0
    if durata <= 0 or durata > 480:
        durata = None

    responsabile_label = ""
    if responsabile:
        responsabile_label = (responsabile.get_full_name() or responsabile.username)[:150]

    item = {
        "id": uuid.uuid4().hex,
        "titolo": titolo[:200],
        "nota": (request.POST.get("nota") or "").strip()[:1000],
        "task_id": None,
        "task_label": "",
        "issue_id": None,
        "action_id": None,
        # Marcatura d'origine: nella minuta un punto aperto in riunione resta
        # distinguibile da uno convocato; «ai» = proposto dal copilota e aggiunto da chi gestisce.
        "source": "ai" if request.POST.get("source") == "ai" else "live",
        "locked": False,
        "responsabile_id": responsabile.pk if responsabile else None,
        "responsabile_label": responsabile_label,
        "durata_minuti": durata,
        "tempo_effettivo_minuti": None,
        "custom_fields": [],
        "done": False,
    }

    items = [entry for entry in (meeting.agenda_items or []) if isinstance(entry, dict)]
    items.append(item)
    meeting.agenda_items = items
    meeting.save(update_fields=["agenda_items", "updated_at"])

    log_action(
        request, "kickoff_meeting_agenda_item_add", "tasks",
        {"meeting_id": meeting.pk, "project_id": project_id, "titolo": item["titolo"]},
    )
    return JsonResponse({"ok": True, "item": item, "position": len(items)})
