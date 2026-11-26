"""Chi dovrebbe avere una qualifica e non ce l'ha (o l'ha scaduta).

Per la scheda del tipo di qualifica. Le fonti del «richiesta a» sono quelle già usate dal portale:

- processi qualificati MOD.128: requisito persona «Qualifica del catalogo» sui ruoli
  dell'abilitazione (``mpq_persone.requisiti_per_abilitazione``), abilitazioni attive;
- mansioni della skill matrix: voce della mansione con la qualifica come requisito formale,
  persone in lista sulla mansione;
- ruoli operativi: qualifica obbligatoria del ruolo, ruolo in essere.

Solo persone in forza (senza data di cessazione). Vale la qualifica corrente per persona
(la conseguita per ultima): «mancante» se non c'è, «scaduta» se la corrente è scaduta.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone


def _aggiungi(motivi: dict[int, list[str]], lid, testo: str) -> None:
    if not lid:
        return
    voci = motivi.setdefault(int(lid), [])
    if testo not in voci:
        voci.append(testo)


def _da_processi(tipo, motivi) -> None:
    from ..models_mpq import AbilitazioneProcesso, RequisitoPersona
    from .mpq_persone import requisiti_per_abilitazione

    reqs = list(RequisitoPersona.objects.filter(attivo=True, tipo=RequisitoPersona.TIPO_QUALIFICA,
                                                tipo_qualifica=tipo)
                .select_related("processo").prefetch_related("ruoli"))
    per_processo: dict[int, list] = {}
    for r in reqs:
        per_processo.setdefault(r.processo_id, []).append(r)
    if not per_processo:
        return
    abilitazioni = (AbilitazioneProcesso.objects
                    .filter(processo_id__in=list(per_processo), stato=AbilitazioneProcesso.STATO_ATTIVA,
                            nominativo_esterno="")
                    .select_related("processo").prefetch_related("ruoli_processo"))
    for ab in abilitazioni:
        if requisiti_per_abilitazione(ab, per_processo[ab.processo_id]):
            _aggiungi(motivi, ab.legacy_anagrafica_id, f"Processo «{ab.processo.nome}»")


def _da_mansioni(tipo, motivi) -> None:
    from ..models_skillmatrix import AbilitazioneMacchina, VoceMacchinaCatalogo

    mansioni = dict(VoceMacchinaCatalogo.objects.filter(qualifica=tipo, attiva=True, mansione__isnull=False)
                    .values_list("mansione_id", "mansione__display"))
    if not mansioni:
        return
    for lid, comp_id in (AbilitazioneMacchina.objects
                         .filter(competenza_id__in=list(mansioni), in_lista=True)
                         .values_list("legacy_anagrafica_id", "competenza_id")):
        _aggiungi(motivi, lid, f"Mansione «{mansioni.get(comp_id) or comp_id}»")


def _da_ruoli(tipo, motivi, oggi: date) -> None:
    from ..models import DipendenteRuoloOperativo, RuoloQualifica

    ruoli = dict(RuoloQualifica.objects.filter(qualifica=tipo, obbligatoria=True)
                 .values_list("ruolo_id", "ruolo__nome"))
    if not ruoli:
        return
    for a in DipendenteRuoloOperativo.objects.filter(ruolo_id__in=list(ruoli)):
        if a.data_fine and a.data_fine < oggi:
            continue
        _aggiungi(motivi, a.legacy_anagrafica_id, f"Ruolo «{ruoli[a.ruolo_id]}»")


def persone_senza_qualifica(tipo, *, oggi: date | None = None, nomi: dict | None = None) -> list[dict]:
    """``[{"legacy_id", "nome", "motivi", "stato", "scadenza"}]``, mancanti prima delle scadute."""
    from ..models import DipendenteAnagraficaAziendale, DipendenteQualifica

    oggi = oggi or timezone.localdate()
    motivi: dict[int, list[str]] = {}
    for fonte in (_da_processi, _da_mansioni):
        try:
            fonte(tipo, motivi)
        except Exception:  # pragma: no cover - modulo non migrato: la sezione resta parziale
            import logging

            logging.getLogger(__name__).warning("qualifica_mancanti: fonte %s non disponibile", fonte.__name__,
                                                exc_info=True)
    try:
        _da_ruoli(tipo, motivi, oggi)
    except Exception:  # pragma: no cover
        import logging

        logging.getLogger(__name__).warning("qualifica_mancanti: ruoli non disponibili", exc_info=True)
    if not motivi:
        return []

    in_forza = set(DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=True)
                   .values_list("legacy_anagrafica_id", flat=True))
    correnti: dict[int, tuple] = {}
    for lid, conseguita, scadenza, pk in DipendenteQualifica.objects.filter(tipo=tipo).values_list(
            "legacy_anagrafica_id", "data_conseguimento", "data_scadenza", "pk"):
        chiave = (conseguita or date.min, pk)
        if lid not in correnti or chiave > correnti[lid][0]:
            correnti[lid] = (chiave, scadenza)

    nomi = nomi or {}
    out = []
    for lid, perche in motivi.items():
        if lid not in in_forza:
            continue
        corrente = correnti.get(lid)
        if corrente is None:
            stato, scadenza = "mancante", None
        elif corrente[1] is not None and corrente[1] < oggi:
            stato, scadenza = "scaduta", corrente[1]
        else:
            continue
        out.append({"legacy_id": lid, "nome": nomi.get(lid, f"#{lid}"), "motivi": perche,
                    "stato": stato, "scadenza": scadenza})
    out.sort(key=lambda r: (r["stato"] != "mancante", r["nome"].casefold()))
    return out
