"""Centro 'Da gestire' KICK-OFF (portfolio/PM): aggrega segnali azionabili.

Solo lettura + navigazione. Ogni sezione e' difensiva (un errore non rompe
il resto). Riusa tasks/readiness.py.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

_TOP = 20


def _url(name, *args):
    try:
        return reverse(name, args=args) if args else reverse(name)
    except Exception:
        return ""


def _projects_qs(request, scope):
    from .views import _scoped_projects_queryset

    qs = _scoped_projects_queryset(request)
    if scope == "mine":
        u = request.user
        qs = qs.filter(
            Q(project_manager=u) | Q(capo_commessa=u) | Q(programmer=u) | Q(created_by=u)
        )
    return qs


def _tasks_qs(request, scope):
    from .views import _scoped_tasks_queryset

    qs = _scoped_tasks_queryset(request)
    if scope == "mine":
        u = request.user
        qs = qs.filter(Q(created_by=u) | Q(assigned_to=u) | Q(subscribers=u)).distinct()
    return qs


def _sec_vrf_pending(request, scope):
    from .models import VRFDocStatus

    qs = (
        _projects_qs(request, scope)
        .filter(vrf_status=VRFDocStatus.PENDING)
        .order_by("-updated_at")
    )
    items = [
        {"label": p.name, "url": _url("tasks:project_vrf_upload", p.id), "meta": "VRF da caricare"}
        for p in qs[:_TOP]
    ]
    return {
        "key": "vrf", "label": "VRF da caricare", "tone": "warning", "icon": "\U0001F4C4",
        "items": items, "all_url": _url("tasks:project_list") + "?vrf_status=pending",
        "empty": "Nessun VRF da caricare.",
    }


def _sec_not_ready(request, scope):
    from .readiness import annotate_readiness_qs, compute_project_readiness

    items = []
    for p in annotate_readiness_qs(_projects_qs(request, scope)).order_by("name"):
        r = compute_project_readiness(p)
        if r.level in ("notready", "partial"):
            missing = ", ".join(c.label for c in r.criteria if not c.ok)
            items.append({
                "label": p.name,
                "url": _url("tasks:list") + f"?project={p.id}",
                "meta": f"{r.label} — manca: {missing}",
            })
        if len(items) >= _TOP:
            break
    return {
        "key": "not_ready", "label": "Commesse non pronte", "tone": "danger", "icon": "\U0001F6A6",
        "items": items, "all_url": _url("tasks:project_list"),
        "empty": "Tutte le commesse sono pronte.",
    }


def _sec_critical_tasks(request, scope):
    from .models import TaskStatus

    today = timezone.localdate()
    now = timezone.now()
    open_statuses = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
    base = _tasks_qs(request, scope).filter(status__in=open_statuses)

    items, seen = [], set()

    def add(qs, reason):
        for t in qs[:_TOP]:
            if t.id in seen:
                continue
            seen.add(t.id)
            items.append({"label": t.title, "url": _url("tasks:detail", t.id), "meta": reason})

    add(base.filter(due_date__lt=today).order_by("due_date"), "Scaduta")
    add(base.filter(assigned_to__isnull=True).order_by("-updated_at"), "Non assegnata")
    add(base.filter(due_date__isnull=True).order_by("-updated_at"), "Senza data fine")
    add(
        base.filter(
            status=TaskStatus.IN_PROGRESS, updated_at__lt=now - timedelta(days=7)
        ).order_by("updated_at"),
        "Ferma >7gg",
    )
    return {
        "key": "critical", "label": "Attività critiche", "tone": "warning", "icon": "⏰",
        "items": items[:_TOP], "all_url": _url("tasks:list"),
        "empty": "Nessuna attività critica.",
    }


def _sec_meetings_open_issues(request, scope):
    from .models import KickoffMeeting, MeetingIssueStatus

    project_ids = _projects_qs(request, scope).values_list("id", flat=True)
    qs = (
        KickoffMeeting.objects.filter(project_id__in=project_ids)
        .annotate(
            open_issues=Count(
                "issues_created", filter=Q(issues_created__status=MeetingIssueStatus.OPEN)
            )
        )
        .filter(open_issues__gt=0)
        .order_by("-data")
    )
    items = [
        {
            # `titolo` e' facoltativo: senza fallback la riga compariva senza etichetta.
            "label": (m.titolo or "").strip() or f"Incontro {m.numero}",
            "url": _url("tasks:project_meeting_detail", m.project_id, m.id),
            "meta": f"{m.open_issues} problemi aperti",
        }
        for m in qs[:_TOP]
    ]
    return {
        "key": "meetings", "label": "Incontri da chiudere", "tone": "info", "icon": "\U0001F4CC",
        "items": items, "all_url": None,
        "empty": "Nessun incontro con problemi aperti.",
    }


def build_kickoff_da_gestire(request, scope: str) -> dict:
    scope = "mine" if scope == "mine" else "portfolio"
    builders = (_sec_vrf_pending, _sec_not_ready, _sec_critical_tasks, _sec_meetings_open_issues)
    sections = []
    for b in builders:
        try:
            sections.append(b(request, scope))
        except Exception:
            continue
    total = sum(len(s["items"]) for s in sections)
    return {"sections": sections, "total": total, "scope": scope}
