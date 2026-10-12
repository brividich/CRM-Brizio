"""Ponte fra i due spazi di id delle persone.

- ``utenti.id`` (``UtenteLegacy``): l'account. E' lo spazio dei permessi
  (``AccessGroupMembership``, team, ``Notifica.legacy_user_id``).
- ``anagrafica_dipendenti.id`` (``AnagraficaDipendente``): la scheda. Molti
  moduli (DPI, visite, formazione, ruoli d'organigramma) salvano questo.

Confonderli manda notifiche e permessi alla persona sbagliata: le conversioni
passano sempre da qui. Una scheda senza account non ha ``utenti.id``.
"""
from __future__ import annotations

from django.db import DatabaseError


def utente_da_anagrafica(anagrafica_id) -> int | None:
    """``utenti.id`` dell'account collegato alla scheda, o None."""
    if not anagrafica_id:
        return None
    from core.legacy_models import AnagraficaDipendente

    try:
        valore = (
            AnagraficaDipendente.objects.filter(pk=int(anagrafica_id))
            .values_list("utente_id", flat=True)
            .first()
        )
    except (DatabaseError, TypeError, ValueError):
        return None
    return int(valore) if valore else None


def anagrafiche_di_utenti(utenti_ids) -> set[int]:
    """``anagrafica_dipendenti.id`` delle schede collegate agli account dati."""
    ids = [int(i) for i in utenti_ids or [] if i]
    if not ids:
        return set()
    from core.legacy_models import AnagraficaDipendente

    try:
        return set(AnagraficaDipendente.objects.filter(utente_id__in=ids).values_list("id", flat=True))
    except DatabaseError:
        return set()
