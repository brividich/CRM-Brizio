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
    """Notifica in-app al dipendente: «ti è stato assegnato un corso online».

    Fire-and-forget (``invia_notifica`` non propaga errori); nessuna notifica se
    il dipendente non ha un account del portale.
    """
    from core.notifiche import invia_notifica
    from django.urls import reverse

    legacy_user_id = utente_di(legacy_anagrafica_id)
    if not legacy_user_id:
        return
    try:
        from ..models_formazione import TrainingCourse
        titolo = TrainingCourse.objects.filter(pk=corso_id).values_list("titolo", flat=True).first() or f"corso #{corso_id}"
    except Exception:
        titolo = f"corso #{corso_id}"
    invia_notifica(
        legacy_user_id, "elearning_assegnato", f"Ti è stato assegnato il corso online: {titolo}.",
        reverse("anagrafica:formazione_online_player", args=[corso_id]),
    )


def notify_promemoria_da_completare(corso_id: int, legacy_anagrafica_id: int) -> None:
    """Promemoria in-app 'micro-corso e-learning ancora da completare'.

    Consegna una :class:`core.models.Notifica` al discente (``legacy_anagrafica_id``),
    rispettando gli interruttori notifiche (``core.notifiche.invia_notifica`` è il
    chokepoint unico). Fire-and-forget: nessuna eccezione propagata.
    """
    from core.notifiche import invia_notifica

    try:
        from ..models_formazione import TrainingCourse
        titolo = (
            TrainingCourse.objects.filter(pk=corso_id)
            .values_list("titolo", flat=True).first()
            or f"corso #{corso_id}"
        )
    except Exception:
        titolo = f"corso #{corso_id}"
    # La notifica va all'UTENTE del portale (utenti.id), non all'id anagrafica:
    # sono numerazioni diverse e passare l'uno per l'altro la recapitava a un altro.
    legacy_user_id = utente_di(legacy_anagrafica_id)
    if not legacy_user_id:
        logger.info("[e-learning] promemoria non recapitabile: dip %s senza utente portale", legacy_anagrafica_id)
        return
    from django.urls import reverse
    invia_notifica(
        legacy_user_id,
        "elearning_promemoria",
        f"Micro-corso e-learning da completare: {titolo}.",
        reverse("anagrafica:formazione_online_player", args=[corso_id]),
    )


def utente_di(legacy_anagrafica_id: int) -> int | None:
    """utenti.id collegato all'anagrafica (None se il dipendente non ha account)."""
    try:
        from core.legacy_models import AnagraficaDipendente
        return (AnagraficaDipendente.objects.filter(pk=legacy_anagrafica_id)
                .values_list("utente_id", flat=True).first())
    except Exception:
        return None


def iter_corsi_da_completare():
    """Corsi e-learning pubblicati ancora da completare, per persona.

    Fonte: le **assegnazioni** aperte (anche di chi non ha mai aperto il corso) e le
    iscrizioni non completate. Una voce per coppia corso/dipendente. Ritorna oggetti
    con ``corso``, ``corso_id``, ``legacy_anagrafica_id``, ``stato``,
    ``ultima_slide_ordine``, ``n_slide_totali``.
    """
    from types import SimpleNamespace
    from ..models_formazione import TrainingAssignment, TrainingElearningEnrollment

    pubblicati = {"corso__is_elearning": True, "corso__is_active": True, "corso__stato": "ATTIVO"}
    completati = set(
        TrainingElearningEnrollment.objects.filter(stato="COMPLETATO", **pubblicati)
        .values_list("corso_id", "legacy_anagrafica_id")
    )
    voci: dict[tuple[int, int], object] = {}
    for e in (TrainingElearningEnrollment.objects
              .filter(stato__in=["ISCRITTO", "IN_CORSO", "NON_SUPERATO"], **pubblicati)
              .select_related("corso")):
        voci[(e.corso_id, e.legacy_anagrafica_id)] = e
    for a in (TrainingAssignment.objects
              .filter(stato__in=["ASSEGNATO", "IN_CORSO", "SCADUTO"], **pubblicati)
              .select_related("corso")):
        chiave = (a.corso_id, a.legacy_anagrafica_id)
        if chiave in voci or chiave in completati:
            continue
        voci[chiave] = SimpleNamespace(
            corso=a.corso, corso_id=a.corso_id, legacy_anagrafica_id=a.legacy_anagrafica_id,
            stato="ISCRITTO", ultima_slide_ordine=0, n_slide_totali=0,
        )
    return list(voci.values())
