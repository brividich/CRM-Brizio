"""F3 — Resolver bridge read-only della Skill Matrix MOD.187.

Espone query **di sola lettura** che altri moduli (primo cliente: i carichi
macchina, Fase B "overlay disponibilità") consumano senza accoppiarsi ai modelli
interni. Nessuna scrittura qui dentro.

Convenzioni:
- il dipendente è sempre ``legacy_anagrafica_id`` (int);
- ``asset`` può essere un ``assets.Asset`` o direttamente il suo id;
- la soglia "operativo" e l'inclusione dei CAR come riserva vengono da
  ``SkillMatrixConfig`` (override per-chiamata possibili).

Punto d'aggancio Fase B: ``pool_abilitati`` / ``livello_operatore`` alimenteranno
l'overlay di disponibilità nel Gantt carichi macchina (chi può stare su quella
macchina, a che livello), senza che i carichi importino i modelli skill matrix.
"""
from __future__ import annotations

from ..models import (
    AbilitazioneMacchina,
    CompetenzaSkm,
    ORDINE_LIVELLO,
    SkillMatrixConfig,
    ordinale_livello,
)


def _asset_id(asset) -> int | None:
    """Accetta un Asset o il suo id."""
    return getattr(asset, "id", asset)


def _livelli_da_ordinale(soglia_ordinale: int) -> list[str]:
    """Codici livello con ordinale >= soglia (per filtrare in DB senza derivati)."""
    return [lv for lv, ordn in ORDINE_LIVELLO.items() if ordn >= soglia_ordinale]


def pool_abilitati(asset, livello_min=None, *, includi_riserva=None, config=None) -> list[int]:
    """``legacy_anagrafica_id`` operativi su ``asset`` (pool capacità).

    Operativo = abilitazione attiva, in lista, livello ≥ soglia. I CAR
    (``conteggiabile_nel_carico=False``) sono esclusi salvo ``includi_riserva``.
    """
    aid = _asset_id(asset)
    if aid is None:
        return []
    config = config or SkillMatrixConfig.get_instance()
    soglia = ordinale_livello(livello_min) if livello_min else config.soglia_operativa_ordinale
    if includi_riserva is None:
        includi_riserva = config.includi_car_come_riserva

    qs = AbilitazioneMacchina.objects.filter(
        asset_id=aid,
        stato=AbilitazioneMacchina.STATO_ATTIVA,
        in_lista=True,
        livello__in=_livelli_da_ordinale(soglia),
    )
    if not includi_riserva:
        qs = qs.filter(conteggiabile_nel_carico=True)
    return list(qs.values_list("legacy_anagrafica_id", flat=True))


def livello_operatore(legacy_anagrafica_id: int, asset) -> str | None:
    """Livello I/L/U/O del dipendente su ``asset`` (None se non in lista/assente)."""
    aid = _asset_id(asset)
    if aid is None:
        return None
    ab = (
        AbilitazioneMacchina.objects
        .filter(legacy_anagrafica_id=legacy_anagrafica_id, asset_id=aid, in_lista=True)
        .only("livello")
        .first()
    )
    return ab.livello if ab else None


def kpi_uomo_solo(asset, *, config=None) -> dict:
    """Rischio uomo-solo su ``asset``: < ``soglia_uomo_solo`` persone operative."""
    config = config or SkillMatrixConfig.get_instance()
    n = len(pool_abilitati(asset, config=config))
    return {
        "n_operativi": n,
        "soglia": config.soglia_uomo_solo,
        "a_rischio": n < config.soglia_uomo_solo,
    }


def _asset_macchina_ids(reparto=None) -> list[int]:
    """Asset-macchina MOD.187 (CompetenzaSkm con asset risolto), opz. per reparto."""
    qs = CompetenzaSkm.objects.filter(
        tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False,
    )
    if reparto:
        qs = qs.filter(asset__reparto=reparto)
    return list(qs.values_list("asset_id", flat=True))


def macchine_scoperte(reparto=None) -> list[int]:
    """Asset-macchina senza nessun abilitato in lista (attivo) — copertura zero."""
    ids = _asset_macchina_ids(reparto)
    if not ids:
        return []
    coperti = set(
        AbilitazioneMacchina.objects
        .filter(asset_id__in=ids, in_lista=True, stato=AbilitazioneMacchina.STATO_ATTIVA)
        .values_list("asset_id", flat=True)
    )
    return [aid for aid in ids if aid not in coperti]


def prontezza_squadra(reparto=None, *, config=None) -> dict:
    """Prontezza: quota di abilitazioni in lista che sono operative (≥ soglia).

    Ritorna conteggi e percentuale; fail-safe a denominatore zero.
    """
    config = config or SkillMatrixConfig.get_instance()
    ids = _asset_macchina_ids(reparto)
    base = AbilitazioneMacchina.objects.filter(
        asset_id__in=ids, in_lista=True, stato=AbilitazioneMacchina.STATO_ATTIVA,
    ) if ids else AbilitazioneMacchina.objects.none()

    totale = base.count()
    operativi = base.filter(
        conteggiabile_nel_carico=True,
        livello__in=_livelli_da_ordinale(config.soglia_operativa_ordinale),
    ).count()
    pct = round(operativi * 100.0 / totale, 1) if totale else 0.0
    return {
        "totale_in_lista": totale,
        "operativi": operativi,
        "percentuale": pct,
        "n_macchine": len(ids),
    }
