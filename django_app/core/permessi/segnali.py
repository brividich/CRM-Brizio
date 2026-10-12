"""Un cambio d'organigramma (ruoli o assegnazioni) azzera la cache dei team."""
from __future__ import annotations

from django.db.models.signals import post_delete, post_save


def _invalida(**_kwargs) -> None:
    from core.permessi.team import invalida_cache_team

    invalida_cache_team()


def collega_segnali() -> None:
    for sender in ("anagrafica.RuoloOperativo", "anagrafica.DipendenteRuoloOperativo"):
        post_save.connect(_invalida, sender=sender, dispatch_uid=f"permessi_team_save_{sender}")
        post_delete.connect(_invalida, sender=sender, dispatch_uid=f"permessi_team_delete_{sender}")
