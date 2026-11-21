"""Elenco unico delle attività: stesse righe, colonne e controlli in tre pagine.

Scheda «Attività» della commessa, «Le mie attività KICK-OFF» e la dashboard
mostravano le attività con colonne e azioni diverse. Qui ogni pagina converte
le sue voci in righe con la stessa forma, che il partial
``tasks/_elenco_attivita.html`` disegna sempre allo stesso modo:

- titolo con l'origine (attività, attività d'incontro, problema, programma…),
  la nota e il collegamento («↳ dopo …»);
- responsabile, scadenza e stato, modificabili sul posto da chi può
  (decide il server: ``task_azione_rapida`` e ``mia_voce_stato``);
- raggruppamento per stato o per responsabile e paginazione.
"""
from __future__ import annotations

from datetime import date

from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone

from ..models import TaskDependency, TaskStatus

PER_PAGINA = 40

STATI_ATTIVITA = [
    (TaskStatus.TODO, "Da fare", "reopen"),
    (TaskStatus.IN_PROGRESS, "In corso", "start"),
    (TaskStatus.DONE, "Completata", "done"),
]

ORIGINI = {
    "task": ("Attività", "info"),
    "action": ("Attività d'incontro", "info"),
    "azione": ("Attività d'incontro", "info"),
    "issue": ("Problema", "warn"),
    "problema": ("Problema", "warn"),
    "subtask": ("Sotto-attività", "soft"),
    "programma": ("Programma", "soft"),
}

ORDINE_STATI = ["In ritardo", "In corso", "Da fare", "Aperta", "Completata", "Chiusa", "Annullata"]


def _nome(user) -> str:
    if not user:
        return ""
    return (user.get_full_name() or user.get_username()).strip()


def nota_breve(task) -> str:
    from .kickoff_avvio import nota_attivita

    return nota_attivita(task)


def stato_etichetta(*, aperta: bool, in_ritardo: bool, task=None) -> str:
    if in_ritardo:
        return "In ritardo"
    if task is not None:
        return {
            TaskStatus.TODO: "Da fare", TaskStatus.IN_PROGRESS: "In corso",
            TaskStatus.DONE: "Completata", TaskStatus.CANCELED: "Annullata",
        }.get(task.status, task.get_status_display())
    return "Aperta" if aperta else "Chiusa"


def riga(
    *, origine: str, titolo: str, url: str, responsabile: str = "", responsabile_id=None,
    scadenza: date | None = None, aperta: bool = True, in_ritardo: bool = False, sotto: str = "",
    progetto=None, task=None, puo: bool = False, puo_nota: bool = False, azione_stato=None,
    etichetta_origine: str = "",
) -> dict:
    """Una riga dell'elenco. ``task`` c'è solo per le attività del piano."""
    etichetta, chip = ORIGINI.get(origine, (origine, "soft"))
    return {
        "origine": origine,
        "etichetta_origine": etichetta_origine or etichetta,
        "chip": chip,
        "titolo": titolo,
        "url": url,
        "sotto": sotto,
        "progetto": progetto,
        "responsabile": responsabile,
        "responsabile_id": responsabile_id,
        "scadenza": scadenza,
        "aperta": aperta,
        "in_ritardo": in_ritardo,
        "stato": stato_etichetta(aperta=aperta, in_ritardo=in_ritardo, task=task),
        "task": task,
        "puo": puo,
        "puo_nota": puo_nota,
        "nota": nota_breve(task) if task is not None else "",
        "dopo": [],
        "azione_stato": azione_stato,
        "chiede": False,
    }


def _sposta_subito(request, task) -> bool:
    """Chi sposta subito le date dipende solo dalla commessa: una volta per commessa e richiesta."""
    from ..access import puo_spostare_subito

    cache = request.__dict__.setdefault("_ka_sposta_subito", {})
    if task.project_id not in cache:
        cache[task.project_id] = puo_spostare_subito(request, task)
    return cache[task.project_id]


def riga_da_task(task, *, request, today=None, puo_gestire=None, sotto: str = "", progetto=True) -> dict:
    """Riga di un'attività del piano, con i permessi della persona che guarda."""
    from ..access import can_manage_task

    today = today or timezone.localdate()
    aperta = task.status in (TaskStatus.TODO, TaskStatus.IN_PROGRESS)
    gestisce = can_manage_task(request, task) if puo_gestire is None else puo_gestire
    incaricato = bool(task.assigned_to_id) and task.assigned_to_id == getattr(request.user, "id", None)
    puo = task.status != TaskStatus.CANCELED and (gestisce or incaricato)
    dati = riga(
        origine="task",
        titolo=task.title,
        url=reverse("tasks:detail", args=[task.pk]),
        responsabile=_nome(task.assigned_to),
        responsabile_id=task.assigned_to_id,
        scadenza=task.due_date,
        aperta=aperta,
        in_ritardo=bool(aperta and task.due_date and task.due_date < today),
        sotto=sotto,
        progetto=task.project if progetto else None,
        task=task,
        puo=puo,
        puo_nota=gestisce,
    )
    # Chi non sposta subito chiede al capocommessa: sotto la data compare il motivo (facoltativo).
    dati["chiede"] = puo and not _sposta_subito(request, task)
    return dati


def aggiungi_collegamenti(righe: list[dict]) -> None:
    """«↳ dopo …»: le attività che ciascuna riga aspetta (una query per tutto l'elenco)."""
    per_task = {r["task"].pk: r for r in righe if r["task"] is not None}
    if not per_task:
        return
    for dep in (
        TaskDependency.objects.filter(successor_id__in=per_task)
        .select_related("predecessor").order_by("predecessor__title")
    ):
        per_task[dep.successor_id]["dopo"].append({"id": dep.pk, "titolo": dep.predecessor.title, "task_id": dep.predecessor_id})


def raggruppa(righe: list[dict], per: str) -> list[dict]:
    """Gruppi {etichetta, righe}: per «stato» o per «responsabile»; altrimenti un gruppo solo."""
    if per not in {"stato", "responsabile"}:
        return [{"etichetta": "", "righe": righe}]
    gruppi: dict[str, list[dict]] = {}
    for r in righe:
        chiave = r["stato"] if per == "stato" else (r["responsabile"] or "Senza responsabile")
        gruppi.setdefault(chiave, []).append(r)
    if per == "stato":
        ordine = sorted(gruppi, key=lambda k: ORDINE_STATI.index(k) if k in ORDINE_STATI else 99)
    else:
        ordine = sorted(gruppi, key=lambda k: (k == "Senza responsabile", k.casefold()))
    return [{"etichetta": k, "righe": gruppi[k]} for k in ordine]


def impagina(request, elementi, per_pagina: int = PER_PAGINA):
    """Pagina richiesta (``?pagina=``) e querystring senza ``pagina`` per i link."""
    pagina = Paginator(elementi, per_pagina).get_page(request.GET.get("pagina"))
    qs = request.GET.copy()
    qs.pop("pagina", None)
    return pagina, qs.urlencode()


def contesto_elenco(request, righe_pagina: list[dict], *, per: str = "", **extra) -> dict:
    """Variabili comuni del partial: gruppi, raggruppamento, stati selezionabili."""
    aggiungi_collegamenti(righe_pagina)
    base = request.GET.copy()
    base.pop("pagina", None)
    base.pop("raggruppa", None)
    return {
        "elenco_gruppi": raggruppa(righe_pagina, per),
        "elenco_raggruppa": per if per in {"stato", "responsabile"} else "",
        # Link «Raggruppa per …»: gli altri filtri restano, si torna alla prima pagina.
        "elenco_qs_base": base.urlencode(),
        "stati_attivita": STATI_ATTIVITA,
        **extra,
    }
