"""Disponibilita' asset e conflitti di prenotazione fra attivita'."""
from __future__ import annotations

import logging
from datetime import datetime

from django.urls import reverse
from django.utils import timezone


from ..models import (
    Task,
    TaskCategoryFieldType,
    TaskExtraRef,
    TaskImpostazioni,
    TaskStatus,
)

logger = logging.getLogger(__name__)


def _parse_iso_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _task_time_window(task: "Task"):
    """Finestra temporale di un task, normalizzata a (start, end).

    - Se next_step_due e due_date sono entrambi presenti, usa [next_step_due, due_date].
    - Se solo due_date, finestra = [due_date, due_date].
    - Se solo next_step_due, finestra = [next_step_due, next_step_due].
    - Se nessuno dei due, ritorna (None, None).
    """
    start = getattr(task, "next_step_due", None)
    end = getattr(task, "due_date", None)
    if start and end:
        if end < start:
            start, end = end, start
        return start, end
    if end:
        return end, end
    if start:
        return start, start
    return None, None


def _windows_overlap(a_start, a_end, b_start, b_end) -> bool:
    if not a_start or not a_end or not b_start or not b_end:
        return False
    return a_start <= b_end and b_start <= a_end


def _asset_availability_report(
    asset,
    start,
    end,
    exclude_task_id: int | None = None,
    scope_task_ids: set[int] | None = None,
) -> dict:
    # SEC: `scope_task_ids` (se fornito) e' l'insieme dei task visibili al richiedente
    # (scope OWN/TEAM). I conflitti su task fuori scope mostrano solo l'occupazione,
    # senza titolo (che puo' contenere P/N o riferimenti cliente) ne' link.
    """Calcola il report di disponibilita per un asset nella finestra [start, end].

    Il risultato contiene: stato asset, OdL aperti, verifiche periodiche, ticket
    manutenzione aperti, task sovrapposti (via TaskExtraRef), severita
    complessiva.
    """
    from assets.models import Asset, WorkOrder, PeriodicVerification

    conflicts: list[dict] = []
    overall = "ok"

    def bump(level: str) -> None:
        nonlocal overall
        order = {"ok": 0, "warning": 1, "block": 2}
        if order[level] > order[overall]:
            overall = level

    # 1) Status asset
    if asset.status == Asset.STATUS_IN_REPAIR:
        conflicts.append({
            "type": "asset_status",
            "severity": "block",
            "title": f"Asset in riparazione: {asset.get_status_display()}",
            "detail": asset.notes or "",
            "when": "",
            "url": "",
        })
        bump("block")

    # 2) Ordini di lavoro aperti. Se la finestra e' nota, consideriamo solo
    #    quelli che si sovrappongono; altrimenti li riportiamo tutti (OPEN).
    wo_qs = WorkOrder.objects.filter(
        asset=asset,
        status=WorkOrder.STATUS_OPEN,
    ).order_by("opened_at")
    try:
        asset_view_url = reverse("assets:asset_view", kwargs={"id": asset.id})
    except Exception:
        asset_view_url = ""
    for wo in wo_qs[:50]:
        wo_start = wo.opened_at.date() if wo.opened_at else None
        wo_end = wo.closed_at.date() if wo.closed_at else None
        if start and end and wo_start:
            # consideriamo un OdL ancora aperto senza data di chiusura come
            # "in corso" fino a oggi incluso
            effective_end = wo_end or timezone.localdate()
            if not _windows_overlap(start, end, wo_start, effective_end):
                continue
        conflicts.append({
            "type": "workorder",
            "severity": "block",
            "title": f"OdL aperto #{wo.id}: {wo.title}",
            "detail": wo.get_kind_display(),
            "when": wo_start.isoformat() if wo_start else "",
            "url": asset_view_url,
        })
        bump("block")

    # 3) Verifiche periodiche in finestra
    pv_qs = PeriodicVerification.objects.filter(
        assets=asset,
        is_active=True,
        next_verification_date__isnull=False,
    )
    if start and end:
        pv_qs = pv_qs.filter(next_verification_date__gte=start, next_verification_date__lte=end)
    for pv in pv_qs.order_by("next_verification_date")[:20]:
        conflicts.append({
            "type": "verification",
            "severity": "warning",
            "title": f"Verifica periodica: {pv.name}",
            "detail": "",
            "when": pv.next_verification_date.isoformat() if pv.next_verification_date else "",
            "url": asset_view_url,
        })
        bump("warning")

    # 4) Ticket manutenzione aperti sull'asset
    try:
        from tickets.models import Ticket, StatoTicket
        open_states = [
            StatoTicket.APERTA,
            StatoTicket.IN_CARICO,
            StatoTicket.IN_ATTESA,
        ]
        for tk in Ticket.objects.filter(asset=asset, stato__in=open_states).order_by("-pk")[:20]:
            try:
                tk_url = reverse("tickets:detail", kwargs={"ticket_id": tk.id})
            except Exception:
                tk_url = ""
            conflicts.append({
                "type": "ticket",
                "severity": "warning",
                "title": f"Ticket {tk.numero_ticket}: {tk.titolo}",
                "detail": tk.get_stato_display(),
                "when": "",
                "url": tk_url,
            })
            bump("warning")
    except Exception:
        pass

    # 5) Task sovrapposti (stesso asset via TaskExtraRef, stato attivo)
    if start and end:
        tref_qs = (
            TaskExtraRef.objects.filter(asset=asset)
            .exclude(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED])
            .select_related("task")
        )
        if exclude_task_id:
            tref_qs = tref_qs.exclude(task_id=exclude_task_id)
        seen_task_ids: set[int] = set()
        for ref in tref_qs[:100]:
            if ref.task_id in seen_task_ids:
                continue
            other = ref.task
            o_start, o_end = _task_time_window(other)
            if not _windows_overlap(start, end, o_start, o_end):
                continue
            seen_task_ids.add(ref.task_id)
            in_scope = scope_task_ids is None or other.id in scope_task_ids
            try:
                t_url = reverse("tasks:detail", kwargs={"task_id": other.id}) if in_scope else ""
            except Exception:
                t_url = ""
            when_label = o_start.isoformat() if o_start else ""
            if o_start and o_end and o_start != o_end:
                when_label = f"{o_start.isoformat()} -> {o_end.isoformat()}"
            conflicts.append({
                "type": "task",
                "severity": "block",
                "title": (
                    f"Attivita gia' assegnata: {other.title}" if in_scope
                    else "Attivita gia' assegnata (altro team)"
                ),
                "detail": other.get_status_display() if in_scope else "",
                "when": when_label,
                "url": t_url,
            })
            bump("block")

    # 6) Carico macchina da Gestione Carichi Macchina (integrazione, SOLO AVVISO).
    #    Se l'asset ha un profilo Macchina, mostriamo le pianificazioni che si
    #    sovrappongono alla finestra. Non bloccante: severity sempre 'warning'.
    if start and end:
        try:
            from gestione_carichi_macchina.integrations import pianificazioni_for_asset

            for pl in pianificazioni_for_asset(asset.id, start, end):
                if pl.get("is_kickoff"):
                    continue  # già rappresentata dalla task KICK-OFF di origine
                when = pl["data"].isoformat()
                if pl["fine"] != pl["data"]:
                    when = f'{pl["data"].isoformat()} -> {pl["fine"].isoformat()}'
                titolo = pl["commessa"] or pl["label"] or "lavoro pianificato"
                det = []
                if pl["ore"]:
                    det.append(f'{pl["ore"]:.0f}h')
                if pl.get("qta"):
                    det.append(f'{pl["qta"]} pz')
                conflicts.append({
                    "type": "carico_macchina",
                    "severity": "warning",
                    "title": f"Carico macchina (Carichi): {titolo}",
                    "detail": " · ".join(det),
                    "when": when,
                    "url": "",
                })
                bump("warning")
        except Exception:
            pass

    return {
        "asset": {
            "id": asset.id,
            "tag": getattr(asset, "asset_tag", "") or "",
            "name": asset.name,
            "status": asset.status,
            "status_label": asset.get_status_display(),
        },
        "window": {
            "start": start.isoformat() if start else "",
            "end": end.isoformat() if end else "",
        },
        "conflicts": conflicts,
        "overall_severity": overall,
        "has_blocking_conflict": any(c["severity"] == "block" for c in conflicts),
    }


def _check_machine_work_overlaps(task: "Task", exclude_task_id: int | None) -> list[str]:
    """Ritorna avvisi (non bloccanti) se l'asset assegnato è già occupato da
    un altro task 'lavoro macchina' nella stessa finestra temporale."""
    if not task.category_id or not getattr(task.category, "is_machine_work", False):
        return []
    start = task.next_step_due
    end = task.due_date
    if not start and not end:
        return []
    asset_refs = list(
        task.extra_refs.filter(asset__isnull=False).select_related("asset")
    )
    if not asset_refs:
        return []
    warnings_out: list[str] = []
    for ref in asset_refs:
        qs = (
            TaskExtraRef.objects
            .filter(asset_id=ref.asset_id)
            .exclude(task_id=task.pk)
            .select_related("task__category", "task__assigned_to")
            .filter(
                task__category__is_machine_work=True,
                task__status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS],
            )
        )
        if exclude_task_id:
            qs = qs.exclude(task_id=exclude_task_id)
        conflicts = []
        for other_ref in qs:
            t = other_ref.task
            t_start = t.next_step_due
            t_end = t.due_date
            overlaps = True
            if start and t_end and t_end < start:
                overlaps = False
            if end and t_start and t_start > end:
                overlaps = False
            if overlaps:
                conflicts.append(t)
        if conflicts:
            asset_label = f"{ref.asset.asset_tag} - {ref.asset.name}"
            titles = ", ".join(f"'{c.title}'" for c in conflicts[:3])
            suffix = f" (+{len(conflicts)-3} altri)" if len(conflicts) > 3 else ""
            warnings_out.append(
                f"Macchina {asset_label} già impegnata nello stesso periodo: {titles}{suffix}."
            )
    return warnings_out


def _check_blocking_asset_conflicts(task: "Task", post_data, exclude_task_id: int | None) -> list[str]:
    """Ritorna la lista di messaggi di errore per eventuali conflitti asset
    bloccanti, usando la stessa logica dell'endpoint availability. Se le
    impostazioni disabilitano il blocco, ritorna [].
    """
    cfg = TaskImpostazioni.get_singleton()
    if not cfg.asset_conflict_check_enabled or not cfg.asset_conflict_block:
        return []
    if not task.category_id:
        return []
    try:
        from assets.models import Asset
    except ImportError:
        return []
    fields = list(task.category.fields.all().order_by("order_index", "id"))
    asset_fields = [f for f in fields if f.field_type == TaskCategoryFieldType.ASSET]
    if not asset_fields:
        return []
    start, end = _task_time_window(task)
    errors: list[str] = []
    for f in asset_fields:
        raw = (post_data.get(f"extra__{f.code}") or "").strip()
        if not raw:
            continue
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            continue
        try:
            asset = Asset.objects.get(pk=aid)
        except Asset.DoesNotExist:
            continue
        report = _asset_availability_report(asset, start, end, exclude_task_id)
        if report["has_blocking_conflict"]:
            tag = report["asset"].get("tag") or ""
            name = report["asset"].get("name") or ""
            asset_label = f"{tag} - {name}" if tag else name
            blocking = [c for c in report["conflicts"] if c["severity"] == "block"]
            details = "; ".join(c["title"] for c in blocking[:3])
            errors.append(
                f"Campo '{f.label}' ({asset_label}): conflitto bloccante - {details}"
            )
    return errors
