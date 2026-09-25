"""Dominio delle verifiche periodiche sugli impianti.

Tutta la logica che cambia dati passa da qui (viste, import dello storico, test):
registrazione di una verifica, conferma, ricalcolo della prossima scadenza del tipo,
OdL dai rilievi non conformi. Vedi docs/ai/VERIFICHE_PERIODICHE.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from ..models import (
    PeriodicCheckAttachment,
    PeriodicCheckItem,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckType,
    WorkOrder,
)

STATE_OVERDUE = "overdue"
STATE_DUE_SOON = "due_soon"
STATE_OK = "ok"
STATE_UNSCHEDULED = "unscheduled"

STATE_LABELS = {
    STATE_OVERDUE: "Scaduta",
    STATE_DUE_SOON: "In scadenza",
    STATE_OK: "In regola",
    STATE_UNSCHEDULED: "Da pianificare",
}


def type_state(check_type: PeriodicCheckType, today: date | None = None) -> str:
    today = today or timezone.localdate()
    due = check_type.next_due_date
    if due is None:
        return STATE_UNSCHEDULED
    if due < today:
        return STATE_OVERDUE
    if due <= today + timedelta(days=check_type.warning_days):
        return STATE_DUE_SOON
    return STATE_OK


@dataclass
class ResultInput:
    label: str
    result: str = PeriodicCheckResult.RESULT_OK
    note: str = ""
    item: PeriodicCheckItem | None = None
    kind: str = PeriodicCheckResult.KIND_ITEM


@dataclass
class SessionInput:
    check_type: PeriodicCheckType
    performed_on: date
    outcome: str
    technician: str = ""
    supplier_id: int | None = None
    notes: str = ""
    next_due_date: date | None = None
    results: list[ResultInput] = field(default_factory=list)
    source: str = PeriodicCheckSession.SOURCE_MANUAL
    status: str = PeriodicCheckSession.STATUS_CONFIRMED
    import_key: str = ""


def outcome_from_results(results: Iterable[ResultInput], *, fallback: str) -> str:
    """Una voce non OK rende la verifica "con rilievi" se l'utente la dava conforme."""
    if fallback == PeriodicCheckSession.OUTCOME_OK and any(
        r.result == PeriodicCheckResult.RESULT_KO for r in results
    ):
        return PeriodicCheckSession.OUTCOME_REMARKS
    return fallback


@transaction.atomic
def register_session(data: SessionInput, *, user=None, files: Iterable = ()) -> PeriodicCheckSession:
    session = PeriodicCheckSession.objects.create(
        check_type=data.check_type,
        performed_on=data.performed_on,
        technician=data.technician[:120],
        supplier_id=data.supplier_id or data.check_type.supplier_id,
        outcome=outcome_from_results(data.results, fallback=data.outcome),
        status=data.status,
        source=data.source,
        notes=data.notes,
        next_due_date=data.next_due_date,
        import_key=data.import_key[:255],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for index, row in enumerate(data.results):
        PeriodicCheckResult.objects.create(
            session=session,
            item=row.item,
            kind=row.kind,
            label=row.label[:255],
            result=row.result,
            note=row.note[:500],
            sort_order=(index + 1) * 10,
        )
    for upload in files:
        add_attachment(session, upload, user=user)
    if session.status == PeriodicCheckSession.STATUS_CONFIRMED:
        _stamp_confirmation(session, user)
        refresh_next_due(session.check_type)
    return session


def add_attachment(session: PeriodicCheckSession, upload, *, user=None, name: str = "") -> PeriodicCheckAttachment:
    return PeriodicCheckAttachment.objects.create(
        session=session,
        file=upload,
        original_name=(name or Path(getattr(upload, "name", "") or "").name)[:255],
        uploaded_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _stamp_confirmation(session: PeriodicCheckSession, user) -> None:
    session.confirmed_by = user if getattr(user, "is_authenticated", False) else None
    session.confirmed_at = timezone.now()
    session.save(update_fields=["confirmed_by", "confirmed_at", "updated_at"])


@transaction.atomic
def confirm_session(session: PeriodicCheckSession, *, user=None) -> None:
    session.status = PeriodicCheckSession.STATUS_CONFIRMED
    session.save(update_fields=["status", "updated_at"])
    _stamp_confirmation(session, user)
    refresh_next_due(session.check_type)


def refresh_next_due(check_type: PeriodicCheckType) -> date | None:
    """Prossima scadenza = dall'ultima verifica confermata (la data indicata a mano
    vince, es. la scadenza scritta sul verbale DPR 462). Senza verifiche confermate
    la scadenza impostata a mano resta com'e'."""
    last = (
        check_type.sessions.filter(status=PeriodicCheckSession.STATUS_CONFIRMED)
        .order_by("-performed_on", "-id")
        .first()
    )
    if last is None:
        return check_type.next_due_date
    due = last.next_due_date or check_type.next_due_from(last.performed_on)
    if check_type.next_due_date != due:
        check_type.next_due_date = due
        check_type.save(update_fields=["next_due_date", "updated_at"])
    return due


def last_session(check_type: PeriodicCheckType) -> PeriodicCheckSession | None:
    return (
        check_type.sessions.filter(status=PeriodicCheckSession.STATUS_CONFIRMED)
        .order_by("-performed_on", "-id")
        .first()
    )


def create_work_order(result: PeriodicCheckResult, *, asset, user=None, title: str = "") -> WorkOrder:
    """OdL correttivo da un rilievo non conforme; il rilievo resta collegato all'OdL."""
    if result.work_order_id:
        return result.work_order
    session = result.session
    check_type = session.check_type
    description = (
        f"Da verifica periodica «{check_type.name}» ({check_type.system.name}) "
        f"del {session.performed_on:%d/%m/%Y}.\n{result.label}"
    )
    if result.note:
        description += f"\n{result.note}"
    work_order = WorkOrder.objects.create(
        asset=asset,
        kind=WorkOrder.KIND_CORRECTIVE,
        origin=WorkOrder.ORIGIN_MANUAL,
        status=WorkOrder.STATUS_OPEN,
        title=(title or f"{check_type.name}: {result.label}")[:255],
        description=description,
        supplier_id=check_type.supplier_id,
    )
    result.work_order = work_order
    result.save(update_fields=["work_order"])
    return work_order
