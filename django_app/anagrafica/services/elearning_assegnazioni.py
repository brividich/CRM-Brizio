"""Assegnazioni automatiche dei corsi e-learning e cicli di aggiornamento.

Fonte unica degli obblighi: il motore dei requisiti (``services.requisiti``), lo
stesso di scadenzario, libretto e cruscotto. Copre già mansione di rischio,
mansione lavorativa, area, ruoli operativi, regole per persona e processi
MOD.128. Qui si trasforma ogni obbligo **non soddisfatto** su un corso
e-learning pubblicato in una ``TrainingAssignment`` del ciclo corrente, con
scadenza, e si notifica il dipendente.

- Idempotente: ``get_or_create`` su (corso, dipendente, ciclo); non cancella nulla.
- Rinnovo: un obbligo **completato in passato** e in scadenza entro la finestra
  delle impostazioni (o scaduto) apre il ciclo successivo (iscrizione e
  assegnazione nuove), lasciando intatta la storia del ciclo precedente.
- Cessati e persone senza anagrafica attiva esclusi.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

STATI_DA_ASSEGNARE = ("MAI_FREQUENTATO", "SCADUTO")  # in scadenza: vedi finestra di rinnovo


def sincronizza(legacy_ids=None, *, oggi=None, notifica: bool = True) -> dict:
    """Crea le assegnazioni mancanti per gli obblighi su corsi e-learning pubblicati."""
    from ..models_formazione import ElearningConfig, TrainingAssignment, TrainingCourse
    from . import requisiti
    from .elearning_fruizione import ciclo_corrente

    ctx = requisiti.ambito(oggi)
    oggi = ctx.today
    cfg = ElearningConfig.get_instance()
    entro = oggi + timedelta(days=int(cfg.giorni_entro_default or 30))
    finestra = oggi + timedelta(days=int(cfg.finestra_rinnovo_giorni or 60))

    from .elearning_fruizione import corsi_pubblicati
    pubblicati = set(corsi_pubblicati().values_list("pk", flat=True))
    report = {"persone": 0, "assegnate": 0, "rinnovi": 0, "gia_presenti": 0}
    if not pubblicati:
        return report
    persone = {d.id: d for d in ctx._tutti() if d.data_cessazione is None and d.attivo_legacy}
    if legacy_ids is not None:
        voluti = {ctx.canonico(int(i)) for i in legacy_ids}
        persone = {pid: p for pid, p in persone.items() if pid in voluti}
    report["persone"] = len(persone)
    for voce in requisiti.formazione(ctx, persone):
        if voce.corso.pk not in pubblicati or not voce.obbligatorio:
            continue
        in_scadenza = voce.scadenza is not None and voce.scadenza <= finestra
        if voce.stato not in STATI_DA_ASSEGNARE and not in_scadenza:
            continue
        rinnovo = voce.completato is not None
        ciclo = ciclo_corrente(voce.corso, voce.persona)
        if rinnovo and _ciclo_completato(voce.corso, voce.persona, ciclo):
            ciclo += 1
        try:
            with transaction.atomic():
                assegnazione, creata = TrainingAssignment.objects.get_or_create(
                    corso=voce.corso, legacy_anagrafica_id=voce.persona, ciclo=ciclo,
                    defaults={"due_date": min(entro, voce.scadenza) if (rinnovo and voce.scadenza and voce.scadenza > oggi) else entro,
                              "note": ("Rinnovo: " if rinnovo else "Obbligo: ") + "; ".join(voce.origini)[:400]},
                )
        except IntegrityError:
            creata = False
        if not creata:
            report["gia_presenti"] += 1
            continue
        report["rinnovi" if rinnovo else "assegnate"] += 1
        if notifica:
            pid, corso_id = voce.persona, voce.corso.pk
            transaction.on_commit(lambda pid=pid, corso_id=corso_id: _notifica(corso_id, pid))
    return report


def _ciclo_completato(corso, legacy_id: int, ciclo: int) -> bool:
    from ..models_formazione import TrainingElearningEnrollment
    return TrainingElearningEnrollment.objects.filter(
        corso=corso, legacy_anagrafica_id=legacy_id, ciclo=ciclo, stato="COMPLETATO").exists()


def _notifica(corso_id: int, legacy_id: int) -> None:
    try:
        from .elearning_notifications import notify_corso_assegnato
        notify_corso_assegnato(corso_id, legacy_id)
    except Exception:
        logger.warning("notifica assegnazione e-learning fallita (%s, %s)", corso_id, legacy_id, exc_info=True)
