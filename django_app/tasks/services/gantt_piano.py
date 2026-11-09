"""Regole del piano Gantt: dipendenze esplicite, ordine delle righe, sovrapposizioni.

Prima il Gantt imponeva una sequenza implicita (ogni attività dopo la fine della
precedente, in ordine di creazione): due attività non potevano mai sovrapporsi.
Ora le attività sono libere e i soli vincoli sono le dipendenze dichiarate.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..models import DependencyType, Task, TaskDependency, TaskStatus

PASSO_ORDINE = 10
_CHIUSE = {TaskStatus.DONE, TaskStatus.CANCELED}


def date_attivita(task: Task) -> tuple[date | None, date | None]:
    """Inizio e fine come le disegna il Gantt (una sola data vale per entrambe)."""
    return task.next_step_due or task.due_date, task.due_date or task.next_step_due


def ordina_piano(tasks) -> list[Task]:
    """Ordine delle righe: quello scelto nel Gantt, poi l'ordine di creazione."""
    return sorted(tasks, key=lambda t: (t.gantt_order or 10**9, t.id))


def prossimo_ordine(project_id: int) -> int:
    ultimo = (
        Task.objects.filter(project_id=project_id)
        .order_by("-gantt_order")
        .values_list("gantt_order", flat=True)
        .first()
    )
    return (ultimo or 0) + PASSO_ORDINE


def sposta_in_ordine(project, task: Task, direzione: str) -> bool:
    """Sposta la riga di un posto (``su``/``giu``) o in cima/in fondo; rinumera il piano."""
    righe = ordina_piano(project.tasks.all())
    ids = [t.id for t in righe]
    if task.id not in ids:
        return False
    i = ids.index(task.id)
    if direzione == "su" and i > 0:
        righe[i - 1], righe[i] = righe[i], righe[i - 1]
    elif direzione == "giu" and i < len(righe) - 1:
        righe[i + 1], righe[i] = righe[i], righe[i + 1]
    elif direzione == "cima" and i > 0:
        righe.insert(0, righe.pop(i))
    elif direzione == "fondo" and i < len(righe) - 1:
        righe.append(righe.pop(i))
    else:
        return False
    da_salvare = []
    for n, t in enumerate(righe, start=1):
        if t.gantt_order != n * PASSO_ORDINE:
            t.gantt_order = n * PASSO_ORDINE
            da_salvare.append(t)
    for t in da_salvare:
        Task.objects.filter(pk=t.pk).update(gantt_order=t.gantt_order)
    return True


def inizio_minimo(task: Task, dipendenze, per_id: dict[int, Task]) -> date | None:
    """Prima data di inizio ammessa dalle dipendenze in cui ``task`` è il successore."""
    inizio, fine = date_attivita(task)
    durata = (fine - inizio).days if inizio and fine else 0
    minimo = None
    for dep in dipendenze:
        if dep.successor_id != task.id:
            continue
        pred = per_id.get(dep.predecessor_id)
        if pred is None or pred.status == TaskStatus.CANCELED:
            continue
        p_inizio, p_fine = date_attivita(pred)
        if not p_inizio:
            continue
        lag = dep.lag_days or 0
        tipo = dep.dependency_type
        if tipo == DependencyType.SS:
            candidato = p_inizio + timedelta(days=lag)
        elif tipo == DependencyType.FF:
            candidato = p_fine + timedelta(days=lag) - timedelta(days=durata)
        elif tipo == DependencyType.SF:
            candidato = p_inizio + timedelta(days=lag) - timedelta(days=durata)
        else:  # FS
            candidato = p_fine + timedelta(days=1 + lag)
        if minimo is None or candidato > minimo:
            minimo = candidato
    return minimo


def crea_ciclo(project, predecessore_id: int, successore_id: int) -> bool:
    """True se la dipendenza predecessore → successore chiuderebbe un giro."""
    archi: dict[int, list[int]] = {}
    for p, s in TaskDependency.objects.filter(predecessor__project=project).values_list(
        "predecessor_id", "successor_id"
    ):
        archi.setdefault(p, []).append(s)
    da_visitare, visti = [successore_id], set()
    while da_visitare:
        nodo = da_visitare.pop()
        if nodo == predecessore_id:
            return True
        if nodo in visti:
            continue
        visti.add(nodo)
        da_visitare.extend(archi.get(nodo, []))
    return False


def propaga_dipendenze(project, task_mosso: Task) -> list[Task]:
    """Spinge in avanti le attività che dipendono da ``task_mosso`` e ora violerebbero il vincolo.

    Solo in avanti: se la precedente si accorcia, le successive non vengono
    tirate indietro (la data l'ha decisa qualcuno). Attività chiuse escluse.
    """
    per_id = {t.id: t for t in Task.objects.filter(project=project)}
    per_id[task_mosso.id] = task_mosso
    dipendenze = list(TaskDependency.objects.filter(predecessor_id__in=per_id, successor_id__in=per_id))
    spostate: dict[int, Task] = {}
    coda = [task_mosso.id]
    passi = 0
    limite = max(10, len(per_id) * len(per_id))
    while coda and passi < limite:
        passi += 1
        corrente = coda.pop(0)
        for dep in dipendenze:
            if dep.predecessor_id != corrente:
                continue
            succ = per_id.get(dep.successor_id)
            if succ is None or succ.status in _CHIUSE:
                continue
            minimo = inizio_minimo(succ, dipendenze, per_id)
            inizio, _fine = date_attivita(succ)
            if not minimo or not inizio or inizio >= minimo:
                continue
            delta = timedelta(days=(minimo - inizio).days)
            if succ.next_step_due:
                succ.next_step_due += delta
            if succ.due_date:
                succ.due_date += delta
            succ.save(update_fields=["next_step_due", "due_date", "updated_at"])
            spostate[succ.id] = succ
            coda.append(succ.id)
    return list(spostate.values())


def sovrapposizioni_per_persona(righe: list[dict]) -> dict[int, list[str]]:
    """Per ogni attività aperta: WBS delle altre attività aperte della stessa persona nello stesso periodo.

    Le sovrapposizioni sono ammesse: servono solo a vedere chi ha troppo insieme.
    """
    aperte = [
        r for r in righe
        if r["task"].assigned_to_id and r["task"].status not in _CHIUSE
    ]
    esito: dict[int, list[str]] = {}
    for a in aperte:
        for b in aperte:
            if a is b or a["task"].assigned_to_id != b["task"].assigned_to_id:
                continue
            if a["active_start"] <= b["active_end"] and b["active_start"] <= a["active_end"]:
                esito.setdefault(a["task"].id, []).append(b["wbs"])
    return esito
