"""Il tipo di un asset (``asset_type``) deriva dalla «Famiglia tecnica» della sua categoria.

I form lo applicano al salvataggio del singolo asset; qui si applica agli asset già
dentro una categoria quando in Impostazioni se ne cambia la famiglia. Vale solo per gli
asset assegnati direttamente alla categoria: le sottocategorie hanno la loro famiglia.
"""
from __future__ import annotations

from django.utils import timezone

from ..models import Asset, AssetCategory

# I prodotti chimici sono legati all'anagrafica delle schede di sicurezza: il tipo
# non si cambia in blocco, né verso né da «Prodotto chimico».
_NON_IN_BLOCCO = {Asset.TYPE_CHEMICAL}


def asset_da_allineare(category: AssetCategory):
    """Asset della categoria con un tipo diverso dalla sua famiglia (esclusi i prodotti chimici)."""
    if category.base_asset_type in _NON_IN_BLOCCO:
        return Asset.objects.none()
    return (
        Asset.objects.filter(asset_category=category)
        .exclude(asset_type=category.base_asset_type)
        .exclude(asset_type__in=_NON_IN_BLOCCO)
    )


def allinea_asset(category: AssetCategory, famiglia_prima: str) -> int:
    """Dopo un cambio di famiglia porta gli asset della categoria al nuovo tipo. Ritorna quanti."""
    if famiglia_prima == category.base_asset_type or famiglia_prima in _NON_IN_BLOCCO:
        return 0
    return asset_da_allineare(category).update(asset_type=category.base_asset_type, updated_at=timezone.now())
