"""Programmi CAM, programmi CMM e FAI di una commessa."""
from __future__ import annotations

from datetime import date

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from ..access import can_manage_project, scoped_projects_queryset, task_permissions_required
from ..models import KickoffMeeting, ProjectTechRef, TechRefKind
from ..services.fai import allinea_da_riga, esito_progetto
from ..services.notify import notify_user
from ..tech_paths import normalizza_percorso
from ._shared import _tasks_shell_context, _utenti_riga_rapida


def _puo_aggiungere(request, project) -> bool:
    return can_manage_project(request, project) or request.user.pk in project.team_user_ids


def _programmatore_id(project):
    """Per CAM e CMM si propone il programmatore, se la commessa ne ha uno solo."""
    programmatori = project.team_members("programmers")
    return programmatori[0].pk if len(programmatori) == 1 else ""


def tech_refs_context(request, project, meeting=None) -> dict:
    gestisce = can_manage_project(request, project)
    righe = [
        {
            "ref": ref,
            "can_edit": gestisce or ref.assigned_to_id == request.user.pk,
            "can_delete": gestisce,
        }
        for ref in project.tech_refs.select_related("assigned_to", "source_meeting", "fai_record__causale", "fai_record__stato")
    ]
    puo_aggiungere = gestisce or request.user.pk in project.team_user_ids
    righe_fai = [r for r in righe if r["ref"].kind == TechRefKind.FAI]
    return {
        "project": project,
        "tech_rows": righe,
        "tech_rows_programmi": [r for r in righe if r["ref"].kind != TechRefKind.FAI],
        "tech_rows_fai": righe_fai,
        "tech_open_count": sum(1 for r in righe if r["ref"].is_open),
        "tech_can_add": puo_aggiungere,
        "tech_show_form": puo_aggiungere or any(r["can_edit"] for r in righe),
        "tech_can_assign": gestisce,
        "tech_kinds": TechRefKind.choices,
        "tech_users": _utenti_riga_rapida(project),
        "tech_default_owner": _programmatore_id(project),
        "tech_meeting": meeting,
        "fai_esito": esito_progetto(project),
        # Se poi qualcuno apre comunque un FAI, vale il FAI.
        "fai_non_richiesto": project.fai_non_richiesto_il is not None and not righe_fai,
        "fai_puo_creare": puo_aggiungere,
        # Il FAI assegnato in riunione si completa, non se ne crea un altro.
        "fai_ref_libera": next((r["ref"] for r in righe_fai if getattr(r["ref"], "fai_record", None) is None), None),
    }


def _risposta(request, project, meeting=None, status: int = 200) -> JsonResponse:
    html = render_to_string("tasks/_tech_refs_body.html", tech_refs_context(request, project, meeting), request=request)
    return JsonResponse({"ok": True, "html": html}, status=status)


def _errore(motivo: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "reason": motivo}, status=status)


def _avvisa(ref, attore) -> None:
    """Chi riceve la voce lo sa subito, senza dover aprire la commessa."""
    assegnato = ref.assigned_to
    if assegnato is None or assegnato.pk == getattr(attore, "pk", None):
        return
    scadenza = f", entro il {ref.due_date:%d/%m/%Y}" if ref.due_date else ""
    url = reverse("tasks:project_tech_refs", args=[ref.project_id])
    notify_user(assegnato, f"Sei responsabile di «{ref.label}» [{ref.project.name}]{scadenza}.", url)


@task_permissions_required("tasks_view")
def project_tech_refs(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    return render(
        request,
        "tasks/project_tech_refs.html",
        {
            **_tasks_shell_context(request, active="tech_refs", project=project),
            **tech_refs_context(request, project),
            "page_title": f"Programmi e FAI - {project.name}",
        },
    )


@require_POST
@task_permissions_required("tasks_view", api=True)
def tech_ref_save(request, project_id: int):
    """Aggiunge una riga o, con ``ref_id``, corregge quella esistente."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    gestisce = can_manage_project(request, project)
    post = request.POST

    meeting = None
    if (post.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(post["meeting_id"]), project=project).first()

    ref = None
    if (post.get("ref_id") or "").isdigit():
        ref = project.tech_refs.filter(pk=int(post["ref_id"])).select_related("assigned_to").first()
        if ref is None:
            return _errore("Riga non trovata in questa commessa.", 404)
        if not (gestisce or ref.assigned_to_id == request.user.pk):
            return _errore("Puoi correggere solo le righe di cui sei responsabile.", 403)
    elif not _puo_aggiungere(request, project):
        return _errore("Solo chi fa parte del team può aggiungere righe.", 403)

    kind = (post.get("kind") or "").strip()
    if kind not in TechRefKind.values:
        return _errore("Scegli il tipo: CAM, CMM o FAI.")
    code = (post.get("code") or "").strip()[:120]
    try:
        path = normalizza_percorso(post.get("path"))
    except ValueError as exc:
        return _errore(str(exc))
    if len(path) > 500:
        return _errore("Il percorso è troppo lungo: massimo 500 caratteri.")

    due_date = None
    testo_data = (post.get("due_date") or "").strip()
    if testo_data:
        try:
            due_date = date.fromisoformat(testo_data)
        except ValueError:
            return _errore("Data non valida.")

    # Chi ha solo la propria riga compila codice e percorso, ma non la passa ad altri.
    if ref is None or gestisce:
        assegnato_id = (post.get("assigned_to") or "").strip()
        assegnato = None
        if assegnato_id:
            from ..forms import task_active_users_queryset

            if not assegnato_id.isdigit():
                return _errore("Responsabile non valido.")
            assegnato = task_active_users_queryset().filter(pk=int(assegnato_id)).first()
            if assegnato is None:
                return _errore("Responsabile non valido.")
    else:
        assegnato = ref.assigned_to

    if not (code or path or assegnato):
        return _errore("Scrivi il codice, il percorso o il responsabile.")

    if ref is not None and kind != TechRefKind.FAI and getattr(ref, "fai_record", None) is not None:
        return _errore("Questa riga ha una scheda FAI: resta di tipo FAI.")

    prima = ref.assigned_to_id if ref else None
    nuova = ref is None
    if nuova:
        ref = ProjectTechRef(project=project, created_by=request.user, source_meeting=meeting)
    ref.kind, ref.code, ref.path, ref.due_date, ref.assigned_to = kind, code, path, due_date, assegnato
    ref.save()
    allinea_da_riga(ref)
    log_action(request, "kickoff_tech_ref_salva", "tasks", {
        "id": ref.pk, "project_id": project.pk, "kind": kind, "nuova": nuova,
    })
    if ref.assigned_to_id != prima:
        _avvisa(ref, request.user)
    return _risposta(request, project, meeting)


@require_POST
@task_permissions_required("tasks_view", api=True)
def fai_non_richiesto(request, project_id: int):
    """Chi gestisce il kickoff segna che qui il FAI non serve, o torna indietro."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return _errore("Solo chi gestisce la commessa può deciderlo.", 403)

    meeting = None
    if (request.POST.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(request.POST["meeting_id"]), project=project).first()

    non_richiesto = request.POST.get("valore") == "1"
    if non_richiesto and project.tech_refs.filter(kind=TechRefKind.FAI).exists():
        return _errore("Questa commessa ha già una riga FAI: eliminala prima.")
    project.fai_non_richiesto_il = timezone.now() if non_richiesto else None
    project.fai_non_richiesto_da = request.user if non_richiesto else None
    project.save(update_fields=["fai_non_richiesto_il", "fai_non_richiesto_da"])
    log_action(request, "kickoff_fai_non_richiesto", "tasks", {
        "project_id": project.pk, "non_richiesto": non_richiesto,
    })
    return _risposta(request, project, meeting)


@require_POST
@task_permissions_required("tasks_view", api=True)
def tech_ref_action(request, project_id: int, ref_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    ref = get_object_or_404(ProjectTechRef, pk=ref_id, project=project)
    gestisce = can_manage_project(request, project)
    azione = (request.POST.get("action") or "").strip()

    meeting = None
    if (request.POST.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(request.POST["meeting_id"]), project=project).first()

    if azione == "delete":
        if not gestisce:
            return _errore("Solo chi gestisce la commessa può eliminare.", 403)
        ref.delete()
    elif azione in ("done", "reopen"):
        if not (gestisce or ref.assigned_to_id == request.user.pk):
            return _errore("Puoi aggiornare solo le righe di cui sei responsabile.", 403)
        if azione == "done":
            ref.mark_done(user=request.user)
        else:
            ref.reopen()
        ref.save(update_fields=["status", "done_by", "done_at", "updated_at"])
        allinea_da_riga(ref)
    else:
        return _errore("Azione non valida.")
    log_action(request, f"kickoff_tech_ref_{azione}", "tasks", {"id": ref_id, "project_id": project.pk})
    return _risposta(request, project, meeting)

