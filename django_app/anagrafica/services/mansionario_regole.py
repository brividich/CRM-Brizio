"""Regole di calcolo del Mansionario: soglia operativa, regola multi-competenza, uomo solo.

I tre valori stanno in ``SkillMatrixConfig`` (gli stessi della skill matrix e
del pool capacità). Il livello sulla mansione di chi ha le competenze valutate
è **scritto** su ``AbilitazioneMacchina.livello`` al momento della valutazione:
cambiare la regola senza ricalcolare lascerebbe livelli calcolati con la
regola vecchia. Per questo qui si lavora in due passi, come l'import Excel:

- ``simula``: con i valori proposti, chi cambierebbe livello o esito e quante
  mansioni resterebbero senza operativi — senza salvare niente;
- ``applica``: salva i valori e riscrive i livelli calcolati, con lo storico.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    LivelloSkm,
    SkillMatrixConfig,
    VoceMacchinaCatalogo,
    ordinale_livello,
)
from . import mansionario_competenze as comp

MAX_RIGHE = 300


@dataclass
class Impatto:
    cambi: list[dict] = field(default_factory=list)     # persone con livello o esito diverso
    n_cambi: int = 0
    operativi_prima: int = 0
    operativi_dopo: int = 0
    scoperte_prima: int = 0
    scoperte_dopo: int = 0
    uomo_solo_prima: int = 0
    uomo_solo_dopo: int = 0
    valutate: int = 0                                   # persone con competenze valutate (livello calcolato)


def valida(soglia: str, regola: str, uomo_solo) -> tuple[str, str, int]:
    soglia = (soglia or "").strip().upper()
    if soglia not in dict(LivelloSkm.choices):
        raise ValueError("Scegli la soglia operativa (I, L, U oppure O).")
    if regola not in dict(SkillMatrixConfig.REGOLA_MULTIVOCE_CHOICES):
        raise ValueError("Scegli la regola di calcolo.")
    try:
        uomo_solo = int(uomo_solo)
    except (TypeError, ValueError):
        raise ValueError("Il minimo di operativi deve essere un numero.") from None
    if not 1 <= uomo_solo <= 20:
        raise ValueError("Il minimo di operativi va da 1 a 20.")
    return soglia, regola, uomo_solo


def _config_proposta(soglia: str, regola: str, uomo_solo: int) -> SkillMatrixConfig:
    nuova = copy.copy(SkillMatrixConfig.get_instance())
    nuova.soglia_operativa, nuova.regola_multivoce, nuova.soglia_uomo_solo = soglia, regola, uomo_solo
    return nuova


def _abilitazioni():
    return list(
        AbilitazioneMacchina.objects.filter(in_lista=True, competenza__isnull=False, competenza__attiva=True,
                                            competenza__tipo__in=("macchina", "processo"))
        .select_related("competenza").prefetch_related("voci")
    )


def _voci(abil) -> dict[int, list]:
    out: dict[int, list] = {}
    for v in (VoceMacchinaCatalogo.objects.filter(mansione_id__in={a.competenza_id for a in abil}, attiva=True)
              .select_related("corso", "qualifica", "processo_mpq").order_by("ordine", "pk")):
        out.setdefault(v.mansione_id, []).append(v)
    return out


def _calcola(soglia: str, regola: str, uomo_solo: int):
    """Per ogni persona in lista: livello ed esito oggi e con le regole proposte."""
    attuale = SkillMatrixConfig.get_instance()
    proposta = _config_proposta(soglia, regola, uomo_solo)
    abil = _abilitazioni()
    voci = _voci(abil)
    requisiti = comp.Requisiti({a.legacy_anagrafica_id for a in abil}, [v for vs in voci.values() for v in vs])
    righe = []
    for a in abil:
        vs = voci.get(a.competenza_id, [])
        prima = comp.valuta(a, voci=vs, config=attuale, requisiti=requisiti)
        dopo = comp.valuta(a, voci=vs, config=proposta, requisiti=requisiti)
        # Con competenze il livello sulla mansione è quello calcolato; senza, resta quello messo a mano.
        livello_dopo = (dopo.livello or a.livello) if vs else a.livello
        righe.append({"abilitazione": a, "voci": vs, "prima": prima, "dopo": dopo,
                      "livello_prima": a.livello, "livello_dopo": livello_dopo})
    return attuale, proposta, righe


def _conta_mansioni(righe, chiave_livello: str, config: SkillMatrixConfig) -> tuple[int, int, int]:
    soglia = config.soglia_operativa_ordinale
    per_mansione: dict[int, int] = {}
    operativi = 0
    for r in righe:
        a = r["abilitazione"]
        per_mansione.setdefault(a.competenza_id, 0)
        # Stesse condizioni di AbilitazioneMacchina.is_operativa, sul livello indicato.
        conta = a.stato == AbilitazioneMacchina.STATO_ATTIVA and a.conteggiabile_nel_carico
        if conta and ordinale_livello(r[chiave_livello]) >= soglia:
            per_mansione[a.competenza_id] += 1
            operativi += 1
    from ..models import CompetenzaSkm
    tutte = CompetenzaSkm.objects.filter(attiva=True, tipo__in=("macchina", "processo")).values_list("pk", flat=True)
    conti = [per_mansione.get(pk, 0) for pk in tutte]
    return operativi, sum(1 for n in conti if n == 0), sum(1 for n in conti if n < config.soglia_uomo_solo)


def simula(soglia: str, regola: str, uomo_solo) -> Impatto:
    soglia, regola, uomo_solo = valida(soglia, regola, uomo_solo)
    attuale, proposta, righe = _calcola(soglia, regola, uomo_solo)
    imp = Impatto()
    imp.operativi_prima, imp.scoperte_prima, imp.uomo_solo_prima = _conta_mansioni(righe, "livello_prima", attuale)
    imp.operativi_dopo, imp.scoperte_dopo, imp.uomo_solo_dopo = _conta_mansioni(righe, "livello_dopo", proposta)
    imp.valutate = sum(1 for r in righe if r["voci"])
    cambiate = [r for r in righe if r["livello_prima"] != r["livello_dopo"] or r["prima"].esito != r["dopo"].esito]
    imp.n_cambi = len(cambiate)
    if cambiate:
        from core import naming
        from core.legacy_anagrafica import fetch_anagrafica_rows

        mostrate = cambiate[:MAX_RIGHE]
        nomi = {int(x["id"]): naming.nome_completo(x.get("nome"), x.get("cognome"))
                for x in fetch_anagrafica_rows(ids=list({r["abilitazione"].legacy_anagrafica_id for r in mostrate}))}
        imp.cambi = sorted(({
            "nome": nomi.get(r["abilitazione"].legacy_anagrafica_id, f"#{r['abilitazione'].legacy_anagrafica_id}"),
            "mansione": r["abilitazione"].competenza,
            "livello_prima": r["livello_prima"], "livello_dopo": r["livello_dopo"],
            "esito_prima": r["prima"].esito_label, "esito_dopo": r["dopo"].esito_label,
            "sale": ordinale_livello(r["livello_dopo"]) > ordinale_livello(r["livello_prima"]),
        } for r in mostrate), key=lambda x: (x["mansione"].nome.casefold(), x["nome"].casefold()))
    return imp


@transaction.atomic
def applica(soglia: str, regola: str, uomo_solo, *, user=None) -> dict:
    """Salva le regole e riscrive i livelli calcolati che cambiano, con lo storico."""
    soglia, regola, uomo_solo = valida(soglia, regola, uomo_solo)
    config = SkillMatrixConfig.get_instance()
    prima = {"soglia": config.soglia_operativa, "regola": config.regola_multivoce, "uomo_solo": config.soglia_uomo_solo}
    _attuale, _proposta, righe = _calcola(soglia, regola, uomo_solo)
    config.soglia_operativa, config.regola_multivoce, config.soglia_uomo_solo = soglia, regola, uomo_solo
    config.save(update_fields=["soglia_operativa", "regola_multivoce", "soglia_uomo_solo", "updated_at"])
    oggi = timezone.localdate()
    ricalcolati = 0
    for r in righe:
        a = r["abilitazione"]
        if not r["voci"] or not r["livello_dopo"] or r["livello_dopo"] == a.livello:
            continue
        a.livello = r["livello_dopo"]
        a.save(update_fields=["livello", "updated_at"])
        AbilitazioneMacchinaStorico.objects.create(
            legacy_anagrafica_id=a.legacy_anagrafica_id, asset_id=a.asset_id, competenza_id=a.competenza_id,
            livello=a.livello, data_rilevazione=oggi, fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
            note="Mansionario: ricalcolo per cambio regole",
        )
        ricalcolati += 1
    return {"prima": prima, "dopo": {"soglia": soglia, "regola": regola, "uomo_solo": uomo_solo},
            "ricalcolati": ricalcolati}
