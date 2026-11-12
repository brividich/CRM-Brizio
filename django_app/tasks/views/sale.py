"""Sale riunioni: disponibilità del giorno nel form dell'incontro e risposta della sala."""
from __future__ import annotations

from datetime import date

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

from ..access import can_manage_project, scoped_projects_queryset, task_permissions_required
from ..models import KickoffMeeting
from ..services import sale as svc


@require_GET
@task_permissions_required("tasks_view", api=True)
def sale_disponibilita(request):
    try:
        giorno = date.fromisoformat((request.GET.get("data") or "").strip())
    except ValueError:
        return JsonResponse({"ok": False, "reason": "Data non valida."}, status=400)
    escludi = request.GET.get("escludi") or ""
    escludi_id = int(escludi) if escludi.isdigit() else None
    if escludi_id and not KickoffMeeting.objects.filter(
        pk=escludi_id, project__in=scoped_projects_queryset(request)
    ).exists():
        escludi_id = None
    organizer = (request.GET.get("organizer") or "").strip() or (request.user.email or "").strip()
    emails: list[str] = []
    ids = [int(x) for x in (request.GET.get("utenti") or "").split(",") if x.strip().isdigit()][:15]
    if ids:
        from ..forms import task_active_users_queryset

        emails += [e for e in task_active_users_queryset().filter(pk__in=ids).values_list("email", flat=True) if e]
    emails += [e.strip() for e in (request.GET.get("esterni") or "").split(",") if "@" in e][:10]
    dati = svc.disponibilita_giorno(giorno, escludi_id=escludi_id, organizer_email=organizer, partecipanti=emails)
    return JsonResponse({"ok": True, **dati})


@require_POST
@task_permissions_required("tasks_view", api=True)
def sala_verifica(request, project_id: int, meeting_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    meeting = get_object_or_404(KickoffMeeting.objects.select_related("sala"), pk=meeting_id, project=project)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "reason": "Solo chi gestisce la commessa può verificarla."}, status=403)
    try:
        etichetta, classe = svc.aggiorna_risposta_sala(meeting)
    except Exception:
        return JsonResponse({"ok": False, "reason": "Outlook non risponde: riprova più tardi."}, status=502)
    log_action(request, "kickoff_sala_verifica", "tasks", {"meeting_id": meeting.pk, "risposta": meeting.sala_risposta})
    return JsonResponse({"ok": True, "label": etichetta, "classe": classe})
