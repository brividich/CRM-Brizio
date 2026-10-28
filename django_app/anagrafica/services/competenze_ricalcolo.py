"""Livello sulla mansione ricalcolato da solo quando cambia ciò da cui dipende (28/10/2026).

Sulle mansioni con competenze il livello salvato su ``AbilitazioneMacchina`` (quello
che leggono skill matrix, pool capacità, carichi e reparto principale) lo calcola
``mansionario_competenze.valuta``: livelli per competenza, regola di calcolo, soglia
e requisiti formali (corso valido, qualifica non scaduta, abilitazione MOD.128).
Prima si riallineava solo da «Valuta»: un corso scaduto o una competenza bloccante
aggiunta lasciavano un «autonomo» che non lo era più.

Qui il ricalcolo per le persone indicate (o per tutti):

- con almeno una competenza valutata vale il livello calcolato (già col tetto di
  chi non è abilitato; mai sotto «I»);
- senza nessuna competenza valutata («da valutare») resta il livello di partenza,
  ma chi non è abilitato scende sotto la soglia: non risulta operativo per errore;
- ogni cambio va nello storico delle abilitazioni (fonte «automatico», con il
  motivo), mai in silenzio.

Si scrive con ``update()``: niente segnali, quindi niente giro di ricalcoli.

Chi lo chiama: ``scadenze.ricalcola_tutto`` (dopo ogni salvataggio che tocca corsi,
qualifiche, MOD.128, persone, e la notte, che copre anche le scadenze che passano
senza che nessuno salvi niente) e ``segnali_competenze`` (competenze della mansione
e regole del Mansionario).
"""
from __future__ import annotations

import logging

from django.utils import timezone

from ..models import AbilitazioneMacchina, AbilitazioneMacchinaStorico, SkillMatrixConfig, VoceMacchinaCatalogo
from ..models_skillmatrix import ordinale_livello

logger = logging.getLogger(__name__)


def livello_atteso(abilitazione: AbilitazioneMacchina, valutazione, soglia: int) -> str:
    """Il livello che l'abilitazione dovrebbe avere oggi ('' = lasciarlo com'è)."""
    from . import mansionario_competenze as comp

    if any(r["livello"] for r in valutazione.voci):
        # Calcolo sotto «I» (es. competenza bloccante nuova, ancora da valutare): chi è in
        # lista resta almeno in formazione.
        return valutazione.livello or "I"
    if valutazione.esito == comp.NON_ABILITATO and ordinale_livello(abilitazione.livello) >= soglia:
        return comp._DA_ORDINALE.get(soglia - 1, "")
    return ""


def ricalcola(legacy_ids=None, *, mansioni_ids=None, motivo: str = "", applica: bool = True) -> dict:
    """Riallinea i livelli sulle mansioni con competenze. ``None`` = tutti.

    Restituisce i conteggi e, per ogni cambio, (persona, mansione, prima, dopo).
    """
    from . import mansionario_competenze as comp

    config = SkillMatrixConfig.get_instance()
    soglia = config.soglia_operativa_ordinale
    voci_per_mansione: dict[int, list] = {}
    voci_qs = VoceMacchinaCatalogo.objects.filter(attiva=True, mansione__isnull=False)
    if mansioni_ids is not None:
        voci_qs = voci_qs.filter(mansione_id__in=list(mansioni_ids))
    for v in voci_qs.select_related("corso", "qualifica", "processo_mpq").order_by("ordine", "pk"):
        voci_per_mansione.setdefault(v.mansione_id, []).append(v)
    esito = {"valutate": 0, "cambiate": 0, "cambi": []}
    if not voci_per_mansione:
        return esito
    abil = AbilitazioneMacchina.objects.filter(in_lista=True, competenza_id__in=list(voci_per_mansione))
    if legacy_ids is not None:
        ids = [int(i) for i in legacy_ids if i]
        if not ids:
            return esito
        abil = abil.filter(legacy_anagrafica_id__in=ids)
    abil = list(abil.select_related("competenza").prefetch_related("voci"))
    if not abil:
        return esito
    requisiti = comp.Requisiti({a.legacy_anagrafica_id for a in abil},
                               [v for vs in voci_per_mansione.values() for v in vs])
    oggi = timezone.localdate()
    nota = "Ricalcolo automatico" + (f": {motivo}" if motivo else "")
    for a in abil:
        val = comp.valuta(a, voci=voci_per_mansione[a.competenza_id], config=config, requisiti=requisiti)
        esito["valutate"] += 1
        nuovo = livello_atteso(a, val, soglia)
        if not nuovo or nuovo == (a.livello or ""):
            continue
        esito["cambiate"] += 1
        esito["cambi"].append((a.legacy_anagrafica_id, a.competenza.nome, a.livello or "", nuovo))
        if not applica:
            continue
        AbilitazioneMacchina.objects.filter(pk=a.pk).update(livello=nuovo, updated_at=timezone.now())
        AbilitazioneMacchinaStorico.objects.create(
            legacy_anagrafica_id=a.legacy_anagrafica_id, asset_id=a.asset_id, competenza_id=a.competenza_id,
            livello=nuovo, data_rilevazione=oggi, fonte=AbilitazioneMacchinaStorico.FONTE_AUTOMATICO,
            note=f"{nota} — livello {a.livello or '—'} → {nuovo} ({val.esito_label.lower()})"[:255],
        )
    if esito["cambiate"] and applica:
        logger.info("competenze: %d livelli riallineati (%s)", esito["cambiate"], motivo or "ricalcolo")
    return esito
