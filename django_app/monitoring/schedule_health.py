"""Salute degli schedule django-q: non solo «registrato», ma «sta girando davvero?».

Per ogni schedule definito in ``automazioni/schedules.py``:
- **registrato** e **abilitato** (ScheduleControl);
- **ultimo run** dai Task di django-q (stessa funzione): quando, riuscito o fallito, con l'errore;
- **in ritardo**: il prossimo run previsto è passato da più di una tolleranza → il cluster
  (``qcluster``) non sta eseguendo. È il segnale più importante: tutti in ritardo = cluster fermo.

Solo letture: la pagina non accoda e non registra nulla.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

STATUS_OK = "ok"
STATUS_LATE = "in_ritardo"
STATUS_FAILED = "errore"
STATUS_MISSING = "non_registrato"
STATUS_DISABLED = "disabilitato"
STATUS_WAITING = "mai_eseguito"
STATUS_LABELS = {
    STATUS_OK: "In regola",
    STATUS_LATE: "In ritardo",
    STATUS_FAILED: "Ultimo run fallito",
    STATUS_MISSING: "Non registrato",
    STATUS_DISABLED: "Disabilitato",
    STATUS_WAITING: "Mai eseguito",
}
SEVERITY = {STATUS_MISSING: 3, STATUS_LATE: 3, STATUS_FAILED: 2, STATUS_WAITING: 1, STATUS_OK: 0, STATUS_DISABLED: 0}


def cadence_label(spec) -> str:
    kind = spec.get("schedule_type")
    if kind == "C":
        return f"cron {spec.get('cron')}"
    if kind == "I":
        minutes = spec.get("minutes") or 0
        return f"ogni {minutes} min" if minutes < 60 else f"ogni {minutes // 60} h"
    return {"H": "ogni ora", "D": "ogni giorno", "W": "ogni settimana", "M": "ogni mese", "Q": "ogni trimestre", "Y": "ogni anno",
            "O": "una volta"}.get(kind, kind or "—")


def tolerance(spec) -> timedelta:
    """Quanto può essere passato il prossimo run prima di dire «in ritardo»: metà cadenza, almeno 10 minuti."""
    kind = spec.get("schedule_type")
    if kind == "I":
        return max(timedelta(minutes=10), timedelta(minutes=(spec.get("minutes") or 1)) / 2)
    return {"H": timedelta(minutes=30), "D": timedelta(hours=2), "W": timedelta(hours=6)}.get(kind, timedelta(minutes=30))


def schedule_rows(now=None):
    from django_q.models import Schedule, Task

    from automazioni.schedules import SCHEDULES
    from monitoring.models import ScheduleControl

    now = now or timezone.now()
    live = {s.name: s for s in Schedule.objects.all()}
    controls = {c.name: c.enabled for c in ScheduleControl.objects.all()}
    funcs = {spec["func"] for spec in SCHEDULES}
    last = {}
    for task in Task.objects.filter(func__in=funcs).order_by("func", "-stopped").only("func", "started", "stopped", "success", "result"):
        last.setdefault(task.func, task)
    failures = dict(
        Task.objects.filter(func__in=funcs, success=False, stopped__gte=now - timedelta(hours=24))
        .values_list("func").order_by().annotate(n=Count("id"))
    )
    rows = []
    for spec in SCHEDULES:
        name, func = spec["name"], spec["func"]
        sch = live.get(name)
        task = last.get(func)
        enabled = controls.get(name, True)
        if not enabled:
            status = STATUS_DISABLED
        elif sch is None:
            status = STATUS_MISSING
        elif sch.next_run and sch.next_run < now - tolerance(spec):
            status = STATUS_LATE
        elif task is not None and not task.success:
            status = STATUS_FAILED
        elif task is None:
            status = STATUS_WAITING
        else:
            status = STATUS_OK
        rows.append({
            "name": name,
            "func": func,
            "cadence": cadence_label(spec),
            "enabled": enabled,
            "registered": sch is not None,
            "next_run": getattr(sch, "next_run", None),
            "last_run": getattr(task, "stopped", None),
            "last_success": getattr(task, "success", None),
            "last_error": (str(task.result)[:300] if task is not None and not task.success and task.result is not None else ""),
            "failures_24h": failures.get(func, 0),
            "status": status,
            "status_label": STATUS_LABELS[status],
        })
    rows.sort(key=lambda r: (-SEVERITY[r["status"]], r["name"]))
    return rows


def cluster_status(now=None):
    """Il cluster gira se ha completato un task di recente. Senza task da 20 minuti è probabilmente fermo."""
    from django_q.models import Task

    now = now or timezone.now()
    last = Task.objects.order_by("-stopped").values_list("stopped", flat=True).first()
    alive = bool(last and last >= now - timedelta(minutes=20))
    return {"alive": alive, "last_task": last}


def summary(rows):
    counts = {status: 0 for status in STATUS_LABELS}
    for row in rows:
        counts[row["status"]] += 1
    problems = counts[STATUS_LATE] + counts[STATUS_MISSING] + counts[STATUS_FAILED]
    return {"counts": counts, "problems": problems, "total": len(rows)}

