"""Prontezza all'avvio (readiness) di una commessa KICK-OFF.

Gate a 4 criteri calcolato al volo dai dati esistenti (nessun campo persistente,
nessuna migrazione). Fonte di verita' unica del calcolo.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Exists, OuterRef
from django.urls import reverse


@dataclass(frozen=True)
class ReadinessCriterion:
    key: str
    label: str
    ok: bool
    action_url: str | None


@dataclass(frozen=True)
class ReadinessResult:
    criteria: list
    met: int
    total: int
    level: str
    label: str


_LEVEL_LABELS = {"ready": "Pronto", "partial": "Quasi pronto", "notready": "Non pronto"}


def _level_for(met: int) -> str:
    if met >= 4:
        return "ready"
    if met >= 2:
        return "partial"
    return "notready"


def _has_meeting(project) -> bool:
    """Vero solo se un incontro e' stato effettivamente SVOLTO.

    Il criterio si chiama «Incontro kickoff fatto»: prima contava anche un
    incontro semplicemente pianificato per il mese prossimo, quindi bastava
    programmarlo per far risultare la commessa pronta.
    """
    anno = getattr(project, "rd_has_meeting", None)
    if anno is not None:
        return bool(anno)
    from .models import MeetingStatus

    return project.meetings.filter(stato=MeetingStatus.SVOLTO).exists()


def _has_any_meeting(project) -> bool:
    """Vero se esiste un incontro in qualsiasi stato (serve solo per la CTA)."""
    anno = getattr(project, "rd_has_any_meeting", None)
    if anno is not None:
        return bool(anno)
    return project.meetings.exists()


def _has_planned_task(project) -> bool:
    anno = getattr(project, "rd_has_planned", None)
    if anno is not None:
        return bool(anno)
    return project.tasks.filter(due_date__isnull=False).exists()


def _meeting_action_url(project, pid: int) -> str:
    """Se un incontro esiste gia' ma non e' svolto, la CTA porta alla lista
    (dove si registra l'esito), non alla creazione di un doppione."""
    if _has_any_meeting(project):
        return reverse("tasks:project_meetings", args=[pid])
    return reverse("tasks:project_meeting_create", args=[pid])


def compute_project_readiness(project) -> ReadinessResult:
    from .models import VRFDocStatus

    pid = project.id
    vrf_ok = project.vrf_status in (VRFDocStatus.UPLOADED, VRFDocStatus.NOT_REQUIRED)
    meeting_ok = _has_meeting(project)
    team_ok = bool(
        project.project_manager_id and project.capo_commessa_id and project.programmer_id
    )
    plan_ok = _has_planned_task(project)

    criteria = [
        ReadinessCriterion(
            "vrf", "VRF a posto", vrf_ok,
            None if vrf_ok else reverse("tasks:project_vrf_upload", args=[pid]),
        ),
        ReadinessCriterion(
            "meeting", "Incontro kickoff fatto", meeting_ok,
            None if meeting_ok else _meeting_action_url(project, pid),
        ),
        ReadinessCriterion("team", "Team assegnato", team_ok, None),
        ReadinessCriterion(
            "plan", "Piano attività definito", plan_ok,
            None if plan_ok else f"{reverse('tasks:create')}?project={pid}",
        ),
    ]
    met = sum(1 for c in criteria if c.ok)
    level = _level_for(met)
    return ReadinessResult(
        criteria=criteria, met=met, total=4, level=level, label=_LEVEL_LABELS[level]
    )


def annotate_readiness_qs(qs):
    from .models import KickoffMeeting, MeetingStatus, Task

    return qs.annotate(
        rd_has_meeting=Exists(
            KickoffMeeting.objects.filter(
                project=OuterRef("pk"), stato=MeetingStatus.SVOLTO
            )
        ),
        rd_has_any_meeting=Exists(KickoffMeeting.objects.filter(project=OuterRef("pk"))),
        rd_has_planned=Exists(
            Task.objects.filter(project=OuterRef("pk"), due_date__isnull=False)
        ),
    )


def readiness_summary(projects) -> dict:
    counts = {"ready": 0, "partial": 0, "notready": 0}
    for p in projects:
        counts[compute_project_readiness(p).level] += 1
    return counts
