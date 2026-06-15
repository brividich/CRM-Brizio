"""AB1-D — Semaforo/alert sui saldi ratei ferie (SaldoCedolino).

Valuta il residuo ferie di un saldo mensile e assegna un semaforo per la vista HR
``ratei_list``. **Solo HR/amministrazione**: niente esposizione lato dipendente.

Due condizioni di allerta sul residuo ferie (in ore):
- **negativo**: ferie godute oltre il maturato (anticipo) → rosso;
- **accumulo eccessivo**: residuo oltre la soglia massima → rosso (obbligo di
  godimento, D.Lgs 66/2003); in avvicinamento → giallo.

Soglie **configurabili senza migration** via ``SiteConfig``:
- ``ratei_ferie_alert_ore_max``  (default 200)
- ``ratei_ferie_alert_ore_warn`` (default 160)
"""
from __future__ import annotations

_DEFAULT_ORE_MAX = 200
_DEFAULT_ORE_WARN = 160


def _cfg_float(chiave: str, default: float) -> float:
    from core.models import SiteConfig

    raw = (SiteConfig.get(chiave, "") or "").strip().replace(",", ".")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def soglie_ratei() -> dict[str, float]:
    ore_max = _cfg_float("ratei_ferie_alert_ore_max", _DEFAULT_ORE_MAX)
    ore_warn = _cfg_float("ratei_ferie_alert_ore_warn", _DEFAULT_ORE_WARN)
    if ore_warn > ore_max:
        ore_warn = ore_max
    return {"ore_max": ore_max, "ore_warn": ore_warn}


def valuta_residuo_ferie(residui_ore, soglie: dict[str, float]) -> dict:
    """Ritorna ``{"tono": rosso|giallo|verde, "motivo": str}`` per un residuo ferie."""
    if residui_ore is None:
        return {"tono": "verde", "motivo": ""}
    try:
        r = float(residui_ore)
    except (TypeError, ValueError):
        return {"tono": "verde", "motivo": ""}
    if r < 0:
        return {"tono": "rosso", "motivo": "Ferie negative (anticipo)"}
    if r >= soglie["ore_max"]:
        return {"tono": "rosso", "motivo": "Accumulo ferie oltre soglia"}
    if r >= soglie["ore_warn"]:
        return {"tono": "giallo", "motivo": "Accumulo ferie in avvicinamento"}
    return {"tono": "verde", "motivo": ""}


def filtro_allerta_q(soglie: dict[str, float]):
    """Q per filtrare i ``SaldoCedolino`` in allerta (negativi o oltre soglia warn)."""
    from django.db.models import Q

    return Q(ferie_residui__lt=0) | Q(ferie_residui__gte=soglie["ore_warn"])
