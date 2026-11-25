"""Centro 'Da gestire' KICK-OFF (portfolio/PM): aggrega segnali azionabili.

Solo lettura + navigazione. Ogni sezione e' difensiva (un errore non rompe
il resto). Riusa tasks/readiness.py.
"""
from __future__ import annotations

from datetime import date, timedelta

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
    from .models import Project
    from .access import scoped_projects_queryset

    qs = scoped_projects_queryset(request)
    if scope == "mine":
        u = request.user
        qs = qs.filter(Q(created_by=u) | Project.team_q(u)).distinct()
    return qs


def _tasks_qs(request, scope):
    from .access import scoped_tasks_queryset

    qs = scoped_tasks_queryset(request)
    if scope == "mine":
        u = request.user
        qs = qs.filter(Q(created_by=u) | Q(assigned_to=u) | Q(subscribers=u)).distinct()
    return qs


# Nomi brevi dei criteri di prontezza, come etichette sulla riga della commessa.
_MANCA = {"vrf": "VRF", "meeting": "Incontro kickoff", "team": "Team", "plan": "Piano attività"}


def _sec_commesse(request, scope):
    """Una riga per commessa non pronta, con quello che manca come etichette.

    Prima c'erano due sezioni («VRF da compilare» e «Commesse non pronte») che
    elencavano le stesse commesse; il VRF da compilare è una delle etichette.
    """
    from .readiness import annotate_readiness_qs, compute_project_readiness

    items = []
    for p in annotate_readiness_qs(_projects_qs(request, scope)).order_by("name"):
        r = compute_project_readiness(p)
        if r.level not in ("notready", "partial"):
            continue
        mancano = [c for c in r.criteria if not c.ok]
        primo = next((c.action_url for c in mancano if c.action_url), None)
        items.append({
            "label": p.name,
            "url": primo or _url("tasks:project_overview", p.id),
            "meta": f"{r.met}/{r.total}",
            "tags": [_MANCA.get(c.key, c.label) for c in mancano],
        })
        if len(items) >= _TOP:
            break
    return {
        "key": "commesse", "label": "Commesse da completare", "tone": "danger", "icon": "🚦",
        "items": items, "all_url": _url("tasks:project_list"),
        "empty": "Tutte le commesse sono pronte.",
    }


def _sec_critical_tasks(request, scope):
    from .models import TaskStatus

    today = timezone.localdate()
    now = timezone.now()
    open_statuses = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
    base = _tasks_qs(request, scope).filter(status__in=open_statuses).select_related("project")

    items, seen = [], set()

    def add(qs, reason):
        for t in qs[:_TOP]:
            if t.id in seen:
                continue
            seen.add(t.id)
            items.append({
                "label": t.title, "url": _url("tasks:detail", t.id), "meta": reason,
                "gruppo": t.project.name if t.project_id else "Senza commessa",
            })

    add(base.filter(due_date__lt=today).order_by("due_date"), "Scaduta")
    add(base.filter(assigned_to__isnull=True).order_by("-updated_at"), "Non assegnata")
    add(base.filter(due_date__isnull=True).order_by("-updated_at"), "Senza data fine")
    add(
        base.filter(
            status=TaskStatus.IN_PROGRESS, updated_at__lt=now - timedelta(days=7)
        ).order_by("updated_at"),
        "Ferma >7gg",
    )
    # Raggruppate per commessa (l'ordine dei motivi resta dentro ogni commessa).
    items = items[:_TOP]
    ordine = {}
    for it in items:
        ordine.setdefault(it["gruppo"], len(ordine))
    items.sort(key=lambda it: ordine[it["gruppo"]])
    return {
        "key": "critical", "label": "Attività critiche", "tone": "warning", "icon": "⏰",
        "items": items, "all_url": _url("tasks:list"),
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


def _sec_meeting_items(request, scope):
    """Azioni e problemi d'incontro aperti: a me («i miei») o di tutto il portfolio."""
    from .models import MeetingActionItem, MeetingActionStatus, MeetingIssue, MeetingIssueStatus

    today = timezone.localdate()
    project_ids = _projects_qs(request, "portfolio").values("id")
    filters = {"project_id__in": project_ids}
    if scope == "mine":
        filters["assigned_to"] = request.user
    rows = []
    for model, status, kind in (
        (MeetingActionItem, MeetingActionStatus.OPEN, "Attività d'incontro"),
        (MeetingIssue, MeetingIssueStatus.OPEN, "Problema"),
    ):
        for item in model.objects.filter(status=status, **filters).select_related("project", "assigned_to"):
            owner = item.assigned_to.get_full_name() or item.assigned_to.username if item.assigned_to_id else "senza responsabile"
            if item.due_date and item.due_date < today:
                meta = f"{kind} scaduta il {item.due_date:%d/%m/%Y} · {owner}"
            elif item.due_date:
                meta = f"{kind} entro il {item.due_date:%d/%m/%Y} · {owner}"
            else:
                meta = f"{kind} senza scadenza · {owner}"
            rows.append((item.due_date or date.max, {
                "label": f"{item.title} [{item.project.name}]",
                "url": _url("tasks:project_actions", item.project_id),
                "meta": meta,
            }))
    rows.sort(key=lambda pair: pair[0])
    return {
        "key": "meeting_items",
        "label": "Attività d'incontro e problemi assegnati a me" if scope == "mine" else "Attività d'incontro e problemi aperti",
        "tone": "warning", "icon": "✅",
        "items": [row for _due, row in rows[:_TOP]],
        "all_url": _url("tasks:mie_azioni") if scope == "mine" else None,
        "empty": "Nessuna attività d'incontro o problema aperto.",
    }


def build_kickoff_da_gestire(request, scope: str) -> dict:
    scope = "mine" if scope == "mine" else "portfolio"
    builders = (_sec_meeting_items, _sec_commesse, _sec_critical_tasks, _sec_meetings_open_issues)
    sections = []
    for b in builders:
        try:
            sections.append(b(request, scope))
        except Exception:
            continue
    total = sum(len(s["items"]) for s in sections)
    return {"sections": sections, "total": total, "scope": scope}
