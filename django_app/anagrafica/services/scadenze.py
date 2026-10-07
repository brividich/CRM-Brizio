"""Scadenze salvate a DB, allineate al motore unico dei requisiti.

Il motore (:mod:`anagrafica.services.requisiti`) calcola requisiti e stato alla
data. Diverse parti del portale pero' leggono dati salvati — scadenzario della
formazione, promemoria del mattino, KPI della dashboard, scadenziario visite —
quindi qui quei dati vengono riscritti dal motore, cosi' che ovunque si legga la
stessa verita':

- :func:`ricalcola_formazione` ricostruisce la cache ``TrainingDeadline``: righe
  per requisito (con l'origine in ``reason_snapshot``) e per corso frequentato,
  stato alla data, righe non piu' valide cancellate (requisiti tolti, persone
  cessate, id di anagrafiche doppie, id inesistenti). Prima la cache conosceva
  solo regole individuali e processi e nessuno la ricalcolava: un corso scaduto
  restava «valido» e i promemoria partivano da dati vecchi.
- :func:`ricalcola_visite` scrive su ``VisitaMedica.data_scadenza`` la scadenza
  **effettiva** (ricalcolo prudente quando la mansione richiede una periodicita'
  piu' stretta, vedi ``requisiti.scadenza_prudente``) e il motivo in
  ``scadenza_nota``; se il requisito sparisce torna la scadenza del tipo.

Entrambe girano ogni notte (schedule ``anagrafica_ricalcolo_scadenze``), dopo un
cambio mansione e, per le visite, dopo ogni salvataggio di una visita.
"""
from __future__ import annotations

import logging

from datetime import date

from django.db import transaction

from anagrafica.reportistica.dati import a_blocchi, filtra_in

from . import requisiti

logger = logging.getLogger(__name__)

FONTE = "requisiti"


def _persone(ctx, legacy_ids) -> dict:
    """Persone in forza da ricalcolare (tutte, o quelle a cui appartengono gli id dati)."""
    in_forza = {p.id: p for p in ctx.dipendenti()}
    if legacy_ids is None:
        return in_forza
    voluti = {ctx.canonico(int(i)) for i in legacy_ids if int(i or 0) > 0}
    return {pid: p for pid, p in in_forza.items() if pid in voluti}


def ricalcola_formazione(legacy_ids=None, *, oggi: date | None = None) -> dict[str, int]:
    """Ricostruisce ``TrainingDeadline`` per tutte le persone in forza o per quelle indicate."""
    from anagrafica.models_formazione import TrainingDeadline

    ctx = requisiti.ambito(oggi)
    persone = _persone(ctx, legacy_ids)
    voci = requisiti.formazione(ctx, persone, solo_obbligatori=False) if persone else []
    nuove = {(v.persona, v.corso.pk): v for v in voci}

    # Righe esistenti da considerare: quelle delle persone ricalcolate (tutti i loro id).
    if legacy_ids is None:
        esistenti = list(TrainingDeadline.objects.all())
    else:
        esistenti = filtra_in(TrainingDeadline.objects.all(), "legacy_anagrafica_id", ctx.id_estesi(persone))
        # Persona indicata ma non (piu') in forza: le sue righe vanno tolte.
        assenti = {ctx.canonico(int(i)) for i in legacy_ids} - set(persone)
        if assenti:
            alias = [i for i, pid in ctx._alias().items() if pid in assenti] + list(assenti)
            esistenti += filtra_in(TrainingDeadline.objects.all(), "legacy_anagrafica_id", alias)
    per_chiave = {}
    da_cancellare = []
    for riga in esistenti:
        chiave = (riga.legacy_anagrafica_id, riga.corso_id)
        if chiave in nuove and chiave not in per_chiave:
            per_chiave[chiave] = riga
        else:
            da_cancellare.append(riga.pk)  # requisito tolto, cessato, id del doppione, duplicato

    # I collegamenti a regola/assegnazione/completamento non li legge nessuna pagina:
    # l'origine del requisito sta in reason_snapshot, scritta in chiaro.
    campi = ["data_ultimo_completamento", "data_scadenza", "stato_scadenza", "giorni_alla_scadenza",
             "is_required", "reason_snapshot", "needs_refresh", "last_recalculation_source",
             "requirement_rule_id", "assignment_id", "ultimo_completamento_id"]
    da_aggiornare, da_creare = [], []
    for chiave, v in nuove.items():
        valori = {
            "data_ultimo_completamento": v.completato, "data_scadenza": v.scadenza,
            "stato_scadenza": v.stato, "giorni_alla_scadenza": v.giorni, "is_required": v.obbligatorio,
            "reason_snapshot": {"origini": list(v.origini)}, "needs_refresh": False,
            "last_recalculation_source": FONTE, "requirement_rule_id": None, "assignment_id": None,
            "ultimo_completamento_id": None,
        }
        riga = per_chiave.get(chiave)
        if riga is None:
            da_creare.append(TrainingDeadline(corso_id=chiave[1], legacy_anagrafica_id=chiave[0], **valori))
        elif any(getattr(riga, c) != val for c, val in valori.items()):
            for c, val in valori.items():
                setattr(riga, c, val)
            da_aggiornare.append(riga)

    with transaction.atomic():
        for blocco in a_blocchi(da_cancellare):
            TrainingDeadline.objects.filter(pk__in=blocco).delete()
        if da_aggiornare:
            TrainingDeadline.objects.bulk_update(da_aggiornare, campi, batch_size=200)
        if da_creare:
            TrainingDeadline.objects.bulk_create(da_creare, batch_size=200)
    esito = {"persone": len(persone), "righe": len(nuove), "create": len(da_creare),
             "aggiornate": len(da_aggiornare), "cancellate": len(da_cancellare)}
    logger.info("ricalcolo scadenze formazione: %s", esito)
    return esito


def ricalcola_visite(legacy_ids=None, *, oggi: date | None = None) -> dict[str, int]:
    """Scrive la scadenza effettiva sulle visite correnti (e la ripristina dove non serve piu')."""
    from anagrafica.models import VisitaMedica

    ctx = requisiti.ambito(oggi)
    persone = _persone(ctx, legacy_ids)
    voci = [v for v in requisiti.visite(ctx, persone) if v.visita_id] if persone else []
    attese = {v.visita_id: (v.scadenza, v.nota) for v in voci}
    aggiornate = 0
    visite = filtra_in(VisitaMedica.objects.only("pk", "data_scadenza", "scadenza_nota"), "pk", attese)
    with transaction.atomic():
        for visita in visite:
            scadenza, nota = attese[visita.pk]
            if visita.data_scadenza != scadenza or (visita.scadenza_nota or "") != nota:
                # update(): niente save(), che ricalcolerebbe la scadenza dal solo tipo.
                VisitaMedica.objects.filter(pk=visita.pk).update(data_scadenza=scadenza, scadenza_nota=nota[:300])
                aggiornate += 1
    esito = {"persone": len(persone), "visite": len(attese), "aggiornate": aggiornate}
    logger.info("ricalcolo scadenze visite: %s", esito)
    return esito


def ricalcola_tutto(legacy_ids=None, *, oggi: date | None = None) -> dict[str, dict]:
    return {"formazione": ricalcola_formazione(legacy_ids, oggi=oggi),
            "visite": ricalcola_visite(legacy_ids, oggi=oggi)}


class _RicalcoloInAttesa:
    """Callback on_commit che accumula le persone toccate nella stessa transazione."""

    def __init__(self):
        self.ids: set[int] = set()

    def __call__(self):
        try:
            ricalcola_tutto(sorted(self.ids))
        except Exception:
            logger.exception("ricalcolo scadenze dopo il salvataggio fallito per %s", sorted(self.ids))


def ricalcola_dopo_commit(legacy_ids) -> None:
    """Ricalcolo per le persone indicate a transazione conclusa; un errore non blocca chi salva.

    Le persone si accumulano: un import che salva centinaia di visite nella stessa
    transazione produce **un** ricalcolo su tutte, non uno per visita. Si riusa il
    callback solo se e' ancora registrato sulla connessione (una transazione
    annullata lo scarta, e allora se ne registra uno nuovo).
    """
    ids = {int(i) for i in legacy_ids if int(i or 0) > 0}
    if not ids:
        return
    conn = transaction.get_connection()
    attivo = getattr(conn, "_scadenze_ricalcolo", None)
    if attivo is not None and conn.in_atomic_block and any(
            voce[1] is attivo for voce in conn.run_on_commit):
        attivo.ids.update(ids)
        return
    callback = _RicalcoloInAttesa()
    callback.ids.update(ids)
    conn._scadenze_ricalcolo = callback
    transaction.on_commit(callback)
