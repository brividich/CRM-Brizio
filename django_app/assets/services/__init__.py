# Servizio per il registro manutenzione unificato (WorkOrder + Ticket MAN)

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.urls import reverse
from django.utils import timezone


def ticket_to_maintenance_register_row(ticket: Any) -> dict[str, Any] | None:
    """
    Converte un ticket MAN in una riga del registro manutenzione.

    Restituisce None se:
    - ticket.tipo != MAN
    - ticket.asset_id mancante
    - include_in_maintenance_register=False

    Restituisce dict con:
    - source = "TICKET"
    - maintenance_type = "Straordinaria"
    - asset
    - title
    - description
    - status
    - date
    - executed_at / closed_at se presente
    - technician / assigned info se disponibile
    - ticket
    - ticket_number
    - origin_label
    - notes
    - url dettaglio ticket
    """
    from tickets.models import Ticket, TipoTicket, StatoTicket

    if not isinstance(ticket, Ticket):
        return None

    if ticket.tipo != TipoTicket.MAN:
        return None

    if not ticket.asset_id:
        return None

    if not ticket.include_in_maintenance_register:
        return None

    # Determina la data principale per ordinamento
    date = ticket.closed_at or ticket.created_at

    # Determina lo stato
    status = ticket.stato
    if ticket.stato == StatoTicket.CHIUSO:
        status = "Completato"
    elif ticket.stato == StatoTicket.ANNULLATO:
        status = "Annullato"
    elif ticket.stato == StatoTicket.IN_CARICO:
        status = "In corso"
    elif ticket.stato == StatoTicket.IN_ATTESA:
        status = "In attesa"
    else:
        status = ticket.label_stato

    # Informazioni tecnico/assegnato
    technician = ticket.assegnato_a or ticket.risolto_da_nome or "—"

    # URL dettaglio ticket
    url = reverse("tickets:detail", kwargs={"pk": ticket.id})

    return {
        "source": "TICKET",
        "maintenance_type": "Straordinaria",
        "asset": ticket.asset,
        "title": ticket.titolo,
        "description": ticket.descrizione,
        "status": status,
        "date": date,
        "executed_at": ticket.closed_at,
        "closed_at": ticket.closed_at,
        "created_at": ticket.created_at,
        "technician": technician,
        "assigned_to": ticket.assegnato_a,
        "ticket": ticket,
        "ticket_number": ticket.numero_ticket,
        "origin_label": f"Ticket {ticket.numero_ticket}",
        "notes": ticket.note_interne,
        "url": url,
        "priority": ticket.priorita,
        "category": ticket.label_categoria,
    }


def collect_asset_maintenance_register(asset: Any, *, include_tickets: bool = True) -> list[dict[str, Any]]:
    """
    Restituisce il registro manutenzione unificato per un asset.

    Include:
    - WorkOrder / manutenzioni assets già esistenti
    - ticket MAN inclusi nel registro (se include_tickets=True)

    Ordinamento per data decrescente.
    """
    from assets.models import WorkOrder
    from tickets.models import Ticket, TipoTicket

    rows = []

    # Aggiungi WorkOrder esistenti
    workorders = WorkOrder.objects.filter(asset=asset).select_related(
        "asset", "periodic_verification", "executed_by"
    ).order_by("-closed_at", "-opened_at")

    for wo in workorders:
        rows.append({
            "source": "WORKORDER",
            "maintenance_type": wo.get_kind_display() or "Manuale",
            "asset": wo.asset,
            "title": wo.title or f"WorkOrder #{wo.id}",
            "description": wo.description or "",
            "status": wo.status or "—",
            "date": wo.closed_at or wo.opened_at,
            "executed_at": wo.closed_at,
            "created_at": wo.opened_at,
            "technician": wo.executed_by.get_full_name() if wo.executed_by else "—",
            "assigned_to": wo.executed_by.get_full_name() if wo.executed_by else "—",
            "workorder": wo,
            "origin_label": f"WorkOrder #{wo.id}",
            "notes": wo.notes or "",
            "url": reverse("assets:wo_view", kwargs={"id": wo.id}),
            "get_kind_display": wo.get_kind_display,
        })

    # Aggiungi ticket MAN inclusi nel registro
    if include_tickets:
        tickets = Ticket.objects.filter(
            asset=asset,
            tipo=TipoTicket.MAN,
            include_in_maintenance_register=True
        ).order_by("-closed_at", "-created_at")

        for ticket in tickets:
            row = ticket_to_maintenance_register_row(ticket)
            if row:
                rows.append(row)

    # Ordina per data decrescente
    rows.sort(key=lambda x: x["date"] or datetime.min, reverse=True)

    return rows


def generate_workorders_for_rule(rule: Any, user: Any = None) -> list[Any]:
    """
    Genera WorkOrder per tutti gli asset coinvolti da una regola di manutenzione.

    Crea un WorkOrder per ogni asset della categoria della regola.
    Ogni WorkOrder ha:
    - asset specifico
    - origin=PERIODIC
    - reference_batch comune non vuoto
    - maintenance_rule collegato
    - kind=PREVENTIVE
    - status=OPEN

    Evita duplicati nello stesso batch controllando reference_batch.

    Args:
        rule: MaintenanceRule instance
        user: User instance (opzionale, per executed_by)

    Returns:
        list[WorkOrder]: WorkOrder creati
    """
    from assets.models import Asset, WorkOrder

    if not rule or not rule.asset_category_id:
        return []

    # Genera reference_batch unico
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    rule_id = getattr(rule, "id", "unknown")
    reference_batch = f"BATCH_{rule_id}_{timestamp}"

    # Trova gli asset coperti dal piano (intera categoria oppure selezione esplicita).
    assets = Asset.objects.filter(
        asset_category_id=rule.asset_category_id,
        status=Asset.STATUS_IN_USE
    ).select_related("asset_category")
    if rule.scope_type == rule.SCOPE_ASSETS:
        assets = assets.filter(pk__in=rule.assets.values("pk"))

    created_workorders = []
    for asset in assets:
        # Verifica se esiste già un WorkOrder per questo asset con lo stesso reference_batch
        existing = WorkOrder.objects.filter(
            asset=asset,
            maintenance_rule=rule,
            reference_batch=reference_batch
        ).exists()

        if existing:
            continue

        # Crea WorkOrder
        wo = WorkOrder.objects.create(
            asset=asset,
            maintenance_rule=rule,
            origin=WorkOrder.ORIGIN_PERIODIC,
            reference_batch=reference_batch,
            kind=getattr(rule.intervention_template, "workorder_kind", WorkOrder.KIND_PREVENTIVE),
            status=WorkOrder.STATUS_OPEN,
            title=f"{rule.intervention_template.label} - {asset.asset_tag}",
            description=rule.intervention_template.description or "",
            assigned_to=rule.assigned_to,
            supplier=rule.supplier,
            notes=f"Generato da regola {rule.id} - batch {reference_batch}",
            executed_by=user,
            opened_at=timezone.now(),
        )
        created_workorders.append(wo)

    return created_workorders
