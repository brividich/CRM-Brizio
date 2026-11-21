"""Linea del tempo compatta di una commessa: una barra per attività, oggi, gli incontri.

È la «striscia» che accompagna le pagine della commessa (pannello attività,
e poi panoramica e scheda attività): non sostituisce il Piano, lo riassume.
Tutto calcolato sul server, in percentuali: la pagina la disegna senza script.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..models import MeetingStatus, TaskStatus

MAX_RIGHE = 40


def striscia_commessa(
    project, oggi: date, *, evidenzia: int | None = None, tasks=None,
) -> dict | None:
    """Dati della striscia, o None se nessuna attività ha una data.

    ``evidenzia`` = id dell'attività da mettere in risalto (scheda attività).
    ``tasks`` = attività della commessa già lette dalla vista (risparmia una query).
    """
    if tasks is None:
        tasks = project.tasks.select_related("assigned_to")
    # Stesso ordine di prima (date vuote in testa, come nel database).
    tasks = sorted(
        (t for t in tasks if t.status != TaskStatus.CANCELED and (t.due_date or t.next_step_due)),
        key=lambda t: (t.next_step_due or date.min, t.due_date or date.min, t.pk),
    )
    if not tasks:
        return None
    inizi = [t.next_step_due or t.due_date for t in tasks]
    fini = [t.due_date or t.next_step_due for t in tasks]
    primo = min(min(inizi), oggi)
    ultimo = max(max(fini), oggi)
    # Settimane intere, da lunedì a domenica, con un margine dopo l'ultima scadenza.
    primo -= timedelta(days=primo.weekday())
    ultimo += timedelta(days=6 - ultimo.weekday())
    giorni = (ultimo - primo).days + 1
    settimane = giorni // 7
    passo = max(1, -(-settimane // 10))  # al più una decina di etichette

    def pos(d: date) -> float:
        return round((d - primo).days / giorni * 100, 2)

    righe = []
    for t, inizio, fine in zip(tasks, inizi, fini, strict=True):
        if fine < inizio:
            inizio = fine
        if t.status == TaskStatus.DONE:
            classe = "is-fatta"
        elif fine < oggi:
            classe = "is-ritardo"
        elif t.status == TaskStatus.IN_PROGRESS:
            classe = "is-corso"
        else:
            classe = ""
        righe.append({
            "task": t,
            "sinistra": pos(inizio),
            "larghezza": max(round(((fine - inizio).days + 1) / giorni * 100, 2), 0.8),
            "classe": classe,
            "evidenziata": t.pk == evidenzia,
        })
    incontri = [
        {"meeting": m, "sinistra": pos(m.data)}
        for m in project.meetings.exclude(stato=MeetingStatus.ANNULLATO).order_by("data")
        if m.data and primo <= m.data <= ultimo
    ]
    return {
        "righe": righe[:MAX_RIGHE],
        "nascoste": max(0, len(righe) - MAX_RIGHE),
        "settimane": [
            {"etichetta": primo + timedelta(days=7 * i), "sinistra": round(i / settimane * 100, 2)}
            for i in range(0, settimane, passo)
        ],
        "oggi": pos(oggi),
        "incontri": incontri,
    }
