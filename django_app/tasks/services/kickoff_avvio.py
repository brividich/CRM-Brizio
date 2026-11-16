"""Righe «chi fa cosa» del nuovo kickoff.

Prima il kickoff partiva con una mail scritta a mano (prima o dopo l'incontro)
che diceva chi doveva fare cosa. Ora quella mail non serve: le righe scritte nel
form diventano attività vere del kickoff, con responsabile e scadenza facoltativi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from ..models import Task, TaskPriority, TaskStatus

logger = logging.getLogger(__name__)

MAX_RIGHE = 40


@dataclass
class RigaAttivita:
    titolo: str
    responsabile: object | None = None
    scadenza: date | None = None


def righe_dal_post(post) -> list[RigaAttivita]:
    """Legge le righe «attività» del form (titolo, responsabile, scadenza).

    Le righe senza titolo si saltano; responsabile e scadenza sono facoltativi
    (la scadenza spesso non si sa ancora). Un responsabile non attivo o una
    data non valida si ignorano invece di bloccare il salvataggio.
    """
    from ..forms import task_active_users_queryset
    from .meeting_tasks import titolo_attivita

    titoli = post.getlist("att_titolo")
    resp = post.getlist("att_resp")
    scad = post.getlist("att_scadenza")
    ids = {int(v) for v in resp if (v or "").strip().isdigit()}
    utenti = {u.pk: u for u in task_active_users_queryset().filter(pk__in=ids)} if ids else {}
    righe = []
    for i, raw in enumerate(titoli[:MAX_RIGHE]):
        titolo = titolo_attivita(raw)
        if not titolo:
            continue
        r = (resp[i] if i < len(resp) else "").strip()
        s = (scad[i] if i < len(scad) else "").strip()
        try:
            scadenza = date.fromisoformat(s) if s else None
        except ValueError:
            scadenza = None
        righe.append(RigaAttivita(titolo, utenti.get(int(r)) if r.isdigit() else None, scadenza))
    return righe


def crea_attivita(project, righe: list[RigaAttivita], user) -> list[Task]:
    """Crea le attività del kickoff. Gli avvisi li manda `notifica_assegnazioni`."""
    tasks = []
    for riga in righe:
        tasks.append(Task.objects.create(
            title=riga.titolo,
            project=project,
            assigned_to=riga.responsabile,
            due_date=riga.scadenza,
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.TODO,
            created_by=user,
        ))
    return tasks


def _nome(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.get_username() or "").strip()


def notifica_assegnazioni(tasks, *, actor) -> None:
    """Ogni responsabile riceve l'avviso standard di assegnazione del modulo."""
    from .meeting_tasks import notify_task_assignment

    for task in tasks:
        notify_task_assignment(task, actor=actor)


def agenda_da_attivita(project, selezione: str) -> tuple[list[dict], list[int]]:
    """Punti ODG «da confermare» per le attività già pianificate.

    ``selezione``: «aperte» (tutte le attività aperte) o id separati da virgola
    (quelle appena scritte in «Pianifica attività»). Restituisce i punti e i
    responsabili, da aggiungere ai convocati.
    """
    qs = project.tasks.exclude(status__in=[TaskStatus.CANCELED, TaskStatus.DONE]).select_related("assigned_to")
    if selezione != "aperte":
        ids = [int(v) for v in (selezione or "").split(",") if v.strip().isdigit()]
        if not ids:
            return [], []
        qs = qs.filter(pk__in=ids)
    punti, responsabili = [], []
    for task in qs.order_by("id"):
        custom = []
        if task.due_date:
            custom.append({"label": "Entro il", "value": task.due_date.strftime("%d-%m-%Y")})
        punti.append({
            "id": f"attivita-{task.pk}",
            "titolo": task.title,
            "nota": "Attività pianificata: da confermare in riunione.",
            "task_id": task.pk,
            "task_label": task.title,
            "source": "attivita",
            "responsabile_id": task.assigned_to_id,
            "responsabile_label": _nome(task.assigned_to),
            "custom_fields": custom,
            "done": False,
        })
        if task.assigned_to_id and task.assigned_to_id not in responsabili:
            responsabili.append(task.assigned_to_id)
    return punti, responsabili


def segni_attivita(items) -> list[tuple[bool, str]]:
    """Per ogni punto ODG (in ordine): (diventa attività, scadenza).

    Va letto PRIMA di salvare l'incontro: il salvataggio riscrive i punti
    sulle righe dell'ordine del giorno, che non conservano questi segni.
    """
    return [(bool(i.get("crea_attivita")) and not i.get("task_id"), i.get("scadenza") or "") for i in (items or [])]


def crea_attivita_dai_punti(meeting, user, segni) -> tuple[int, bool]:
    """Punti ODG segnati «diventa attività»: nasce l'attività, il punto la collega.

    ``segni`` viene da `segni_attivita` (stesso ordine dei punti salvati).
    Restituisce (attività create, bloccato_vrf).
    """
    from ..forms import task_active_users_queryset
    from .meeting_tasks import KickoffBloccatoVRF, crea_attivita_da_incontro

    if not any(crea for crea, _ in segni or []):
        return 0, False
    items = list(meeting.agenda_items or [])
    ids = {i.get("responsabile_id") for i in items if i.get("responsabile_id")}
    utenti = {u.pk: u for u in task_active_users_queryset().filter(pk__in=ids)} if ids else {}
    create, bloccato = 0, False
    for item, (crea, scad) in zip(items, segni, strict=False):
        if not crea or item.get("task_id"):
            continue
        try:
            scadenza = date.fromisoformat(scad) if scad else None
        except ValueError:
            scadenza = None
        try:
            task = crea_attivita_da_incontro(
                project=meeting.project, meeting=meeting, user=user, title=item.get("titolo", ""),
                assigned_to=utenti.get(item.get("responsabile_id")), due_date=scadenza,
                nota=item.get("nota", ""),
            )
        except KickoffBloccatoVRF:
            bloccato = True
            break
        except ValueError:
            continue
        item["task_id"] = task.pk
        item["task_label"] = task.title
        create += 1
    if create:
        meeting.agenda_items = items
        meeting.save()
    return create, bloccato
