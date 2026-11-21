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


# Chiave in ``Task.extra_data``: l'avviso al responsabile aspetta la minuta di
# questo incontro (id). Senza la chiave l'avviso è già partito, o non serve.
AVVISO_CON_MINUTA = "avviso_con_minuta"


@dataclass
class RigaAttivita:
    titolo: str
    responsabile: object | None = None
    scadenza: date | None = None
    nota: str = ""
    # Va nell'ordine del giorno dell'incontro, da confermare.
    odg: bool = False
    # Chiave della riga nel form e chiave della riga da cui dipende («viene dopo»).
    chiave: str = ""
    dopo: str = ""


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
    # Campi della pagina «Attività e incontro»: assenti nella vecchia pagina a righe.
    note, odg = post.getlist("att_note"), post.getlist("att_odg")
    chiavi, dopo = post.getlist("att_chiave"), post.getlist("att_dopo")

    def _voce(valori, i):
        return (valori[i] if i < len(valori) else "").strip()
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
        righe.append(RigaAttivita(
            titolo, utenti.get(int(r)) if r.isdigit() else None, scadenza,
            nota=_voce(note, i)[:2000], odg=_voce(odg, i) == "1",
            chiave=_voce(chiavi, i)[:40], dopo=_voce(dopo, i)[:40],
        ))
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
            description=riga.nota,
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.TODO,
            created_by=user,
        ))
    return tasks


def collega_attivita(righe: list[RigaAttivita], tasks: list[Task]) -> int:
    """«Viene dopo»: la riga che ne indica un'altra parte quando quella finisce.

    Stesso legame del Gantt (`TaskDependency`, fine → inizio). Una riga che
    indica se stessa o una riga senza titolo viene ignorata; un giro chiuso
    (A dopo B, B dopo A) si ferma al primo legame.
    """
    from ..models import TaskDependency

    per_chiave = {riga.chiave: task for riga, task in zip(righe, tasks, strict=False) if riga.chiave}
    viene_dopo: dict[int, int] = {}
    creati = 0
    for riga, task in zip(righe, tasks, strict=False):
        prima = per_chiave.get(riga.dopo) if riga.dopo else None
        if prima is None or prima.pk == task.pk:
            continue
        # Risale la catena: se da «prima» si torna a questa attività, è un giro.
        cursore, giro = prima.pk, False
        while cursore in viene_dopo:
            cursore = viene_dopo[cursore]
            if cursore == task.pk:
                giro = True
                break
        if giro:
            continue
        TaskDependency.objects.get_or_create(predecessor=prima, successor=task)
        viene_dopo[task.pk] = prima.pk
        creati += 1
    return creati


def nota_attivita(task) -> str:
    """La nota scritta da chi assegna, senza la firma «Dall'incontro #n (data)»."""
    testo = (task.description or "").strip()
    if testo.startswith("Dall'incontro #"):
        _firma, _, resto = testo.partition("\n")
        testo = resto.strip()
    return testo


def rimanda_avviso_alla_minuta(tasks, meeting) -> None:
    """Le attività aspettano la minuta dell'incontro: nessun avviso adesso."""
    for task in tasks:
        task.extra_data = {**(task.extra_data or {}), AVVISO_CON_MINUTA: meeting.pk}
        task.save(update_fields=["extra_data", "updated_at"])


def attivita_dell_incontro(meeting) -> list[Task]:
    """Attività legate all'incontro: punti dell'ordine del giorno, nate in riunione, in attesa della minuta."""
    from .meeting_tasks import meeting_task_marker

    ids = {
        int(item["task_id"]) for item in (meeting.agenda_items or [])
        if isinstance(item, dict) and str(item.get("task_id") or "").isdigit()
    }
    tasks = {
        t.pk: t for t in Task.objects.filter(project_id=meeting.project_id)
        .exclude(status=TaskStatus.CANCELED).select_related("assigned_to").order_by("id")
        if t.pk in ids
        or (t.description or "").startswith(meeting_task_marker(meeting))
        or (t.extra_data or {}).get(AVVISO_CON_MINUTA) == meeting.pk
    }
    return list(tasks.values())


def avvisa_con_la_minuta(meeting, *, actor=None) -> int:
    """La minuta è partita: chi aspettava l'avviso riceve la notifica nel portale.

    Niente seconda mail: le attività stanno già nella minuta (sezione «Attività»).
    """
    from django.urls import reverse

    from .notify import notify_user

    avvisati = 0
    for task in attivita_dell_incontro(meeting):
        dati = dict(task.extra_data or {})
        if dati.pop(AVVISO_CON_MINUTA, None) != meeting.pk:
            continue
        task.extra_data = dati
        task.save(update_fields=["extra_data", "updated_at"])
        assignee = task.assigned_to
        if assignee is None or assignee.pk == getattr(actor, "pk", None):
            continue
        scadenza = f", entro il {task.due_date:%d/%m/%Y}" if task.due_date else ""
        try:
            notify_user(
                assignee,
                f"Ti è stata assegnata l'attività «{task.title}» [{meeting.project.name}]{scadenza}: è nella minuta dell'incontro {meeting.numero}.",
                reverse("tasks:detail", kwargs={"task_id": task.pk}),
            )
            avvisati += 1
        except Exception:
            logger.exception("Notifica attività con minuta fallita (task=%s)", task.pk)
    return avvisati


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
