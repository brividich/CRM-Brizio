"""F5 — Continuità operativa: regola di sospensione automatica (MT CN 65 §3.7).

Quando la continuità di un processo critico è **persa** (ultima esecuzione oltre la
finestra), l'abilitazione collegata viene **sospesa** automaticamente: è l'**unica
regola bloccante** della skill matrix. Al recupero della continuità l'abilitazione
sospesa *per questo motivo* viene riattivata.

⛔ La sorgente di ``ultima_esecuzione`` (esecuzione reale di produzione) NON è
cablata qui: va popolata in un passo successivo, dopo approvazione (vedi BUILD_LOG
F5). Questo modulo lavora su ``ContinuitaOperativa.ultima_esecuzione`` qualunque sia
la sua provenienza, e calcola lo stato via ``ContinuitaOperativa.stato()``.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    ContinuitaOperativa,
)

# Marcatore in nota: distingue le sospensioni dovute alla continuità (riattivabili
# in automatico) da quelle manuali/di altra origine (che NON vanno riattivate).
MARKER = "[continuita-persa]"


def applica_sospensioni(*, oggi=None, apply: bool = True) -> dict:
    """Sospende le abilitazioni con continuità persa, riattiva quelle recuperate.

    Idempotente. Con ``apply=False`` calcola soltanto il piano. Ritorna conteggi.
    """
    oggi = oggi or timezone.localdate()
    stats = {
        "apply": apply,
        "persa": 0, "da_sospendere": 0, "sospese": 0,
        "da_riattivare": 0, "riattivate": 0,
    }
    qs = ContinuitaOperativa.objects.select_related("abilitazione", "processo")

    with transaction.atomic():
        for co in qs:
            ab = co.abilitazione
            if ab is None:
                continue
            stato = co.stato(oggi=oggi)
            if stato == ContinuitaOperativa.STATO_PERSA:
                stats["persa"] += 1
                if ab.stato == AbilitazioneMacchina.STATO_ATTIVA:
                    stats["da_sospendere"] += 1
                    if apply:
                        ab.stato = AbilitazioneMacchina.STATO_SOSPESA
                        ab.note = f"{ab.note} {MARKER}".strip()
                        ab.save(update_fields=["stato", "note", "updated_at"])
                        AbilitazioneMacchinaStorico.objects.create(
                            legacy_anagrafica_id=ab.legacy_anagrafica_id,
                            asset_id=ab.asset_id, livello=ab.livello,
                            data_rilevazione=oggi,
                            fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
                            note=f"Sospensione automatica: continuità persa ({co.processo.nome})",
                        )
                        stats["sospese"] += 1
            else:
                # Continuità mantenuta/in_scadenza/na: riattiva SOLO se l'avevamo
                # sospesa noi per continuità persa (marcatore presente).
                if ab.stato == AbilitazioneMacchina.STATO_SOSPESA and MARKER in (ab.note or ""):
                    stats["da_riattivare"] += 1
                    if apply:
                        ab.stato = AbilitazioneMacchina.STATO_ATTIVA
                        ab.note = (ab.note or "").replace(MARKER, "").strip()
                        ab.save(update_fields=["stato", "note", "updated_at"])
                        AbilitazioneMacchinaStorico.objects.create(
                            legacy_anagrafica_id=ab.legacy_anagrafica_id,
                            asset_id=ab.asset_id, livello=ab.livello,
                            data_rilevazione=oggi,
                            fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
                            note=f"Riattivazione: continuità recuperata ({co.processo.nome})",
                        )
                        stats["riattivate"] += 1
    return stats


def riepilogo_continuita(*, oggi=None) -> dict:
    """Conteggio per stato (mantenuta/in_scadenza/persa/na) — per KPI/cruscotto."""
    oggi = oggi or timezone.localdate()
    out = {
        ContinuitaOperativa.STATO_MANTENUTA: 0,
        ContinuitaOperativa.STATO_IN_SCADENZA: 0,
        ContinuitaOperativa.STATO_PERSA: 0,
        ContinuitaOperativa.STATO_NA: 0,
    }
    for co in ContinuitaOperativa.objects.select_related("processo"):
        out[co.stato(oggi=oggi)] += 1
    return out
