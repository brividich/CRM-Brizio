"""Chiusura di un intervento (OdL) in un'unica transazione.

Prima la view ``workorder_close`` eseguiva in sequenza, senza transazione,
chiusura, causa del guasto, giorni di esecuzione, esito, follow-up e log: se un
passo falliva a meta' l'intervento restava chiuso senza esito, o con i giorni di
esecuzione cancellati e mai ricreati. Qui tutto avviene sotto
``transaction.atomic()`` con il lock sulla riga dell'OdL: un doppio invio del
form trova l'intervento gia' chiuso e si ferma.

Gli effetti esterni (sincronizzazione SharePoint del ticket) partono solo a
transazione confermata (``transaction.on_commit``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from ..models import (
    MaintenanceOccurrence,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderExecutionDay,
    WorkOrderLog,
)

logger = logging.getLogger(__name__)

# Tipi di intervento per cui la causa del guasto ha senso.
FAILURE_CAUSE_KINDS = (WorkOrder.KIND_CORRECTIVE, WorkOrder.KIND_SAFETY, WorkOrder.KIND_CALIBRATION)


class WorkOrderCloseError(Exception):
    """Chiusura rifiutata per una regola di dominio (messaggio per l'utente)."""


class WorkOrderAlreadyClosed(WorkOrderCloseError):
    """L'intervento risultava gia' chiuso o annullato al momento del lock."""


@dataclass(frozen=True)
class CloseData:
    """Dati validati dal form di chiusura."""

    status: str
    esito: str = ""
    closed_at: datetime | None = None
    resolution: str = ""
    intervention_duration: int | None = None
    downtime: int | None = None
    labor_cost: Decimal | None = None
    materials_cost: Decimal | None = None
    cost: Decimal | None = None
    covered_by_contract: bool | None = None
    assistance_contract: Any = None
    resolved_supplier: Any = None
    failure_cause: str = ""
    execution_days: tuple[date, ...] = ()
    follow_up_date: date | None = None
    log_note: str = ""
    assigned_to: Any = None
    executed_by: Any = None
    claim_on_close: bool = False
    pending_occurrences_count: int = 0
    pending_reason: str = ""
    uploads: tuple = ()
    resolve_ticket: bool = False


@dataclass(frozen=True)
class RequestIdentity:
    """Chi chiude: l'utente Django, il nome/email per i log del ticket e se puo'
    gestire il ticket collegato (stessa regola delle API ticket)."""

    name: str = ""
    email: str = ""
    can_manage_ticket: bool = False


@dataclass(frozen=True)
class CloseResult:
    workorder: WorkOrder
    follow_up: WorkOrder | None
    ticket_resolved: bool
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _user_label(user) -> str:
    if user is None:
        return "nessuno"
    return user.get_full_name() or user.username


def ticket_resolvable(workorder: WorkOrder) -> bool:
    """L'OdL ha una segnalazione collegata ancora aperta (APERTA/IN_CARICO/IN_ATTESA)."""
    from tickets.services.stato import STATI_APERTI

    ticket = workorder.ticket if workorder.ticket_id else None
    return bool(ticket is not None and ticket.stato in STATI_APERTI)


def _delete_stored_files(attachments: list) -> None:
    for attachment in attachments:
        try:
            attachment.file.delete(save=False)
        except Exception:  # pragma: no cover - lo storage non deve mascherare l'errore vero
            logger.exception("Allegato OdL %s: file non rimosso dopo il rollback", attachment.pk)


def close_workorder(workorder_id: int, *, data: CloseData, user, request_identity: RequestIdentity) -> CloseResult:
    """Chiude (o annulla, o registra come "Non risolto") l'intervento ``workorder_id``.

    Solleva ``WorkOrderAlreadyClosed`` se l'OdL e' gia' DONE/CANCELED,
    ``WorkOrderCloseError`` per una regola di dominio (checklist obbligatoria),
    ``ValidationError`` se il modello rifiuta i dati. In tutti i casi non resta
    nulla di scritto: ne' a DB ne' sullo storage.
    """
    saved_attachments: list = []
    try:
        with transaction.atomic():
            result = _close_locked(
                workorder_id,
                data=data,
                user=user,
                identity=request_identity,
                saved_attachments=saved_attachments,
            )
    except Exception:
        # Il rollback annulla le righe ma non i file gia' scritti: niente orfani.
        _delete_stored_files(saved_attachments)
        raise
    return result


def _close_locked(workorder_id, *, data: CloseData, user, identity: RequestIdentity, saved_attachments: list) -> CloseResult:
    workorder = (
        WorkOrder.objects.select_for_update()
        .select_related("asset", "maintenance_rule", "assistance_contract", "ticket", "assigned_to")
        .get(pk=workorder_id)
    )
    if workorder.status in (WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED):
        raise WorkOrderAlreadyClosed(
            f"L'intervento #{workorder.display_number} risulta gia' "
            f"{'chiuso' if workorder.status == WorkOrder.STATUS_DONE else 'annullato'}: "
            "nessuna modifica registrata."
        )
    if data.status == WorkOrder.STATUS_DONE:
        blocking = [item for item in workorder.checklist_items.all() if item.blocks_closure]
        if blocking:
            labels = ", ".join(f"#{item.step_number} {item.description}" for item in blocking)
            raise WorkOrderCloseError(
                f"Completa o salta con motivazione gli step obbligatori della checklist prima di chiudere: {labels}."
            )

    authenticated = bool(getattr(user, "is_authenticated", False))
    author = user if authenticated else None

    if data.resolved_supplier is not None and workorder.supplier_id is None:
        workorder.supplier = data.resolved_supplier
    previous_assignee_id = workorder.assigned_to_id
    previous_assignee_label = _user_label(workorder.assigned_to) if workorder.assigned_to_id else "nessuno"
    if data.assigned_to is not None:
        workorder.assigned_to = data.assigned_to
    # Coda condivisa: un intervento che nessuno aveva preso in carico si intesta a
    # chi lo chiude (la casella resta disattivabile per chi registra per un altro).
    if data.claim_on_close and workorder.assigned_to_id is None and authenticated:
        workorder.assigned_to = user
    if data.executed_by is not None:
        workorder.executed_by = data.executed_by
    if data.claim_on_close and workorder.executed_by_id is None and authenticated:
        workorder.executed_by = user
    assignee_changed = workorder.assigned_to_id != previous_assignee_id

    esito = data.esito or ""
    # "Non risolto" non deve mai risultare chiuso, nemmeno per un istante: un OdL
    # chiuso e riaperto avanzerebbe la scadenza su una manutenzione che non ha
    # risolto nulla. Si registrano i dati e l'OdL resta aperto.
    reopened_as_unresolved = data.status == WorkOrder.STATUS_DONE and esito == WorkOrder.OUTCOME_NOT_RESOLVED
    closure_kwargs = dict(
        resolution=data.resolution or "",
        intervention_duration=data.intervention_duration,
        downtime=data.downtime,
        labor_cost=data.labor_cost,
        materials_cost=data.materials_cost,
        cost=data.cost,
        covered_by_contract=data.covered_by_contract,
        assistance_contract=data.assistance_contract,
    )
    if reopened_as_unresolved:
        workorder.record_outcome_keep_open(**closure_kwargs)
    else:
        workorder.close(status=data.status, closed_at=data.closed_at, **closure_kwargs)

    failure_cause = data.failure_cause or ""
    if workorder.kind not in FAILURE_CAUSE_KINDS:
        failure_cause = ""
    if failure_cause != workorder.failure_cause:
        workorder.failure_cause = failure_cause
        workorder.save(update_fields=["failure_cause"])

    execution_days = list(data.execution_days or ())
    workorder.execution_days.all().delete()
    WorkOrderExecutionDay.objects.bulk_create(
        [WorkOrderExecutionDay(work_order=workorder, execution_date=day) for day in execution_days]
    )

    follow_up = None
    if reopened_as_unresolved:
        workorder.outcome = esito
        workorder.save(update_fields=["outcome"])
    elif workorder.status == WorkOrder.STATUS_DONE and esito:
        outcome_fields = ["outcome"]
        workorder.outcome = esito
        if esito == WorkOrder.OUTCOME_RESOLVED_TEMP:
            workorder.follow_up_date = data.follow_up_date
            outcome_fields.append("follow_up_date")
        workorder.save(update_fields=outcome_fields)
        if esito == WorkOrder.OUTCOME_RESOLVED_TEMP:
            follow_up = WorkOrder.objects.create(
                asset=workorder.asset,
                supplier=workorder.supplier,
                maintenance_rule=workorder.maintenance_rule,
                kind=workorder.kind,
                origin=WorkOrder.ORIGIN_MANUAL,
                assigned_to=workorder.assigned_to,
                title=f"Verifica: {workorder.title}",
                description=(
                    f"Intervento di verifica dell'intervento #{workorder.id}, "
                    f"risolto temporaneamente il {timezone.localtime(workorder.closed_at):%d/%m/%Y}."
                ),
                follow_up_of=workorder,
            )
            WorkOrderLog.objects.create(
                work_order=follow_up,
                note=f"Creato come intervento di verifica dell'intervento #{workorder.id}.",
                author=author,
            )

    # Segnalazione collegata: si risolve solo con esito "Risolto", su richiesta
    # esplicita e se chi chiude puo' gestire quel ticket.
    ticket_resolved = False
    ticket_note = ""
    if workorder.ticket_id and ticket_resolvable(workorder):
        ticket = workorder.ticket
        if (
            workorder.status == WorkOrder.STATUS_DONE
            and esito == WorkOrder.OUTCOME_RESOLVED
            and data.resolve_ticket
            and identity.can_manage_ticket
        ):
            from tickets.models import StatoTicket
            from tickets.services.stato import cambia_stato_ticket

            cambia_stato_ticket(
                ticket,
                StatoTicket.RISOLTO,
                utente_nome=identity.name or _user_label(author),
                utente_email=identity.email,
                nota=f"Risolto con la chiusura dell'intervento #{workorder.display_number}.",
            )
            ticket_resolved = True
            ticket_note = f"Segnalazione {ticket.numero_ticket} segnata come Risolta."
        elif workorder.status != WorkOrder.STATUS_CANCELED:
            ticket_note = f"Segnalazione {ticket.numero_ticket} invariata ({ticket.get_stato_display()})."

    if workorder.status == WorkOrder.STATUS_DONE:
        closure_note = f"Intervento chiuso · esito: {workorder.get_outcome_display()}."
    elif workorder.status == WorkOrder.STATUS_CANCELED:
        closure_note = "Intervento annullato."
    else:
        closure_note = f"Intervento non risolto, resta aperto · esito: {workorder.get_outcome_display()}."
    if follow_up is not None:
        closure_note = (
            f"{closure_note} Intervento di verifica #{follow_up.id} creato "
            f"(verifica entro il {workorder.follow_up_date:%d/%m/%Y})."
        )
    if assignee_changed:
        closure_note = (
            f"{closure_note} Assegnatario aggiornato: {previous_assignee_label} → "
            f"{_user_label(workorder.assigned_to) if workorder.assigned_to_id else 'nessuno'}."
        )
    if execution_days:
        closure_note = f"{closure_note} Giorni esecuzione: {', '.join(day.strftime('%d/%m/%Y') for day in execution_days)}."
    if data.pending_occurrences_count:
        closure_note = (
            f"{closure_note} Chiuso con {data.pending_occurrences_count} manutenzioni "
            "raccolte non registrate, che restano dovute."
        )
        if data.pending_reason:
            closure_note = f"{closure_note} Motivo: {data.pending_reason}"
    if ticket_note:
        closure_note = f"{closure_note} {ticket_note}"
    if data.log_note:
        closure_note = f"{closure_note} {data.log_note}"
    if data.uploads:
        for upload in data.uploads:
            attachment = WorkOrderAttachment.objects.create(
                work_order=workorder,
                file=upload,
                original_name=Path(getattr(upload, "name", "") or "").name[:255],
                uploaded_by=author,
            )
            saved_attachments.append(attachment)
        closure_note = f"{closure_note} Allegati caricati: {len(saved_attachments)}."
    WorkOrderLog.objects.create(work_order=workorder, note=closure_note, author=author)

    if workorder.status == WorkOrder.STATUS_DONE:
        success = "Intervento chiuso."
    elif workorder.status == WorkOrder.STATUS_CANCELED:
        success = "Intervento annullato."
    else:
        success = "Intervento registrato come non risolto: resta aperto."
    if follow_up is not None:
        success = f"{success} Creato l'intervento di verifica #{follow_up.id}."
    if ticket_resolved:
        success = f"{success} La segnalazione {workorder.ticket.numero_ticket} e' ora Risolta."
    messages = [success]

    # Chiudere l'intervento non registra le manutenzioni raccolte: se ne restano
    # aperte la scadenza resta scaduta, e va detto subito.
    warnings: list[str] = []
    if workorder.status in (WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED):
        aperte = MaintenanceOccurrence.objects.filter(
            work_order=workorder, status=MaintenanceOccurrence.STATUS_OPEN
        ).count()
        if aperte == 1:
            warnings.append(
                "Una manutenzione raccolta in questo intervento non risulta "
                "registrata: la sua scadenza resta aperta. Registrala dal "
                "pannello «Manutenzioni raccolte»."
            )
        elif aperte:
            warnings.append(
                f"{aperte} manutenzioni raccolte in questo intervento non "
                "risultano registrate: le loro scadenze restano aperte. "
                "Registrale dal pannello «Manutenzioni raccolte»."
            )

    return CloseResult(
        workorder=workorder,
        follow_up=follow_up,
        ticket_resolved=ticket_resolved,
        messages=messages,
        warnings=warnings,
    )
