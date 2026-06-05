"""Servizio condiviso di lettura dei Ruoli Operativi dall'anagrafica.

Fonte unica del catalogo ruoli e delle assegnazioni utente->ruolo:
- catalogo: ``anagrafica.RuoloOperativo`` (attivi);
- assegnazioni: ``anagrafica.DipendenteRuoloOperativo`` su ``legacy_anagrafica_id``.

Questo helper centralizza il ponte legacy<->Django cosi i singoli moduli
(anomalie, tasks, ...) non duplicano la logica di risoluzione:

    Django user --(core.Profile.legacy_user_id)--> UtenteLegacy.id
               --(anagrafica_dipendenti.utente_id)--> AnagraficaDipendente.id
               (= DipendenteRuoloOperativo.legacy_anagrafica_id)

I ruoli NON sono una primitiva ACL: servono come ruoli funzionali interni
ai moduli. L'accesso al modulo resta governato dall'ACL esistente.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model


def get_active_roles():
    """Catalogo dei Ruoli Operativi attivi (queryset ordinato per nome)."""
    from anagrafica.models import RuoloOperativo

    return RuoloOperativo.objects.filter(is_active=True).order_by("nome")


def get_legacy_anagrafica_id(django_user) -> int | None:
    """Risolve l'id anagrafica (``AnagraficaDipendente.id``) di un utente Django.

    Restituisce ``None`` se l'utente non e' collegato a un dipendente di anagrafica.
    Non solleva eccezioni: in caso di DB legacy non disponibile torna ``None``.
    """
    from django.db import DatabaseError

    from core.legacy_models import AnagraficaDipendente

    if django_user is None or not getattr(django_user, "is_authenticated", False):
        return None

    profile = getattr(django_user, "profile", None)
    legacy_user_id = getattr(profile, "legacy_user_id", None) if profile else None
    if not legacy_user_id:
        return None

    try:
        anagrafica = (
            AnagraficaDipendente.objects.filter(utente_id=int(legacy_user_id))
            .only("id")
            .first()
        )
    except DatabaseError:
        return None
    return int(anagrafica.id) if anagrafica is not None else None


def get_roles_for_user(django_user):
    """Ruoli Operativi (attivi) ricoperti da un utente Django.

    Restituisce un queryset di ``RuoloOperativo`` (eventualmente vuoto).
    """
    from anagrafica.models import DipendenteRuoloOperativo, RuoloOperativo

    anagrafica_id = get_legacy_anagrafica_id(django_user)
    if anagrafica_id is None:
        return RuoloOperativo.objects.none()

    ruolo_ids = (
        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=anagrafica_id)
        .values_list("ruolo_id", flat=True)
    )
    return RuoloOperativo.objects.filter(id__in=list(ruolo_ids), is_active=True).order_by("nome")


def get_role_ids_for_user(django_user) -> set[int]:
    """Insieme degli id ``RuoloOperativo`` (attivi) ricoperti dall'utente Django."""
    return set(get_roles_for_user(django_user).values_list("id", flat=True))


def get_anagrafica_ids_for_role(ruolo_id: int) -> list[int]:
    """``legacy_anagrafica_id`` dei dipendenti che ricoprono il ruolo dato."""
    from anagrafica.models import DipendenteRuoloOperativo

    return list(
        DipendenteRuoloOperativo.objects.filter(ruolo_id=int(ruolo_id))
        .values_list("legacy_anagrafica_id", flat=True)
    )


def get_users_for_role(ruolo_id: int):
    """Utenti Django che ricoprono il Ruolo Operativo dato.

    Mappa gli ``legacy_anagrafica_id`` assegnati al ruolo verso gli account
    Django attraverso ``AnagraficaDipendente.utente_id`` -> ``Profile.legacy_user_id``.
    Restituisce un queryset di User (eventualmente vuoto).
    """
    from django.db import DatabaseError

    from core.legacy_models import AnagraficaDipendente

    User = get_user_model()
    anagrafica_ids = get_anagrafica_ids_for_role(ruolo_id)
    if not anagrafica_ids:
        return User.objects.none()

    try:
        legacy_user_ids = list(
            AnagraficaDipendente.objects.filter(id__in=anagrafica_ids, utente_id__isnull=False)
            .values_list("utente_id", flat=True)
        )
    except DatabaseError:
        return User.objects.none()

    if not legacy_user_ids:
        return User.objects.none()

    return User.objects.filter(
        profile__legacy_user_id__in=legacy_user_ids
    ).order_by("last_name", "first_name", "username")


def get_roster_by_role():
    """Riepilogo catalogo -> utenti, utile per le pagine Impostazioni dei moduli.

    Restituisce una lista di dict::

        [{"ruolo": <RuoloOperativo>, "users": [<User>, ...]}, ...]
    """
    rows = []
    for ruolo in get_active_roles():
        rows.append({"ruolo": ruolo, "users": list(get_users_for_role(ruolo.id))})
    return rows
