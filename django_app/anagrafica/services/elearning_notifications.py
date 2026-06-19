"""Hook notifiche e-learning — micro-corsi interni (NOVICROM HUB).

PREDISPOSIZIONE (D7): in questa fase NON viene inviata alcuna notifica. Qui restano
solo gli **hook** da agganciare a django-q2 (pattern visite mediche / SLA reminder).
La logica di invio (email/Teams/Graph) verrà implementata in una patch successiva.

Per attivare in futuro: schedulare ``send_elearning_reminders`` via Task Scheduler
(QCluster) — vedi le note operative su django-q2 (usare intervallo in MINUTI, non
secondi) e i command analoghi ``send_formazione_session_reminders`` /
``send_visite_mediche_digest``.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify_corso_assegnato(corso_id: int, legacy_anagrafica_id: int) -> None:
    """Hook: nuovo micro-corso e-learning assegnato a un dipendente.

    NO-OP per ora (D7). Implementare qui l'invio quando si abilitano le notifiche.
    """
    logger.debug(
        "[e-learning] hook notify_corso_assegnato corso=%s dip=%s (invio non implementato)",
        corso_id, legacy_anagrafica_id,
    )


def notify_promemoria_da_completare(corso_id: int, legacy_anagrafica_id: int) -> None:
    """Hook: promemoria 'corso e-learning ancora da completare'.

    NO-OP per ora (D7).
    """
    logger.debug(
        "[e-learning] hook notify_promemoria corso=%s dip=%s (invio non implementato)",
        corso_id, legacy_anagrafica_id,
    )


def iter_corsi_da_completare():
    """Seleziona le iscrizioni e-learning non ancora completate (per i futuri promemoria).

    Restituisce un iterabile di ``TrainingElearningEnrollment``. Usata dal management
    command stub: per ora solo conteggio/log, nessun invio.
    """
    from ..models_formazione import TrainingElearningEnrollment
    return (
        TrainingElearningEnrollment.objects
        .filter(stato__in=["ISCRITTO", "IN_CORSO", "NON_SUPERATO"], corso__is_active=True)
        .select_related("corso")
    )
