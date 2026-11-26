"""Skill Matrix — verifica copertura minima AS/EN 9100 (1.13).

Confronta ogni ``SogliaCopertura`` configurata con gli abilitati **operativi**
disponibili ed evidenzia i gap. Riusa il resolver skill matrix per gli asset e
le abilitazioni MPQ attive per i processi. Le soglie sono definite
dall'organizzazione / flow-down cliente (nessuna percentuale fissa di norma).
"""
from __future__ import annotations

from ..models_skillmatrix import (
    AbilitazioneMacchina,
    ordinale_livello,
)


def _conta_asset(asset_id, livello_minimo) -> int:
    """Abilitati operativi su un asset con livello ≥ ``livello_minimo``.

    Operativo = in lista, stato attivo, conteggiabile nel carico, non ex dipendente.
    La soglia di livello è quella della soglia di copertura (non quella globale di
    config). Se la mansione ha competenze nel Mansionario, conta solo chi non è
    «non abilitato» (requisito formale mancante o competenza bloccante sotto il
    minimo): stessa valutazione di ``mansionario_competenze.valuta``.
    """
    from ..models import SkillMatrixConfig, VoceMacchinaCatalogo
    from .mansionario_competenze import NON_ABILITATO, Requisiti, valuta
    from .organigramma_albero import cessati_legacy_ids

    soglia_ord = ordinale_livello(livello_minimo)
    cessati = cessati_legacy_ids()
    candidati = [
        ab for ab in (AbilitazioneMacchina.objects.filter(asset_id=asset_id).prefetch_related("voci"))
        if ab.stato == AbilitazioneMacchina.STATO_ATTIVA and ab.in_lista and ab.conteggiabile_nel_carico
        and ab.ordinale >= soglia_ord and ab.legacy_anagrafica_id not in cessati
    ]
    voci_per_mansione: dict[int, list] = {}
    mansioni = {ab.competenza_id for ab in candidati if ab.competenza_id}
    if mansioni:
        for v in (VoceMacchinaCatalogo.objects.filter(mansione_id__in=sorted(mansioni), attiva=True)
                  .select_related("corso", "qualifica", "processo_mpq").order_by("ordine", "pk")):
            voci_per_mansione.setdefault(v.mansione_id, []).append(v)
    if not voci_per_mansione:
        return len(candidati)
    config = SkillMatrixConfig.get_instance()
    requisiti = Requisiti({ab.legacy_anagrafica_id for ab in candidati},
                          [v for vs in voci_per_mansione.values() for v in vs])
    n = 0
    for ab in candidati:
        voci = voci_per_mansione.get(ab.competenza_id)
        if voci and valuta(ab, voci=voci, config=config, requisiti=requisiti).esito == NON_ABILITATO:
            continue
        n += 1
    return n


def _conta_processo(processo_id) -> int:
    """Abilitazioni MPQ **attive** (qualificati) su un processo."""
    from ..models import AbilitazioneProcesso
    return (AbilitazioneProcesso.objects
            .filter(processo_id=processo_id, stato=AbilitazioneProcesso.STATO_ATTIVA)
            .count())


def valuta_soglia(soglia) -> dict:
    """Valuta una soglia: ``{soglia, disponibili, minimo, gap, coperta}``.

    - target asset → conta abilitati operativi ≥ livello_minimo sull'asset;
    - target processo → conta abilitazioni MPQ attive sul processo;
    - ambito libero → nessuna fonte automatica (``disponibili=None``, non valutabile).
    """
    if soglia.asset_id:
        disponibili = _conta_asset(soglia.asset_id, soglia.livello_minimo)
    elif soglia.processo_id:
        disponibili = _conta_processo(soglia.processo_id)
    else:
        # Ambito libero: nessun conteggio automatico (valutazione manuale).
        return {
            "soglia": soglia, "disponibili": None, "minimo": soglia.minimo_abilitati,
            "gap": None, "coperta": None,
        }
    gap = max(0, soglia.minimo_abilitati - disponibili)
    return {
        "soglia": soglia, "disponibili": disponibili,
        "minimo": soglia.minimo_abilitati, "gap": gap, "coperta": gap == 0,
    }


def valuta_copertura(soglie=None) -> list[dict]:
    """Valuta tutte le soglie attive (o l'elenco fornito), ordinate per gap desc."""
    from ..models import SogliaCopertura
    if soglie is None:
        soglie = (SogliaCopertura.objects
                  .filter(attiva=True)
                  .select_related("asset", "processo"))
    out = [valuta_soglia(s) for s in soglie]
    # Prima i gap più gravi (None in coda), poi per nome.
    out.sort(key=lambda r: (-(r["gap"] or 0), r["soglia"].nome))
    return out
