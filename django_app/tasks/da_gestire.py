"""Centro 'Da gestire' KICK-OFF: una riga per commessa con quello che non va.

Solo lettura + navigazione. Ogni parte è difensiva (un errore non rompe il
resto, ma finisce nel log). Riusa tasks/readiness.py.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


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


# ── Vista semplice (25/11/2026): una riga per commessa ────────────────────
# Prima la pagina aveva quattro sezioni (attività d'incontro e problemi, commesse
# da completare, attività critiche, incontri da chiudere) che ripetevano le
# stesse commesse. Ora una riga per commessa con i conteggi di quello che non va
# e, aperta la riga, l'elenco delle voci. Prima le commesse più urgenti.

_MAX_VOCI = 30


def _riga(per, project):
    r = per.get(project.pk)
    if r is None:
        r = per[project.pk] = {
            "project": project, "url": _url("tasks:project_overview", project.pk),
            "conteggi": {}, "manca": [], "voci": [], "testo": project.name.lower(),
        }
    return r


def _conta(r, chiave):
    r["conteggi"][chiave] = r["conteggi"].get(chiave, 0) + 1


def _voce(r, label, url, meta):
    if len(r["voci"]) < _MAX_VOCI:
        r["voci"].append({"label": label, "url": url, "meta": meta})
    r["testo"] += " " + label.lower()


# (chiave, etichetta singolare, plurale, tono): rosse prima, poi arancio.
_CHIP = (
    ("scadute", "scaduta", "scadute", "danger"),
    ("problemi", "problema aperto", "problemi aperti", "danger"),
    ("non_assegnate", "non assegnata", "non assegnate", "warn"),
    ("senza_data", "senza data", "senza data", "warn"),
    ("ferme", "ferma da più di 7 giorni", "ferme da più di 7 giorni", "warn"),
)
_PESO = {"scadute": 3, "problemi": 3}


def build_da_gestire_per_commessa(request, scope: str) -> dict:
    """Righe per commessa: chip coi conteggi, cosa manca per l'avvio, voci da gestire."""
    from .models import (
        MeetingActionItem, MeetingActionStatus, MeetingIssue, MeetingIssueStatus, TaskStatus,
    )
    from .readiness import annotate_readiness_qs, compute_project_readiness

    scope = "mine" if scope == "mine" else "portfolio"
    oggi = timezone.localdate()
    per: dict[int, dict] = {}

    # Attività del piano: scadute, non assegnate, senza data, ferme.
    try:
        aperte = (
            _tasks_qs(request, scope)
            .filter(status__in=(TaskStatus.TODO, TaskStatus.IN_PROGRESS), project__isnull=False)
            .select_related("project", "assigned_to").order_by("due_date", "id")
        )
        sette_giorni_fa = timezone.now() - timedelta(days=7)
        for t in aperte[:500]:
            motivi = []
            if t.due_date and t.due_date < oggi:
                motivi.append(("scadute", f"Scaduta il {t.due_date:%d/%m/%Y}"))
            if not t.assigned_to_id:
                motivi.append(("non_assegnate", "Non assegnata"))
            if not t.due_date:
                motivi.append(("senza_data", "Senza data fine"))
            if t.status == TaskStatus.IN_PROGRESS and t.updated_at and t.updated_at < sette_giorni_fa:
                motivi.append(("ferme", "Ferma da più di 7 giorni"))
            if not motivi:
                continue
            r = _riga(per, t.project)
            for chiave, _testo in motivi:
                _conta(r, chiave)
            _voce(r, t.title, _url("tasks:detail", t.pk), " · ".join(m for _c, m in motivi))
    except Exception:
        logger.exception("Da gestire: attività del piano non calcolate")

    # Problemi e attività d'incontro aperti (in «Le mie» solo quelli a mio nome).
    try:
        filtri = {"project_id__in": _projects_qs(request, "portfolio").values("id")}
        if scope == "mine":
            filtri["assigned_to"] = request.user
        for model, stato, tipo in (
            (MeetingIssue, MeetingIssueStatus.OPEN, "Problema"),
            (MeetingActionItem, MeetingActionStatus.OPEN, "Attività d'incontro"),
        ):
            for it in model.objects.filter(status=stato, **filtri).select_related("project", "assigned_to"):
                r = _riga(per, it.project)
                scaduta = bool(it.due_date and it.due_date < oggi)
                if model is MeetingIssue:
                    _conta(r, "problemi")
                if scaduta:
                    _conta(r, "scadute")
                chi = (it.assigned_to.get_full_name() or it.assigned_to.username) if it.assigned_to_id else "senza responsabile"
                quando = f"scaduta il {it.due_date:%d/%m/%Y}" if scaduta else (f"entro il {it.due_date:%d/%m/%Y}" if it.due_date else "senza scadenza")
                _voce(r, it.title, _url("tasks:project_actions", it.project_id), f"{tipo} {quando} · {chi}")
    except Exception:
        logger.exception("Da gestire: problemi e attività d'incontro non calcolate")

    # Cosa manca per l'avvio (prontezza): etichette «manca …».
    try:
        for p in annotate_readiness_qs(_projects_qs(request, scope)):
            pr = compute_project_readiness(p)
            if pr.level not in ("notready", "partial"):
                continue
            r = _riga(per, p)
            for c in pr.criteria:
                if not c.ok:
                    r["manca"].append({"testo": _MANCA.get(c.key, c.label), "url": c.action_url})
    except Exception:
        logger.exception("Da gestire: prontezza non calcolate")

    righe = []
    for r in per.values():
        r["chip"] = [
            {"testo": f"{n} {sing if n == 1 else plur}", "tono": tono}
            for chiave, sing, plur, tono in _CHIP
            if (n := r["conteggi"].get(chiave))
        ]
        r["peso"] = sum(n * _PESO.get(k, 1) for k, n in r["conteggi"].items()) + len(r["manca"])
        r["n"] = len(r["voci"]) + len(r["manca"])
        righe.append(r)
    righe.sort(key=lambda r: (-r["peso"], r["project"].name.casefold()))
    return {"righe": righe, "scope": scope}
