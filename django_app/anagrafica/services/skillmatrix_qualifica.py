"""Skill Matrix MOD.187 — gate qualificante I→L (1.12).

Un'abilitazione a livello ≥ L (INTERMEDIO) su una macchina è consentita solo se
il dipendente ha il **corso qualificante** della macchina completato e valido
(``TrainingDeadline``), dichiarato su ``CompetenzaSkm.corso_qualificante``.
Allineato EN 4179 / Part 145: qualifica = training **verificato** con evidenza.

Lo stato è *derivato+validato*: l'override resta possibile (responsabile) ma va
**tracciato** sullo storico append-only (``AbilitazioneMacchinaStorico``), mai
applicato silenziosamente.
"""
from __future__ import annotations

from ..models_skillmatrix import (
    LivelloSkm,
    SkillMatrixConfig,
    ordinale_livello,
)

# Stati TrainingDeadline che valgono "corso completato e valido".
_STATI_VALIDI = {"VALIDO", "IN_SCADENZA_30", "IN_SCADENZA_90", "UNA_TANTUM"}
_ORD_L = ordinale_livello(LivelloSkm.INTERMEDIO)  # soglia del gate: L=2


def corso_qualificante_asset(asset_id):
    """``TrainingCourse`` qualificante dichiarato per l'asset (None se assente)."""
    from ..models import CompetenzaSkm
    comp = (
        CompetenzaSkm.objects
        .filter(asset_id=asset_id, corso_qualificante__isnull=False)
        .select_related("corso_qualificante")
        .first()
    )
    return comp.corso_qualificante if comp else None


def corso_valido(legacy_id, corso) -> bool:
    """True se la persona ha il corso completato e valido (TrainingDeadline)."""
    if corso is None or not legacy_id:
        return False
    from ..models import TrainingDeadline
    d = (TrainingDeadline.objects
         .filter(legacy_anagrafica_id=legacy_id, corso=corso)
         .only("stato_scadenza").first())
    return bool(d and d.stato_scadenza in _STATI_VALIDI)


def valida_livello(legacy_id, asset_id, livello, *, corso=None) -> dict:
    """Verifica se ``livello`` è ammesso per (persona, asset) senza override.

    Ritorna ``{ammesso, richiede_corso, corso, motivo}``. Livelli < L sono sempre
    ammessi. Livelli ≥ L: ammessi solo se il corso qualificante — se dichiarato —
    è completato e valido; se nessun corso è dichiarato non c'è nulla da bloccare.
    """
    if ordinale_livello(livello) < _ORD_L:
        return {"ammesso": True, "richiede_corso": False, "corso": None, "motivo": ""}
    if corso is None:
        corso = corso_qualificante_asset(asset_id)
    if corso is None:
        return {"ammesso": True, "richiede_corso": False, "corso": None, "motivo": ""}
    if corso_valido(legacy_id, corso):
        return {"ammesso": True, "richiede_corso": True, "corso": corso, "motivo": ""}
    return {
        "ammesso": False, "richiede_corso": True, "corso": corso,
        "motivo": f"Corso qualificante «{corso.titolo}» non completato o non valido.",
    }


def imposta_livello(abil, livello, *, forza=False, attore=None, oggi=None):
    """Applica un livello a un'``AbilitazioneMacchina`` rispettando il gate I→L.

    - gate soddisfatto → applica e basta;
    - gate violato e ``forza=False`` → ``ValueError`` (nessuna modifica);
    - gate violato e ``forza=True`` → applica e registra l'**eccezione** sullo
      storico append-only (``AbilitazioneMacchinaStorico``, fonte manuale).

    Ritorna l'abilitazione salvata.
    """
    from django.utils import timezone
    from ..models import AbilitazioneMacchinaStorico
    oggi = oggi or timezone.localdate()
    esito = valida_livello(abil.legacy_anagrafica_id, abil.asset_id, livello)
    if not esito["ammesso"] and not forza:
        raise ValueError(esito["motivo"])
    abil.livello = livello
    abil.save(update_fields=["livello", "updated_at"])
    if not esito["ammesso"] and forza:
        nota = f"OVERRIDE gate I→L: {esito['motivo']}"
        AbilitazioneMacchinaStorico.objects.create(
            legacy_anagrafica_id=abil.legacy_anagrafica_id,
            asset=abil.asset, livello=livello, data_rilevazione=oggi,
            fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
            note=nota[:255],
        )
    return abil


def conta_operativi_per_asset(asset_ids) -> dict[int, int]:
    """Numero di abilitazioni **operative** (≥ soglia, in lista, attive, in pool)
    per ciascun asset — usato nell'header colonna della matrice (contatore 1.12).
    """
    from ..models import AbilitazioneMacchina
    asset_ids = list(asset_ids)
    if not asset_ids:
        return {}
    soglia = SkillMatrixConfig.get_instance().soglia_operativa_ordinale
    counts: dict[int, int] = {aid: 0 for aid in asset_ids}
    for ab in (AbilitazioneMacchina.objects
               .filter(asset_id__in=asset_ids)
               .only("asset_id", "livello", "in_lista", "stato", "conteggiabile_nel_carico")):
        if ab.is_operativa(soglia):
            counts[ab.asset_id] = counts.get(ab.asset_id, 0) + 1
    return counts
