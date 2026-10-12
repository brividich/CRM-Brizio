"""Viste dei kickoff/commesse: elenco, creazione, copia, fase, commenti."""
from __future__ import annotations

import logging

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, F, Max, Min, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from ..forms import (
    ProjectCommentForm,
    ProjectKickoffForm,
    task_active_users_queryset,
)
from ..models import (
    KickoffMeeting,
    MeetingStatus,
    Project,
    Task,
    TaskImpostazioni,
    TaskStatus,
)
from ..access import (
    can_manage_project,
    has_task_permission,
    scoped_projects_queryset,
    task_permissions_required,
)
from ..services.notify import (
    notify_user,
    _project_notify_users_queryset,
)
from ._shared import (
    OPEN_STATUSES,
    _tasks_shell_context,
    _vrf_status_detail,
)

logger = logging.getLogger(__name__)


def _copy_project_vrf_file(project: Project, *, clear_part_number: bool = False) -> tuple[bytes | None, str]:
    if not project.vrf_file:
        return None, ""

    import io
    from pathlib import Path

    project.vrf_file.open("rb")
    try:
        file_bytes = project.vrf_file.read()
    finally:
        project.vrf_file.close()

    filename = project.vrf_original_name or Path(project.vrf_file.name).name

    if clear_part_number:
        import openpyxl

        workbook = openpyxl.load_workbook(io.BytesIO(file_bytes))
        try:
            worksheet = workbook["VRF"] if "VRF" in workbook.sheetnames else workbook.active
            worksheet["B3"] = ""
            output = io.BytesIO()
            workbook.save(output)
            file_bytes = output.getvalue()
        finally:
            workbook.close()

    return file_bytes, filename


def _duplicate_kickoff(source_project: Project, *, created_by, clear_part_number: bool = False) -> Project:
    from django.core.files.base import ContentFile

    kickoff = Project.objects.create(
        name="",
        description=source_project.description,
        client_name=source_project.client_name,
        control_method=source_project.control_method,
        part_number="" if clear_part_number else source_project.part_number,
        revisione=source_project.revisione,
        versione=source_project.versione,
        vrf_status=source_project.vrf_status,
        vrf_original_name=source_project.vrf_original_name,
        vrf_uploaded_at=source_project.vrf_uploaded_at,
        vrf_quote_number=source_project.vrf_quote_number,
        vrf_description=source_project.vrf_description,
        vrf_esp=source_project.vrf_esp,
        similar_project=source_project.similar_project,
        similar_work_note=source_project.similar_work_note,
        created_by=created_by,
    )

    # Il team si eredita per intero: ogni ruolo puo' avere piu' persone.
    for field in Project.TEAM_ROLE_FIELDS:
        getattr(kickoff, field).set(getattr(source_project, field).all())

    file_bytes, filename = _copy_project_vrf_file(source_project, clear_part_number=clear_part_number)
    if file_bytes is not None:
        kickoff.vrf_file.save(filename, ContentFile(file_bytes), save=False)
        kickoff.vrf_original_name = filename
        kickoff.save(update_fields=["vrf_file", "vrf_original_name", "updated_at"])

    return kickoff


def _create_first_meeting(project: Project, user) -> KickoffMeeting | None:
    """Crea l'incontro 1 del kickoff appena nato e vi precarica il team.

    Un kickoff senza incontri e' un kickoff che non e' ancora partito: l'incontro
    di avvio e' il passo successivo obbligato, non un extra da ricordarsi. Nasce
    PIANIFICATO con la data di oggi (da correggere nella convocazione) e con PM,
    capo commessa e programmatore gia' fra i partecipanti — sono le persone che
    l'utente ha appena indicato nel form, non un'invenzione.

    Idempotente: se il kickoff ha gia' un incontro non ne crea un secondo.
    """
    if project.meetings.exists():
        return None

    meeting = KickoffMeeting.objects.create(
        project=project,
        data=timezone.localdate(),
        stato=MeetingStatus.PIANIFICATO,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )

    team_ids = set(project.team_user_ids)
    if team_ids:
        # Passa dal queryset degli utenti selezionabili: un membro del team
        # disattivato non deve rientrare dalla finestra come partecipante.
        meeting.partecipanti_utenti.set(
            task_active_users_queryset().filter(pk__in=team_ids)
        )
    return meeting


@task_permissions_required("tasks_view", "tasks_create")
def project_create(request):
    """Crea un nuovo kickoff (Project) con il suo primo incontro.

    Flow: anagrafica kickoff -> salvataggio Project -> creazione incontro 1 ->
    redirect alla sua convocazione. La scheda VRF resta raggiungibile dalle tab
    di commessa, dalla checklist di prontezza e dal centro «Da gestire»: non e'
    piu' il primo passo imposto, perche' il passo che fa partire davvero una
    commessa e' convocare l'incontro di avvio.

    Se l'utente compila P/N + revisione + versione gia' esistenti, il form
    intercetta il duplicato e reindirizza al kickoff gia' presente (li' non c'e'
    nessuna creazione, quindi nessun incontro nuovo).
    """
    projects_qs = scoped_projects_queryset(request)

    if request.method == "POST":
        form = ProjectKickoffForm(request.POST, project_queryset=projects_qs)
        if form.is_valid():
            if form.reused_existing_project is not None:
                reused = form.reused_existing_project
                messages.info(
                    request,
                    f"Kickoff gia' esistente per questo P/N: riutilizzo '{reused.name}'. "
                    "Procedi con la scheda VRF o aggiungi una nuova attivita.",
                )
                log_action(request, "kickoff_reused_on_create", "tasks", {
                    "project_id": reused.id,
                    "part_number": reused.part_number,
                    "message": f"Kickoff #{reused.id} riutilizzato da form Nuovo kickoff",
                })
                return redirect("tasks:project_vrf_compile", project_id=reused.id)

            with transaction.atomic():
                project = form.save(commit=False)
                project.created_by = request.user
                project.save()
                # Il team va scritto prima dell'incontro: i partecipanti di default
                # si leggono dagli elenchi M2M appena salvati.
                form.save_team(project)
                meeting = _create_first_meeting(project, request.user)
            log_action(request, "kickoff_created", "tasks", {
                "project_id": project.id,
                "part_number": project.part_number,
                "client_name": project.client_name,
                "meeting_id": meeting.id if meeting else None,
                "message": f"Nuovo kickoff #{project.id} '{project.name}' creato",
            })
            if meeting is not None:
                messages.success(
                    request,
                    f"Kickoff '{project.name}' creato con il primo incontro. "
                    "Completa data, luogo e partecipanti, poi invia la convocazione. "
                    "La scheda VRF resta da compilare dalle tab della commessa.",
                )
                return redirect(
                    "tasks:project_meeting_edit",
                    project_id=project.id,
                    meeting_id=meeting.id,
                )
            messages.success(
                request,
                f"Kickoff '{project.name}' creato. Compila la scheda VRF per proseguire.",
            )
            return redirect("tasks:project_vrf_compile", project_id=project.id)
    else:
        form = ProjectKickoffForm(project_queryset=projects_qs)

    return render(
        request,
        "tasks/project_create.html",
        {
            **_tasks_shell_context(request, active="projects"),
            "page_title": "Nuovo kickoff",
            "form": form,
            "team_fields": [form[name] for name in ProjectKickoffForm.TEAM_FIELDS],
        },
    )


@task_permissions_required("tasks_view")
def project_list(request):
    today = timezone.localdate()
    projects_base_qs = scoped_projects_queryset(request).order_by()

    # ── Filtri GET ──
    q_text   = (request.GET.get("q") or "").strip()
    q_client = (request.GET.get("client") or "").strip()
    q_vrf    = (request.GET.get("vrf_status") or "").strip()
    q_sort   = request.GET.get("sort") or "name"

    if q_text:
        projects_base_qs = projects_base_qs.filter(
            Q(name__icontains=q_text) | Q(part_number__icontains=q_text) | Q(client_name__icontains=q_text)
        )
    if q_client:
        projects_base_qs = projects_base_qs.filter(client_name__icontains=q_client)

    # earliest_due come sottoquery correlata (Min), non F("tasks__due_date"): un
    # campo non aggregato su una relazione multi-riga forza Django a raggruppare
    # anche gli altri Count() per quel valore, sdoppiando il progetto in una riga
    # per ogni due_date distinta tra i suoi task.
    earliest_due_sq = (
        Task.objects.filter(project=OuterRef("pk"), due_date__isnull=False)
        .order_by()
        .values("project")
        .annotate(v=Min("due_date"))
        .values("v")
    )
    # Data di inizio del kickoff = data del PRIMO incontro. Sottoquery correlata
    # per la stessa ragione di earliest_due: un Min() diretto sulla relazione
    # multi-riga «meetings» sdoppierebbe le righe di progetto.
    first_meeting_sq = (
        KickoffMeeting.objects.filter(project=OuterRef("pk"))
        .exclude(stato=MeetingStatus.ANNULLATO)
        .order_by()
        .values("project")
        .annotate(v=Min("data"))
        .values("v")
    )
    projects_qs = projects_base_qs.annotate(
        data_inizio=Subquery(first_meeting_sq),
        task_done=Count("tasks", filter=Q(tasks__status=TaskStatus.DONE), distinct=True),
        task_overdue=Count(
            "tasks",
            filter=Q(tasks__status__in=OPEN_STATUSES, tasks__due_date__lt=today),
            distinct=True,
        ),
        earliest_due=Subquery(earliest_due_sq),
    )
    from tasks.action_register import annotate_open_action_counts
    from tasks.readiness import annotate_readiness_qs, compute_project_readiness
    projects_qs = annotate_readiness_qs(projects_qs)
    projects_qs = annotate_open_action_counts(projects_qs)

    # Ordinamento
    if q_sort == "due":
        projects_qs = projects_qs.order_by(
            F("earliest_due").asc(nulls_last=True), "name", "id"
        )
    elif q_sort == "progress_desc":
        projects_qs = projects_qs.order_by(
            F("task_done").desc(nulls_last=True), "name", "id"
        )
    elif q_sort == "ral":
        projects_qs = projects_qs.order_by(
            F("task_overdue").desc(nulls_last=True), "name", "id"
        )
    else:
        projects_qs = projects_qs.order_by("name", "id")

    projects = list(projects_qs.distinct())
    cfg = TaskImpostazioni.get_singleton()

    # ── VRF detail, readiness e giorni alla consegna per ciascun progetto ──
    for p in projects:
        p.vrf_detail = _vrf_status_detail(p, cfg)
        p.can_manage = can_manage_project(request, p)
        p.readiness = compute_project_readiness(p)
        p.days_to_delivery = (p.earliest_due - today).days if p.earliest_due else None

    # Filtro VRF applicato lato Python (usa vrf_detail già calcolato)
    if q_vrf:
        projects = [p for p in projects if p.vrf_detail.get("status") == q_vrf]

    # Clienti distinti per il dropdown filtro
    client_choices = sorted(set(
        client_name
        for client_name in scoped_projects_queryset(request).values_list("client_name", flat=True).distinct()
        if client_name
    ))

    from tasks.models import ProjectPhase
    _v = request.GET.get("view")
    view_mode = _v if _v in ("board", "timeline") else "cards"
    board_columns = None
    is_board_editor = has_task_permission(request, "tasks_edit")
    if view_mode == "board":
        by_phase = {key: [] for key, _ in ProjectPhase.choices}
        for p in projects:
            by_phase.get(getattr(p, "phase", ProjectPhase.BOZZA), by_phase[ProjectPhase.BOZZA]).append(p)
        board_columns = [
            {"key": key, "label": label, "projects": by_phase[key]}
            for key, label in ProjectPhase.choices
        ]

    timeline = None
    timeline_undated = []
    if view_mode == "timeline":
        # Min/Max sono gia' importati a livello modulo.
        from django.db.models.functions import Coalesce
        from tasks.timeline import build_portfolio_timeline
        spans = {
            r["id"]: (r["tl_start"], r["tl_end"])
            for r in Project.objects.filter(id__in=[p.id for p in projects]).annotate(
                tl_start=Min(Coalesce("tasks__next_step_due", "tasks__due_date")),
                tl_end=Max("tasks__due_date"),
            ).values("id", "tl_start", "tl_end")
        }
        items = []
        for p in projects:
            s, e = spans.get(p.id, (None, None))
            if s and e:
                items.append({"project": p, "start": s, "end": e, "readiness": getattr(p, "readiness", None)})
            else:
                timeline_undated.append(p)
        timeline = build_portfolio_timeline(items, timezone.localdate())

    return render(
        request,
        "tasks/projects.html",
        {
            **_tasks_shell_context(request, active="projects"),
            "page_title": "Portfolio kickoff",
            "projects": projects,
            "view": view_mode,
            "board_columns": board_columns,
            "is_board_editor": is_board_editor,
            "phase_choices": ProjectPhase.choices,
            "timeline": timeline,
            "timeline_undated": timeline_undated,
            "is_scope_admin": has_task_permission(request, "tasks_admin"),
            "pf_filter_q": q_text,
            "pf_filter_client": q_client,
            "pf_filter_vrf": q_vrf,
            "pf_sort": q_sort,
            "pf_client_choices": client_choices,
        },
    )


@require_POST
@task_permissions_required("tasks_view")
def project_set_phase(request, project_id: int):
    from tasks.models import ProjectPhase

    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not (has_task_permission(request, "tasks_edit") or can_manage_project(request, project)):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    phase = (request.POST.get("phase") or "").strip()
    if phase not in ProjectPhase.values:
        return JsonResponse({"ok": False, "error": "Fase non valida."}, status=400)
    if project.phase != phase:
        project.phase = phase
        project.save(update_fields=["phase", "updated_at"])
    return JsonResponse({"ok": True, "phase": phase, "phase_label": ProjectPhase(phase).label})


@require_POST
@task_permissions_required("tasks_view", "tasks_create")
def copy_project_with_vrf(request, project_id: int):
    source_project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, source_project):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    kickoff = _duplicate_kickoff(source_project, created_by=request.user, clear_part_number=False)
    log_action(
        request,
        "copy_kickoff_vrf",
        "tasks",
        {
            "message": f"Copiato kickoff #{source_project.id} in kickoff #{kickoff.id} con duplicazione VRF.",
            "source_project_id": source_project.id,
            "copied_project_id": kickoff.id,
        },
    )
    messages.success(request, f"Kickoff duplicato correttamente: {kickoff.name}.")
    return redirect("tasks:project_overview", project_id=kickoff.id)


@require_POST
@task_permissions_required("tasks_view", "tasks_create")
def copy_project_with_vrf_without_pn(request, project_id: int):
    source_project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, source_project):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    kickoff = _duplicate_kickoff(source_project, created_by=request.user, clear_part_number=True)
    log_action(
        request,
        "copy_kickoff_vrf_without_pn",
        "tasks",
        {
            "message": (
                f"Copiato kickoff #{source_project.id} in kickoff #{kickoff.id} "
                "svuotando il P/N e la cella B3 del file VRF."
            ),
            "source_project_id": source_project.id,
            "copied_project_id": kickoff.id,
            "without_part_number": True,
        },
    )
    messages.success(request, f"Kickoff duplicato senza P/N: {kickoff.name}.")
    return redirect("tasks:project_overview", project_id=kickoff.id)


@require_POST
@task_permissions_required("tasks_view", "tasks_comment")
def add_project_comment(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    notify_users_qs = _project_notify_users_queryset(project)
    form = ProjectCommentForm(request.POST, user=request.user, notify_user_queryset=notify_users_qs)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.project = project
        comment.author = request.user
        comment.save()
        if comment.target_user_id and comment.target_user_id != request.user.id:
            notify_user(
                comment.target_user,
                f"Nuovo commento nel kickoff '{project.name}'.",
                reverse("tasks:project_gantt", kwargs={"project_id": project.id}),
            )
        messages.success(request, "Commento kickoff aggiunto.")
    else:
        messages.error(request, "Commento kickoff non valido.")
    return_qs = str(request.POST.get("return_qs") or "").strip()
    target_url = reverse("tasks:project_gantt", kwargs={"project_id": project.id})
    if return_qs:
        target_url = f"{target_url}?{return_qs}"
    return redirect(target_url)
