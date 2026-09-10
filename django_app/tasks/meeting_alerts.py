"""Segnalazioni incontri kickoff per la dashboard KICK-OFF.

Risponde a due domande che la dashboard attivita' non copriva: «quando ho il
prossimo incontro» e «quali incontri stanno aspettando qualcosa da me».

Regole:
- lo scope e' sempre quello ACL delle commesse (`_scoped_projects_queryset`):
  qui non si allarga mai la visibilita', si filtra soltanto;
- il taglio «i miei» e' personale (convocato, presente, creatore o membro del
  team di commessa), non un permesso: chi ha scope ampio puo' vedere tutto;
- le voci «da gestire» che richiedono di scrivere (registrare l'esito,
  approvare la minuta) compaiono solo a chi puo' gestire quella commessa.
"""
from __future__ import annotations

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

_LIMIT = 6


def _url(name, *args) -> str:
    try:
        return reverse(name, args=args)
    except Exception:
        return ""


def _mine_filter(user) -> Q:
    """Incontri «miei»: convocato, presente, creatore o nel team di commessa."""
    from .models import Project

    q = (
        Q(partecipanti_utenti=user)
        | Q(presenti_utenti=user)
        | Q(created_by=user)
        | Q(project__created_by=user)
    )
    for field in Project.TEAM_ROLE_FIELDS:
        q |= Q(**{f"project__{field}": user})
    return q


def _meeting_label(meeting) -> str:
    titolo = (meeting.titolo or "").strip()
    return titolo or f"Incontro {meeting.numero}"


def _row(meeting, *, tone: str, motivo: str, action_url: str = "", action_label: str = "") -> dict:
    return {
        "meeting": meeting,
        "project": meeting.project,
        "label": _meeting_label(meeting),
        "url": _url("tasks:project_meeting_detail", meeting.project_id, meeting.id),
        "action_url": action_url,
        "action_label": action_label,
        "tone": tone,
        "motivo": motivo,
    }


def build_meeting_alerts(request, *, only_mine: bool = True) -> dict:
    """Prossimi incontri + incontri da gestire, nello scope dell'utente."""
    from .models import KickoffMeeting, MeetingIssueStatus, MeetingStatus
    from .views import _can_manage_project, _scoped_projects_queryset

    user = request.user
    today = timezone.localdate()
    projects = _scoped_projects_queryset(request)

    base = KickoffMeeting.objects.filter(project_id__in=projects.values("id")).select_related("project")
    personal = bool(only_mine and getattr(user, "is_authenticated", False))
    if personal:
        base = base.filter(_mine_filter(user))
    base = base.distinct()

    prossimi_qs = (
        base.filter(stato=MeetingStatus.PIANIFICATO, data__gte=today)
        .order_by("data", "ora", "numero")[: _LIMIT]
    )
    prossimi = []
    for meeting in prossimi_qs:
        giorni = (meeting.data - today).days
        if giorni == 0:
            quando = "Oggi"
        elif giorni == 1:
            quando = "Domani"
        else:
            quando = f"Tra {giorni} giorni"
        prossimi.append({
            **_row(meeting, tone="info" if giorni > 1 else "warn", motivo=quando),
            "giorni": giorni,
            "quando": quando,
        })

    # ── Da gestire ────────────────────────────────────────────────────────────
    manage_cache: dict[int, bool] = {}

    def can_manage(project) -> bool:
        if project.id not in manage_cache:
            manage_cache[project.id] = _can_manage_project(request, project)
        return manage_cache[project.id]

    da_gestire: list[dict] = []
    visti: set[int] = set()

    def add(meeting, *, tone, motivo, action_route=None, action_label=""):
        if meeting.id in visti:
            return
        visti.add(meeting.id)
        action_url = (
            _url(action_route, meeting.project_id, meeting.id) if action_route else ""
        )
        da_gestire.append(
            _row(meeting, tone=tone, motivo=motivo, action_url=action_url, action_label=action_label)
        )

    # 1. Incontro passato ancora «pianificato»: l'esito non e' mai stato registrato.
    for meeting in base.filter(stato=MeetingStatus.PIANIFICATO, data__lt=today).order_by("-data")[: _LIMIT]:
        giorni = (today - meeting.data).days
        add(
            meeting,
            tone="danger",
            motivo=f"Esito non registrato da {giorni} giorn{'o' if giorni == 1 else 'i'}",
            action_route="tasks:project_meeting_minutes" if can_manage(meeting.project) else None,
            action_label="Registra esito",
        )

    # 2. Incontro svolto con minuta mai approvata.
    for meeting in base.filter(
        stato=MeetingStatus.SVOLTO, minuta_chiusa_at__isnull=True
    ).order_by("-data")[: _LIMIT]:
        if not can_manage(meeting.project):
            continue
        add(
            meeting,
            tone="warn",
            motivo="Minuta da approvare",
            action_route="tasks:project_meeting_detail",
            action_label="Apri minuta",
        )

    # 3. Incontri con problemi ancora aperti.
    con_problemi = (
        base.annotate(
            aperti=Count(
                "issues_created",
                filter=Q(issues_created__status=MeetingIssueStatus.OPEN),
                distinct=True,
            )
        )
        .filter(aperti__gt=0)
        .order_by("-data")[: _LIMIT]
    )
    for meeting in con_problemi:
        add(
            meeting,
            tone="warn",
            motivo=f"{meeting.aperti} problem{'a' if meeting.aperti == 1 else 'i'} apert{'o' if meeting.aperti == 1 else 'i'}",
        )

    return {
        "prossimi": prossimi,
        "da_gestire": da_gestire[: _LIMIT],
        "da_gestire_total": len(da_gestire),
        "personal": personal,
        "prossimo": prossimi[0] if prossimi else None,
        "has_any": bool(prossimi or da_gestire),
    }
