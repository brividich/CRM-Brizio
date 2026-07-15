"""Campi form condivisi per la scelta di utenti.

I dropdown su ``User`` mostrano di default ``str(user)`` == username. Nei moduli
rivolti agli operatori (Suggestion Corner, KICK-OFF, ...) va mostrato invece il
nome della persona. Questi campi centralizzano quella resa, con fallback allo
username quando nome/cognome non sono valorizzati.
"""
from __future__ import annotations

from django import forms


def user_display_label(user) -> str:
    """Nome visualizzato di un utente: "Nome Cognome", fallback allo username."""
    full = (user.get_full_name() or "").strip()
    return full or user.get_username()


class UserChoiceField(forms.ModelChoiceField):
    """``ModelChoiceField`` su ``User`` che mostra "Nome Cognome" non lo username."""

    def label_from_instance(self, obj):
        return user_display_label(obj)


class UserMultipleChoiceField(forms.ModelMultipleChoiceField):
    """Variante multi-selezione di :class:`UserChoiceField`."""

    def label_from_instance(self, obj):
        return user_display_label(obj)
