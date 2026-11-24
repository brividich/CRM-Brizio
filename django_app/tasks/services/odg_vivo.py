"""Punti dell'ordine del giorno legati alle attività, sempre aggiornati.

Un punto nasceva con una fotografia dell'attività («Macchina: da assegnare», «Stato: Da
assegnare») e restava così anche dopo che la macchina era stata scelta. Qui ogni punto che
riporta un'attività, o una tappa del Percorso, si legge al momento:

- titolo della tappa con quello che è stato collegato («Macchine: CNC-744, CNC-512»);
- stato, responsabile, scadenza e collegamenti dell'attività (macchine come operazioni);
- il punto di una tappa senza attività si aggancia da solo alla prima attività della tappa
  appena c'è (anche a un'attività senza tipo che ha già il collegamento che la tappa aspetta);
- in un incontro ancora da fare il punto si segna «Trattato» quando le sue attività sono
  tutte completate. Non torna mai indietro da solo: un punto segnato a mano resta segnato.

Lo usa ``filo_incontro.punti_con_filo``: scheda dell'incontro (fase Prima e dopo) e conduzione.
"""
from __future__ import annotations

import logging

from django.urls import reverse
from django.utils import timezone

from ..models import MeetingAgendaItem, MeetingStatus, Task, TaskStatus

logger = logging.getLogger(__name__)

# Campi fotografati alla nascita del punto: con il dato vivo non servono più.
CAMPI_FOTOGRAFIA = {"Stato", "Responsabile", "Entro il"}
# Nel titolo di una tappa si scrive il codice di quello che è stato collegato.
TIPO_DEL_TITOLO = {
    "MACCHINA": ("macchina", "Macchina", "Macchine"),
    "ATTREZZATURA": ("attrezzatura", "Attrezzatura", "Attrezzature"),
    "UTENSILI": ("utensile", "Utensile", "Utensili"),
    "CAM": ("cam", "Programma CAM", "Programmi CAM"),
    "CMM": ("cmm", "Programma CMM", "Programmi CMM"),
    "FAI": ("fai", "FAI", "FAI"),
}


def _nome(user) -> str:
    return (user.get_full_name() or user.get_username()) if user is not None else ""


def stato_attivita(task: Task) -> tuple[str, str]:
    """(etichetta, tono) dell'attività come la legge chi guarda l'ordine del giorno."""
    if task.status == TaskStatus.DONE:
        return "Completata", "ok"
    if task.status == TaskStatus.CANCELED:
        return "Annullata", ""
    if task.due_date and task.due_date < timezone.localdate():
        return "In ritardo", "danger"
    if task.status == TaskStatus.IN_PROGRESS:
        return "In corso", "info"
    return "Da fare", "warn"


def _vivo(task: Task, voci: list[dict]) -> dict:
    stato, tono = stato_attivita(task)
    return {
        "task": task,
        "url": reverse("tasks:detail", args=[task.pk]),
        "titolo": task.title,
        "stato": stato,
        "tono": tono,
        "chiusa": task.status == TaskStatus.DONE,
        "responsabile": _nome(task.assigned_to) if task.assigned_to_id else "",
        "scadenza": task.due_date,
        "operazioni": [v for v in voci if v["tipo"] == "macchina"],
        "altri": [v for v in voci if v["tipo"] not in ("macchina", "incontro")],
    }


def _titolo_tappa(riga: dict, voci_tappa: list[dict], stato_label: str) -> str:
    tipo, singolare, plurale = TIPO_DEL_TITOLO.get(riga["key"], ("", riga["label"], riga["label"]))
    codici = []
    for v in voci_tappa:
        if v["tipo"] == tipo and not v.get("vuoto") and v["codice"] not in codici:
            codici.append(v["codice"])
    if codici:
        return f"{plurale if len(codici) > 1 else singolare}: {', '.join(codici)}"
    return f"{riga['label']}: {stato_label[0].lower() + stato_label[1:]}" if stato_label else riga["label"]


def _attivita_per_tappa(project, righe: dict) -> dict[str, list[Task]]:
    """Attività di ogni tappa: quelle del tipo della tappa, o in mancanza quelle che hanno già
    il collegamento che la tappa aspetta (un'attività «Attrezzatura di bloccaggio» senza tipo)."""
    from .collegamenti import collegamenti_per_attivita

    esito = {k: [v["task"] for v in r["voci"]] for k, r in righe.items()}
    vuote = [k for k, elenco in esito.items() if not elenco and k in TIPO_DEL_TITOLO]
    if not vuote:
        return esito
    altre = list(
        Task.objects.filter(project=project).exclude(status=TaskStatus.CANCELED)
        .select_related("assigned_to", "category").order_by("id")
    )
    per_task = collegamenti_per_attivita(altre, incontri=False)
    for key in vuote:
        tipo = TIPO_DEL_TITOLO[key][0]
        esito[key] = [t for t in altre if any(v["tipo"] == tipo for v in per_task[t.pk])]
    return esito


def key_tappa(punto: dict) -> str:
    """Chiave della tappa del Percorso per i punti ``tappa:<KEY>``, altrimenti ``""``."""
    source = str(punto.get("source") or "")
    return source[6:] if source.startswith("tappa:") else ""


def arricchisci(meeting, punti: list[dict]) -> list[dict]:
    """Aggiunge a ogni punto ``vivo`` (l'attività com'è ora) e, per le tappe, ``titolo_vivo``.

    Nell'incontro ancora pianificato aggancia le tappe alla loro attività e segna «Trattato»
    i punti con tutte le attività completate (salvato, così lo vedono anche minuta e verbale).
    """
    if not punti:
        return punti
    try:
        return _arricchisci(meeting, punti)
    except Exception:
        # L'ordine del giorno si vede comunque, con i dati del momento in cui è nato.
        logger.exception("Ordine del giorno: dati vivi non letti (incontro=%s)", getattr(meeting, "pk", None))
        return punti


def _arricchisci(meeting, punti: list[dict]) -> list[dict]:
    from .collegamenti import collegamenti_per_attivita
    from .tappe import _stato_tappa, percorso

    project = meeting.project
    pianificato = meeting.stato == MeetingStatus.PIANIFICATO
    tappe = {key_tappa(p) for p in punti if key_tappa(p)}
    righe, per_tappa = {}, {}
    if tappe:
        righe = {r["key"]: r for r in percorso(project)["righe"] if r["key"] in tappe}
        per_tappa = _attivita_per_tappa(project, righe)

    # Un punto scritto a mano con lo stesso titolo di un'attività della commessa è quell'attività.
    liberi = [
        p for p in punti
        if not key_tappa(p) and not p.get("task_id") and not p.get("issue_id") and not p.get("action_id")
    ]
    if liberi and pianificato:
        per_titolo = {}
        for pk, titolo in (
            Task.objects.filter(project=project).exclude(status=TaskStatus.CANCELED).order_by("id").values_list("pk", "title")
        ):
            per_titolo.setdefault(" ".join(titolo.split()).casefold(), pk)
        for p in liberi:
            pk = per_titolo.get(" ".join(str(p.get("titolo") or "").split()).casefold())
            if pk:
                p["task_id"] = pk
                p["_aggancia"] = True

    ids = {int(p["task_id"]) for p in punti if p.get("task_id")}
    for elenco in per_tappa.values():
        ids.update(t.pk for t in elenco)
    attivita = {
        t.pk: t for t in Task.objects.filter(pk__in=ids, project=project).select_related("assigned_to", "category")
    }
    voci = collegamenti_per_attivita(list(attivita.values()), incontri=False)

    agganci, trattati = {}, []
    for p in punti:
        key = key_tappa(p)
        del_punto: list[Task] = []
        if key and key in righe:
            del_punto = [attivita[t.pk] for t in per_tappa.get(key, []) if t.pk in attivita]
            voci_tappa = [v for t in del_punto for v in voci.get(t.pk, [])]
            stato_label = righe[key]["stato_label"]
            if del_punto and righe[key]["stato"] == "vuota":
                stato_label = _stato_tappa(del_punto, False)[1]
            p["titolo_vivo"] = _titolo_tappa(righe[key], voci_tappa, stato_label)
            # Lo stato della tappa è già nel titolo: la fotografia di quando è nato il punto non serve.
            p["custom_fields"] = [f for f in (p.get("custom_fields") or []) if f.get("label") not in CAMPI_FOTOGRAFIA]
            if del_punto and not p.get("task_id"):
                primo = next((t for t in del_punto if t.status != TaskStatus.DONE), del_punto[0])
                p["task_id"], p["task_label"] = primo.pk, primo.title
                agganci[str(p.get("id"))] = primo
        elif p.get("task_id") and int(p["task_id"]) in attivita:
            del_punto = [attivita[int(p["task_id"])]]
        if not p.get("task_id") or int(p["task_id"]) not in attivita:
            continue
        task = attivita[int(p["task_id"])]
        if p.pop("_aggancia", False):
            p["task_label"] = task.title
            agganci[str(p.get("id"))] = task
        p["vivo"] = _vivo(task, voci.get(task.pk, []))
        # Il nome dell'attività accanto al titolo solo se dice qualcosa in più.
        titolo = " ".join(str(p.get("titolo_vivo") or p.get("titolo") or "").split()).casefold()
        p["vivo"]["stesso_titolo"] = titolo == " ".join(task.title.split()).casefold()
        p["custom_fields"] = [f for f in (p.get("custom_fields") or []) if f.get("label") not in CAMPI_FOTOGRAFIA]
        if pianificato and not p.get("done") and del_punto and all(t.status == TaskStatus.DONE for t in del_punto):
            p["done"] = True
            p["trattato_da_solo"] = True
            trattati.append(str(p.get("id")))

    if pianificato and (agganci or trattati):
        _salva(meeting, agganci, trattati)
    return punti


def _salva(meeting, agganci: dict, trattati: list[str]) -> None:
    for item_id, task in agganci.items():
        MeetingAgendaItem.objects.filter(meeting=meeting, item_id=item_id, task__isnull=True).update(
            task=task, task_label=task.title[:200],
        )
    if trattati:
        MeetingAgendaItem.objects.filter(meeting=meeting, item_id__in=trattati, done=False).update(done=True)
    # La cache dell'incontro rilegge le righe alla prossima richiesta.
    meeting.__dict__.pop("_agenda_cache", None)
    meeting.__dict__.pop("_agenda_snapshot", None)


def numeri_dei_punti(righe) -> dict[tuple[int, str], int]:
    """(incontro, id punto) → numero del punto a video (dall'1), per le righe date."""
    meeting_ids = {r.meeting_id for r in righe}
    numeri: dict[tuple[int, str], int] = {}
    contatore: dict[int, int] = {}
    for mid, item_id in (
        MeetingAgendaItem.objects.filter(meeting_id__in=meeting_ids).order_by("meeting_id", "ordine", "id")
        .values_list("meeting_id", "item_id")
    ):
        contatore[mid] = contatore.get(mid, 0) + 1
        numeri[(mid, item_id)] = contatore[mid]
    return numeri
