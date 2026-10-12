"""Sistema unico dei permessi del portale: ruoli, matrice, visibilita' dei dati.

Uso nei moduli::

    from core.permessi import puo_fare, utenti_visibili, sistema_ruoli_attivo

    if sistema_ruoli_attivo():
        if not puo_fare(request, "ticket_it", "gestire", ticket):
            ...

Dettagli e procedura per un modulo nuovo: ``docs/ai/PERMESSI_RUOLI.md``.
Gli import sono pigri: questo pacchetto viene importato anche dall'autodiscover
dei ``registro_permessi.py`` e da ``core.legacy_utils``.
"""
from __future__ import annotations


def puo_fare(soggetto, modulo: str, azione: str, oggetto=None) -> bool:
    from core.permessi.motore import puo_fare as _puo_fare

    return _puo_fare(soggetto, modulo, azione, oggetto)


def decisione(soggetto, modulo: str, azione: str):
    from core.permessi.motore import decisione as _decisione

    return _decisione(soggetto, modulo, azione)


def utenti_visibili(soggetto, modulo: str, azione: str = "vedere"):
    from core.permessi.motore import utenti_visibili as _utenti_visibili

    return _utenti_visibili(soggetto, modulo, azione)


def sistema_ruoli_attivo() -> bool:
    from core.permessi.motore import sistema_ruoli_attivo as _attivo

    return _attivo()


def legacy_id(soggetto) -> int | None:
    """``utenti.id`` della persona (request o User), o None."""
    from core.permessi.motore import contesto_per

    return contesto_per(soggetto).legacy_user_id


def legacy_id_da_user(user) -> int | None:
    """``utenti.id`` di un utente Django qualsiasi (per i proprietari dei record)."""
    if user is None:
        return None
    profile = getattr(user, "profile", None)
    try:
        value = getattr(profile, "legacy_user_id", None) if profile is not None else None
    except Exception:
        value = None
    return int(value) if value else None


def legacy_id_da_user_id(user_id) -> int | None:
    """``utenti.id`` dall'id di un utente Django, senza caricare lo User."""
    if not user_id:
        return None
    from core.models import Profile

    value = Profile.objects.filter(user_id=int(user_id)).values_list("legacy_user_id", flat=True).first()
    return int(value) if value else None
