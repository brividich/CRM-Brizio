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


# --- Autorizzazione azioni FSM (sessione 3b) --------------------------------
# Il gate ACL (PERM_VIEW) lascia entrare ogni utente autenticato; qui si decide
# CHI può eseguire una data transizione. SMS_TEAM/superuser gestisce l'intero
# workflow; l'incaricato assegnato può completare il DO; il controllore
# assegnato può eseguire il CHECK.

def is_incaricato(user, seg) -> bool:
    return bool(user and user.is_authenticated and seg.incaricato_id == user.id)


def is_controllore(user, seg) -> bool:
    return bool(user and user.is_authenticated and seg.controllore_id == user.id)


def can_complete_do(user, seg) -> bool:
    """Completa DO: SMS_TEAM/superuser oppure l'incaricato assegnato."""
    return is_sms_team(user) or is_incaricato(user, seg)


def can_check(user, seg) -> bool:
    """Azioni CHECK: SMS_TEAM/superuser oppure il controllore assegnato."""
    return is_sms_team(user) or is_controllore(user, seg)
