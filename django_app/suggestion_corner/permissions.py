"""Autorizzazione dati del modulo Suggestion Corner.

L'accesso al modulo è gated da ACL v2 (PERM_VIEW, vedi acl_bootstrap.py).
Qui si decide lo *scope dei dati*: il team SMS (Django Group) vede tutto, gli
altri vedono solo le proprie segnalazioni e gli incarichi assegnati.
"""
from __future__ import annotations

from django.db.models import Q

from .models import SuggestionCorner, SuggestionCornerConfig


def is_sms_team(user) -> bool:
    """True se l'utente è superuser o membro del Group SMS_TEAM configurato."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    group_name = SuggestionCornerConfig.load().sms_team_group_name
    return user.groups.filter(name=group_name).exists()


def visible_segnalazioni(user):
    """QuerySet delle segnalazioni visibili all'utente.

    - team SMS / superuser: tutte;
    - altri: create da loro (created_by) o a loro assegnate (incaricato/controllore).
    """
    qs = SuggestionCorner.objects.all()
    if is_sms_team(user):
        return qs
    return qs.filter(
        Q(created_by=user) | Q(incaricato=user) | Q(controllore=user)
    ).distinct()
