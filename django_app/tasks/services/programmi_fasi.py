"""Fasi di un programma CAM/CMM: un passo per clic, con storico e attività allineata.

Da scrivere → In scrittura → Da provare in macchina → Validato.
«Nuova revisione» riporta un programma validato in scrittura con la lettera successiva.
Validato chiude l'attività collegata; una nuova revisione la riapre.
"""
from __future__ import annotations

from django.db import transaction

from ..models import ProgrammaFase, ProgrammaStorico, TaskExtraRef, TaskStatus, TappaKickoff, TechRefStatus

# azione → (fase di partenza ammesse, fase di arrivo, etichetta del pulsante)
AZIONI = {
    "inizia": ({ProgrammaFase.DA_SCRIVERE}, ProgrammaFase.IN_SCRITTURA, "Inizia a scrivere"),
    "da_provare": ({ProgrammaFase.DA_SCRIVERE, ProgrammaFase.IN_SCRITTURA}, ProgrammaFase.DA_PROVARE, "Pronto da provare"),
    "valida": ({ProgrammaFase.DA_PROVARE, ProgrammaFase.IN_SCRITTURA}, ProgrammaFase.VALIDATO, "Validato in macchina"),
    "torna": ({ProgrammaFase.DA_PROVARE}, ProgrammaFase.IN_SCRITTURA, "Da correggere"),
    "revisione": ({ProgrammaFase.VALIDATO}, ProgrammaFase.IN_SCRITTURA, "Nuova revisione"),
}
CLASSE = {
    ProgrammaFase.DA_SCRIVERE: "warn",
    ProgrammaFase.IN_SCRITTURA: "info",
    ProgrammaFase.DA_PROVARE: "danger",
    ProgrammaFase.VALIDATO: "ok",
}


class PassaggioNonValido(ValueError):
    pass


def azioni_possibili(ref) -> list[tuple[str, str]]:
    """Pulsanti da mostrare: il passo principale per primo."""
    if not ref.is_programma:
        return []
    return [(chiave, etichetta) for chiave, (da, _a, etichetta) in AZIONI.items() if ref.fase in da]


def revisione_successiva(rev: str) -> str:
    rev = (rev or "").strip().upper()
    if not rev:
        return "A"
    if rev.isdigit():
        return str(int(rev) + 1)
    if len(rev) == 1 and "A" <= rev < "Z":
        return chr(ord(rev) + 1)
    return rev + "1"


def macchina_della_commessa(project):
    """La macchina scelta nella tappa Macchina del Percorso, se c'è."""
    ref = (
        TaskExtraRef.objects.filter(
            task__project=project, task__category__tappa=TappaKickoff.MACCHINA, asset__isnull=False,
        ).exclude(task__status=TaskStatus.CANCELED).select_related("asset").order_by("task_id").first()
    )
    return ref.asset if ref else None


def registra(ref, user, nota: str = "") -> None:
    ProgrammaStorico.objects.create(
        ref=ref, fase=ref.fase, revisione=ref.revisione, code=ref.code, nota=(nota or "")[:500],
        utente=user if getattr(user, "is_authenticated", False) else None,
    )


def avanza(ref, user, azione: str, *, nota: str = "") -> None:
    if not ref.is_programma or azione not in AZIONI:
        raise PassaggioNonValido("Passaggio non valido.")
    da, a, _etichetta = AZIONI[azione]
    if ref.fase not in da:
        raise PassaggioNonValido(f"Il programma è «{ref.get_fase_display()}»: questo passaggio non si fa da qui.")
    if a in (ProgrammaFase.DA_PROVARE, ProgrammaFase.VALIDATO) and not ref.code:
        raise PassaggioNonValido("Scrivi prima il codice del programma.")
    with transaction.atomic():
        if azione == "revisione":
            ref.revisione = revisione_successiva(ref.revisione)
        elif not ref.revisione and ref.code:
            ref.revisione = "A"
        if ref.macchina_id is None and ref.project_id:
            ref.macchina = macchina_della_commessa(ref.project)
        ref.fase = a
        if a == ProgrammaFase.VALIDATO:
            ref.mark_done(user=user if getattr(user, "is_authenticated", False) else None)
        elif ref.status == TechRefStatus.DONE:
            ref.status, ref.done_by, ref.done_at = TechRefStatus.OPEN, None, None
        ref.save()
        registra(ref, user, nota)
        _allinea_attivita(ref, user)


def _allinea_attivita(ref, user) -> None:
    """Validato chiude l'attività che lo chiedeva; una nuova revisione la riapre."""
    task = ref.task
    if task is None:
        return
    from ..views._shared import _log_task_update_events, _task_snapshot

    before = _task_snapshot(task)
    if ref.fase == ProgrammaFase.VALIDATO and task.status not in (TaskStatus.DONE, TaskStatus.CANCELED):
        task.status = TaskStatus.DONE
        task.progress = 100
    elif ref.fase != ProgrammaFase.VALIDATO and task.status == TaskStatus.DONE:
        task.status = TaskStatus.IN_PROGRESS
    else:
        return
    task.save()
    _log_task_update_events(task, user, before)
