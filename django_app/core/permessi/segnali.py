"""Un cambio d'organigramma (ruoli, assegnazioni, ruoli del portale collegati) azzera le cache.

Dall'organigramma dipendono il team e i ruoli del portale che arrivano in
automatico: si invalidano entrambi (``invalida_permessi`` azzera anche il team).
"""
from __future__ import annotations

from django.db.models.signals import m2m_changed, post_delete, post_save


def _invalida(**_kwargs) -> None:
    from core.permessi.cache import invalida_permessi

    invalida_permessi()


def _invalida_m2m(action=None, **_kwargs) -> None:
    if action in {"post_add", "post_remove", "post_clear"}:
        _invalida()


def collega_segnali() -> None:
    for sender in ("anagrafica.RuoloOperativo", "anagrafica.DipendenteRuoloOperativo"):
        post_save.connect(_invalida, sender=sender, dispatch_uid=f"permessi_team_save_{sender}")
        post_delete.connect(_invalida, sender=sender, dispatch_uid=f"permessi_team_delete_{sender}")
    from anagrafica.models import RuoloOperativo

    m2m_changed.connect(
        _invalida_m2m,
        sender=RuoloOperativo.profili_permessi.through,
        dispatch_uid="permessi_organigramma_profili",
    )
