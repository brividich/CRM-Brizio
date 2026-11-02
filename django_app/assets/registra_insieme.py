"""«Registra insieme»: la stessa operazione su piu' voci gemelle (altri asset, altre
licenze, altri contratti). Periodo proposto nelle finestre con il filtro «scadute o
entro»: il server propone fino al massimo, la pagina restringe; al salvataggio
l'elenco consentito si ricalcola sempre lato server.

Checklist e avanzamento: docs/ai/CHECKLIST_REGISTRA_INSIEME.md.
"""

from __future__ import annotations

from datetime import date

WINDOW_DEFAULT_DAYS = 30
WINDOW_CHOICES = (
    (7, "7 giorni"), (15, "15 giorni"), (30, "30 giorni"), (60, "60 giorni"),
    (90, "90 giorni"), (180, "6 mesi"), (365, "un anno"),
)
WINDOW_MAX_DAYS = max(days for days, _label in WINDOW_CHOICES)


def days_between(reference: date | None, other: date | None) -> int | None:
    """Giorni da ``reference`` a ``other`` (negativi = prima); None se manca una data."""
    if reference is None or other is None:
        return None
    return (other - reference).days


def within_window(reference: date | None, other: date | None) -> bool:
    """La gemella rientra nel massimo proposto: gia' passata rispetto alla voce o entro
    ``WINDOW_MAX_DAYS``. Senza data della voce principale vale tutto quanto ha una data."""
    if other is None:
        return False
    if reference is None:
        return True
    return (other - reference).days <= WINDOW_MAX_DAYS


def ids_from_post(request, field: str, *, exclude: int | None = None) -> set[int]:
    """Id interi positivi da un campo multiplo del POST (gli altri valori si scartano)."""
    ids = {int(raw) for raw in request.POST.getlist(field) if str(raw).strip().isdigit()}
    ids.discard(0)
    if exclude is not None:
        ids.discard(int(exclude))
    return ids


def window_context() -> dict:
    return {"insieme_window_choices": WINDOW_CHOICES, "insieme_window_default": WINDOW_DEFAULT_DAYS}
