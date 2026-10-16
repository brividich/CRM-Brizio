"""Movimenti dei ricambi: la giacenza cambia solo da qui.

Ogni movimento blocca la riga del ricambio (``select_for_update``) e aggiorna la
giacenza nella stessa transazione: due scarichi contemporanei non vanno sotto zero
e non si perdono a vicenda.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Sum

from ..models import SparePart, SparePartMovement


class SparePartError(ValueError):
    """Movimento rifiutato (messaggio per l'utente)."""


def parse_qty(raw) -> Decimal:
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise SparePartError("Quantita' non valida.") from None
    if not value.is_finite() or value < 0:
        raise SparePartError("La quantita' deve essere un numero positivo.")
    return value.quantize(Decimal("0.01"))


def register_movement(
    part: SparePart,
    kind: str,
    qty,
    *,
    user=None,
    work_order=None,
    unit_cost=None,
    note: str = "",
) -> SparePartMovement:
    """Registra un movimento e aggiorna la giacenza.

    * ``IN`` aggiunge ``qty``; ``OUT`` la toglie e non puo' andare sotto zero;
    * ``ADJUST`` porta la giacenza a ``qty`` (valore contato) e vuole una nota.
    """
    qty = parse_qty(qty)
    note = (note or "").strip()[:255]
    if kind not in dict(SparePartMovement.KIND_CHOICES):
        raise SparePartError("Tipo di movimento non valido.")
    if kind != SparePartMovement.KIND_ADJUST and qty <= 0:
        raise SparePartError("La quantita' deve essere maggiore di zero.")
    if kind == SparePartMovement.KIND_ADJUST and not note:
        raise SparePartError("Per una rettifica serve una nota (es. «inventario del 16/10»).")

    with transaction.atomic():
        locked = SparePart.objects.select_for_update().get(pk=part.pk)
        if kind == SparePartMovement.KIND_IN:
            new_stock = locked.stock_qty + qty
        elif kind == SparePartMovement.KIND_OUT:
            new_stock = locked.stock_qty - qty
            if new_stock < 0:
                raise SparePartError(
                    f"Giacenza insufficiente per {locked.code}: disponibili {locked.stock_qty} {locked.unit}, "
                    f"richiesti {qty}. Se il magazzino reale e' diverso, fai una rettifica."
                )
        else:
            new_stock = qty
        cost = unit_cost
        if cost in (None, "") and kind == SparePartMovement.KIND_OUT:
            cost = locked.unit_cost_eur
        locked.stock_qty = new_stock
        locked.save(update_fields=["stock_qty", "updated_at"])
        movement = SparePartMovement.objects.create(
            part=locked,
            kind=kind,
            qty=qty,
            stock_after=new_stock,
            work_order=work_order,
            unit_cost_eur=cost if cost not in ("",) else None,
            note=note,
            user=user if getattr(user, "is_authenticated", False) else None,
        )
    part.stock_qty = new_stock
    return movement


def workorder_parts_cost(work_order) -> Decimal | None:
    """Somma qty x costo (snapshot) degli scarichi sull'intervento; None se nessun costo noto."""
    total = (
        SparePartMovement.objects.filter(
            work_order=work_order, kind=SparePartMovement.KIND_OUT, unit_cost_eur__isnull=False
        )
        .aggregate(total=Sum(F("qty") * F("unit_cost_eur")))
        .get("total")
    )
    if total is None:
        return None
    return Decimal(total).quantize(Decimal("0.01"))


def below_min_queryset():
    return SparePart.objects.filter(is_active=True, stock_qty__lte=F("min_qty"))
