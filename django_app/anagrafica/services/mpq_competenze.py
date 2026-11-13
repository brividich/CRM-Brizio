"""MOD.128 → Mansionario: assegnazione e livello sulla mansione collegata al ruolo del processo.

Un ruolo del processo può essere collegato a una mansione della skill matrix
(``RuoloProcesso.competenza``, es. «Operatore macchina» → mansione «Foratura CN»).
Per chi ha quel ruolo su un processo (abilitazione attiva o sospesa):

- se non è in lista sulla mansione, ci viene messo (assegnazione), con livello
  «I» se non è ancora qualificato, con il livello operativo minimo se lo è;
- se è qualificato e il livello è sotto la soglia operativa, sale alla soglia;
- se non è (più) qualificato e il livello è operativo, scende sotto la soglia:
  non risulta operativo per errore.

Le mansioni con competenze nel Mansionario hanno il livello calcolato dalle
valutazioni (``competenze_ricalcolo``): qui si fa solo l'assegnazione, il livello
lo decide quel calcolo. Ogni cambio va nello storico delle abilitazioni (fonte
«automatico»). Gira con il ricalcolo delle scadenze (dopo i salvataggi e la notte)
e dal pulsante «Aggiorna mansioni e livelli» del processo.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def allinea(legacy_ids=None, *, processi_ids=None, oggi=None, applica: bool = True) -> dict:
    """Riallinea assegnazioni e livelli. ``None`` = tutti. Ritorna conteggi e cambi."""
    from ..models_mpq import AbilitazioneProcesso, ProcessoQualificato, RuoloProcesso
    from ..models_skillmatrix import (AbilitazioneMacchina, AbilitazioneMacchinaStorico, SkillMatrixConfig,
                                      VoceMacchinaCatalogo, ordinale_livello)
    from .mansionario_competenze import _DA_ORDINALE
    from .mpq_persone import qualificati

    oggi = oggi or timezone.localdate()
    esito = {"assegnate": 0, "alzate": 0, "abbassate": 0, "cambi": []}
    ruoli = RuoloProcesso.objects.filter(competenza__isnull=False,
                                         processo__stato=ProcessoQualificato.STATO_ATTIVO)
    if processi_ids is not None:
        ruoli = ruoli.filter(processo_id__in=list(processi_ids))
    ruoli = {r.pk: r for r in ruoli.select_related("competenza", "processo")}
    if not ruoli:
        return esito
    abil = (AbilitazioneProcesso.objects
            .filter(ruoli_processo__in=list(ruoli), nominativo_esterno="",
                    stato__in=[AbilitazioneProcesso.STATO_ATTIVA, AbilitazioneProcesso.STATO_SOSPESA])
            .exclude(legacy_anagrafica_id=0).prefetch_related("ruoli_processo").distinct())
    if legacy_ids is not None:
        ids = [int(i) for i in legacy_ids if i]
        if not ids:
            return esito
        abil = abil.filter(legacy_anagrafica_id__in=ids)
    abil = list(abil)
    if not abil:
        return esito
    ok = qualificati({a.legacy_anagrafica_id for a in abil}, {a.processo_id for a in abil}, oggi=oggi)

    # (persona, mansione) → qualificata su almeno un processo che la collega, e da dove viene.
    coppie: dict[tuple[int, int], dict] = {}
    for a in abil:
        for r in a.ruoli_processo.all():
            if r.pk not in ruoli:
                continue
            c = coppie.setdefault((a.legacy_anagrafica_id, r.competenza_id),
                                  {"mansione": ruoli[r.pk].competenza, "qualificata": False, "processi": []})
            c["qualificata"] = c["qualificata"] or (a.legacy_anagrafica_id, a.processo_id) in ok
            c["processi"].append(ruoli[r.pk].processo.nome)

    config = SkillMatrixConfig.get_instance()
    soglia = config.soglia_operativa_ordinale
    liv_soglia = _DA_ORDINALE.get(soglia, "U")
    liv_sotto = _DA_ORDINALE.get(soglia - 1, "I") or "I"
    con_competenze = set(VoceMacchinaCatalogo.objects.filter(attiva=True, mansione_id__in={m for _l, m in coppie})
                         .values_list("mansione_id", flat=True))
    esistenti = {(x.legacy_anagrafica_id, x.competenza_id): x for x in AbilitazioneMacchina.objects.filter(
        legacy_anagrafica_id__in={lid for lid, _m in coppie}, competenza_id__in={m for _l, m in coppie})}

    def _storico(lid, mansione, livello, testo):
        AbilitazioneMacchinaStorico.objects.create(
            legacy_anagrafica_id=lid, competenza_id=mansione.pk, livello=livello, data_rilevazione=oggi,
            fonte=AbilitazioneMacchinaStorico.FONTE_AUTOMATICO, note=testo[:255])

    with transaction.atomic():
        for (lid, mansione_id), c in sorted(coppie.items()):
            mansione, qualif = c["mansione"], c["qualificata"]
            origine = "Qualifica MOD.128 «" + ", ".join(sorted(set(c["processi"]))) + "»"
            ab = esistenti.get((lid, mansione_id))
            if ab is None:
                livello = "I" if (mansione_id in con_competenze or not qualif) else liv_soglia
                esito["assegnate"] += 1
                esito["cambi"].append((lid, mansione.nome, "", livello))
                if applica:
                    AbilitazioneMacchina.objects.create(
                        legacy_anagrafica_id=lid, competenza=mansione, livello=livello, in_lista=True,
                        data_assegnazione=oggi, note=f"Assegnata da {origine}"[:500])
                    _storico(lid, mansione, livello, f"{origine}: assegnata, livello {livello}")
                continue
            if mansione_id in con_competenze or not ab.in_lista:
                continue  # livello calcolato dalle competenze / tolto a mano dalla lista: non si tocca
            attuale = ordinale_livello(ab.livello)
            nuovo = ""
            if qualif and attuale < soglia:
                nuovo, chiave = liv_soglia, "alzate"
            elif not qualif and attuale >= soglia:
                nuovo, chiave = liv_sotto, "abbassate"
            if not nuovo or nuovo == ab.livello:
                continue
            esito[chiave] += 1
            esito["cambi"].append((lid, mansione.nome, ab.livello or "", nuovo))
            if applica:
                AbilitazioneMacchina.objects.filter(pk=ab.pk).update(livello=nuovo, updated_at=timezone.now())
                stato = "qualificata" if qualif else "non qualificata"
                _storico(lid, mansione, nuovo, f"{origine} ({stato}): livello {ab.livello or '—'} → {nuovo}")
    if applica and esito["cambi"]:
        logger.info("MOD.128 → mansioni: %d assegnate, %d alzate, %d abbassate",
                    esito["assegnate"], esito["alzate"], esito["abbassate"])
    return esito
