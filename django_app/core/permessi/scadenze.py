"""Scadenza dei ruoli assegnati a mano (``AccessGroupMembership.scade_il``).

Serve agli utenti esterni (RSPP, medico competente, ente di certificazione):
il ruolo vale fino al giorno indicato compreso, poi non conta piu', senza che
qualcuno debba ricordarsi di toglierlo. Ogni lettura delle appartenenze passa
da qui, cosi' la regola e' una sola.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone


def q_appartenenze_valide(prefisso: str = "") -> Q:
    """Filtro delle appartenenze ancora valide oggi.

    ``prefisso`` e' il percorso verso il modello dal queryset in uso, es.
    ``"memberships__"`` partendo da ``AccessGroup``.
    """
    oggi = timezone.localdate()
    return Q(**{f"{prefisso}scade_il__isnull": True}) | Q(**{f"{prefisso}scade_il__gte": oggi})
