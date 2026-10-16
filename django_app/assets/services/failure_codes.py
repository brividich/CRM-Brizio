"""Codici guasto (problema / causa / rimedio) e loro filtro per categoria."""

from __future__ import annotations

from django.db.models import Q

from ..models import AssetCategory, FailureCode, WorkOrder

# I sei valori storici di ``WorkOrder.failure_cause``: il codice CAUSE omonimo
# (minuscolo) tiene allineato il campo legacy.
LEGACY_CAUSE_BY_CODE = {value.lower(): value for value, _label in WorkOrder.FAILURE_CAUSE_CHOICES}


def category_with_ancestors(category: AssetCategory | None) -> list[int]:
    """La categoria e i suoi antenati (l'albero e' poco profondo)."""
    ids: list[int] = []
    seen: set[int] = set()
    current = category
    while current is not None and current.pk not in seen and len(ids) < 10:
        ids.append(current.pk)
        seen.add(current.pk)
        current = current.parent
    return ids


def codes_for_category(kind: str, category: AssetCategory | None, *, include_ids=()):
    """Codici attivi validi per ``category``: globali + categoria + antenati.

    ``include_ids`` tiene nel menu un codice gia' scelto anche se nel frattempo e'
    stato disattivato, per non perderlo modificando l'intervento.
    """
    scope = Q(asset_category__isnull=True)
    ancestors = category_with_ancestors(category)
    if ancestors:
        scope |= Q(asset_category_id__in=ancestors)
    queryset = FailureCode.objects.filter(kind=kind).filter(scope).filter(is_active=True)
    extra = [pk for pk in include_ids if pk]
    if extra:
        queryset = FailureCode.objects.filter(Q(pk__in=queryset.values("pk")) | Q(pk__in=extra))
    return queryset.select_related("asset_category").order_by("sort_order", "label", "id")


def legacy_cause_for(code: FailureCode | None) -> str | None:
    """Valore di ``failure_cause`` corrispondente a un codice CAUSE, se esiste."""
    if code is None or code.kind != FailureCode.KIND_CAUSE:
        return None
    return LEGACY_CAUSE_BY_CODE.get((code.code or "").lower())
