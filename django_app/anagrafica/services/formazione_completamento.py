"""Un solo punto di uscita per ogni completamento (TrainingEmployeeRecord), da qualunque strada arrivi:
iscrizione a una sessione (aula, online), completamento diretto, e-learning, link aperto, import,
formazione pregressa del preinserimento.

Prima gli effetti stavano in due copie (``views/formazione._post_completamento`` e la coda di
``views/_helpers._crea_record_completamento_elearning``) che facevano cose diverse; gli import non ne
facevano nessuno (analisi 26/11/2026).

Effetti (tutti fail-safe: un errore qui non annulla mai il completamento):
- scadenze ricalcolate per persona × corso;
- qualifica collegata al corso, se il completamento è idoneo;
- un corso = un completamento: chiuse le assegnazioni aperte dello stesso corso e le iscrizioni alle
  sessioni online dello stesso corso;
- solo per i completamenti «di oggi» (non ``storico``): valutazione di efficacia e archiviazione
  dell'attestato, dopo il commit.
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def dopo_completamento(record, user=None, *, storico: bool = False) -> None:
    if record is None:
        return
    corso = record.corso
    legacy_id = record.legacy_anagrafica_id

    from ..models_formazione import TrainingAssignment, TrainingDeadline

    TrainingDeadline.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).update(needs_refresh=True)
    try:
        from .training_deadline_service import refresh_deadlines
        refresh_deadlines(legacy_id=legacy_id, corso_id=corso.pk)
    except NotImplementedError:
        pass
    except Exception:
        logger.exception("Ricalcolo scadenze fallito per dip=%s corso=%s", legacy_id, corso.pk)

    try:
        if corso.qualifica_id and record.idoneo:
            from ..views._helpers import _upsert_dipendente_qualifica
            with transaction.atomic():
                qual, _ = _upsert_dipendente_qualifica(legacy_id, corso.qualifica, record.data_completamento,
                                                       record.data_scadenza, user=user)
                if qual.record_formazione_id != record.pk:
                    qual.record_formazione = record
                    qual.save(update_fields=["record_formazione"])
    except Exception:
        logger.exception("Allineamento qualifica fallito per record %s", record.pk)

    if record.idoneo:
        try:
            with transaction.atomic():
                TrainingAssignment.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).exclude(
                    stato__in=("COMPLETATO", "ESONERATO")).update(stato="COMPLETATO")
                from .sessione_online import completa_iscrizioni_da_record
                completa_iscrizioni_da_record(record)
        except Exception:
            logger.exception("Assegnazioni / sessioni online non chiuse per record %s", record.pk)

    if storico:
        return

    try:
        from .formazione_efficacia import pianifica_valutazione_efficacia
        with transaction.atomic():
            pianifica_valutazione_efficacia(record)
    except Exception:
        logger.exception("Valutazione di efficacia non pianificata per record %s", record.pk)

    def _archivia():
        try:
            from ..models_formazione import AttestatoFormazioneConfig
            cfg = AttestatoFormazioneConfig.get_instance()
            if cfg.auto_salva_attestato:
                from .attestato_pdf import archivia_attestato
                archivia_attestato(record, cfg=cfg, user=user)
        except Exception:
            logger.exception("Archiviazione automatica attestato fallita per record %s", record.pk)

    transaction.on_commit(_archivia)


def completamento_valido(corso, legacy_id, *, oggi=None):
    """Il completamento valido più recente della persona per il corso, da qualunque strada; None se
    non c'è o se è scaduto. Regola unica di «ha già fatto il corso»."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord

    if not legacy_id or corso is None:
        return None
    oggi = oggi or timezone.localdate()
    return (TrainingEmployeeRecord.objects
            .filter(corso=corso, legacy_anagrafica_id=legacy_id, idoneo=True)
            .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
            .order_by("-data_completamento", "-pk").first())


def ids_con_completamento_valido(corso, legacy_ids, *, oggi=None) -> set[int]:
    """Le persone (fra ``legacy_ids``) che hanno un completamento valido del corso."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord

    oggi = oggi or timezone.localdate()
    return set(TrainingEmployeeRecord.objects
               .filter(corso=corso, legacy_anagrafica_id__in=list(legacy_ids), idoneo=True)
               .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
               .values_list("legacy_anagrafica_id", flat=True))
