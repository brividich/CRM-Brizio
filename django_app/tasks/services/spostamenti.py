"""Richieste di spostamento delle date: chi non ha pieni poteri chiede, il capocommessa decide.

Il primo che decide chiude la richiesta; gli altri vedono chi ha deciso. Tutto
resta nello storico dell'attività (TaskEvent DATE_REQUEST + modifiche applicate).
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from ..access import ha_pieni_poteri, puo_spostare_subito, utenti_pieni_poteri
from ..models import SpostamentoStato, TaskEvent, TaskEventType, TaskSpostamento
from .notify import notify_user

logger = logging.getLogger(__name__)


class SpostamentoNonValido(ValueError):
    pass


def _fmt(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _date_cambiate(task, before: dict) -> bool:
    return before.get("next_step_due") != task.next_step_due or before.get("due_date") != task.due_date


def intercetta(request, task, before: dict, *, motivo: str = "") -> TaskSpostamento | None:
    """Prima del salvataggio: se le date cambiano e chi modifica non può, diventa una richiesta.

    Rimette sull'oggetto le date di prima (il chiamante salva il resto) e ritorna la richiesta.
    """
    if not _date_cambiate(task, before) or puo_spostare_subito(request, task):
        return None
    nuovo_inizio, nuova_fine = task.next_step_due, task.due_date
    task.next_step_due, task.due_date = before.get("next_step_due"), before.get("due_date")
    return crea_richiesta(request.user, task, nuovo_inizio, nuova_fine, motivo=motivo)


def crea_richiesta(user, task, inizio, fine, *, motivo: str = "") -> TaskSpostamento:
    if inizio and fine and fine < inizio:
        raise SpostamentoNonValido("La fine non può venire prima dell'inizio.")
    with transaction.atomic():
        # Una sola richiesta aperta per attività: la nuova sostituisce la precedente.
        TaskSpostamento.objects.filter(task=task, stato=SpostamentoStato.IN_ATTESA).update(
            stato=SpostamentoStato.ANNULLATA, deciso_at=timezone.now(), nota_decisione="Sostituita da una nuova richiesta.",
        )
        sp = TaskSpostamento.objects.create(
            task=task, richiesto_da=user, inizio_prima=task.next_step_due, fine_prima=task.due_date,
            inizio_nuovo=inizio, fine_nuovo=fine, motivo=(motivo or "").strip()[:500],
        )
        TaskEvent.objects.create(task=task, actor=user, type=TaskEventType.DATE_REQUEST, payload={
            "azione": "richiesta", "id": sp.pk, "inizio": str(inizio or ""), "fine": str(fine or ""), "motivo": sp.motivo,
        })
    _avvisa_approvatori(sp)
    return sp


def _avvisa_approvatori(sp: TaskSpostamento) -> None:
    task = sp.task
    if not task.project_id:
        return
    chi = (sp.richiesto_da.get_full_name() or sp.richiesto_da.get_username()) if sp.richiesto_da else "Qualcuno"
    testo = (
        f"{chi} chiede di spostare «{task.title}» [{task.project.name}]: "
        f"{_fmt(sp.inizio_prima)}–{_fmt(sp.fine_prima)} → {_fmt(sp.inizio_nuovo)}–{_fmt(sp.fine_nuovo)}."
        + (f" Motivo: {sp.motivo}" if sp.motivo else "")
    )
    url = reverse("tasks:detail", kwargs={"task_id": task.pk}) + "#spostamenti"
    for u in utenti_pieni_poteri(task.project):
        if u.pk == sp.richiesto_da_id:
            continue
        try:
            notify_user(u, testo, url)
            from .avvisi import mail_cambiamento

            mail_cambiamento(task, u, testo)
        except Exception:
            logger.exception("Avviso richiesta spostamento non inviato (sp=%s)", sp.pk)


def decidi(request, sp: TaskSpostamento, *, approva: bool, nota: str = "", inizio=None, fine=None) -> TaskSpostamento:
    from ..views._shared import _log_task_update_events, _task_snapshot

    task = sp.task
    if not ha_pieni_poteri(request, task.project):
        raise SpostamentoNonValido("Decide chi ha pieni poteri sulla commessa (capocommessa).")
    with transaction.atomic():
        sp = TaskSpostamento.objects.select_for_update().select_related("deciso_da").get(pk=sp.pk)
        if not sp.in_attesa:
            chi = sp.deciso_da.get_full_name() if sp.deciso_da else ""
            raise SpostamentoNonValido(f"Già decisa{(' da ' + chi) if chi else ''}: {sp.get_stato_display().lower()}.")
        if approva:
            inizio = inizio if inizio is not None else sp.inizio_nuovo
            fine = fine if fine is not None else sp.fine_nuovo
            if inizio and fine and fine < inizio:
                raise SpostamentoNonValido("La fine non può venire prima dell'inizio.")
            before = _task_snapshot(task)
            task.next_step_due, task.due_date = inizio, fine
            task.save(update_fields=["next_step_due", "due_date", "updated_at"])
            sp.inizio_nuovo, sp.fine_nuovo = inizio, fine
        sp.stato = SpostamentoStato.APPROVATA if approva else SpostamentoStato.RIFIUTATA
        sp.deciso_da, sp.deciso_at, sp.nota_decisione = request.user, timezone.now(), (nota or "").strip()[:500]
        sp.save()
        TaskEvent.objects.create(task=task, actor=request.user, type=TaskEventType.DATE_REQUEST, payload={
            "azione": "approvata" if approva else "rifiutata", "id": sp.pk, "nota": sp.nota_decisione,
        })
    if approva:
        # Registra le date nuove e avvisa i coinvolti (incaricato compreso).
        _log_task_update_events(task, request.user, before)
    if sp.richiesto_da_id and sp.richiesto_da_id != request.user.pk:
        esito = "approvata" if approva else "rifiutata"
        testo = f"Richiesta di spostamento di «{task.title}» {esito}" + (f": {sp.nota_decisione}" if sp.nota_decisione else ".")
        notify_user(sp.richiesto_da, testo, reverse("tasks:detail", kwargs={"task_id": task.pk}))
    return sp


def richieste_da_decidere(request, progetti_qs):
    """Richieste aperte sulle commesse dove chi guarda ha pieni poteri."""
    aperte = (
        TaskSpostamento.objects.filter(stato=SpostamentoStato.IN_ATTESA, task__project__in=progetti_qs)
        .select_related("task__project", "richiesto_da")
        .order_by("created_at")
    )
    return [sp for sp in aperte if ha_pieni_poteri(request, sp.task.project)]
