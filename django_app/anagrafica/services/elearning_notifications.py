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

    Esclusi i cessati e chi ha già un completamento valido (regola unica, da qualunque strada:
    aula, link aperto, import) nato dopo l'assegnazione / iscrizione: quel ciclo è chiuso.
    """
    voci = _voci_da_completare()
    if not voci:
        return []
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord
    from .formazione_completamento import _data_di
    from .training_eligibility import _cessati_ids

    oggi = timezone.localdate()
    cessati = _cessati_ids()
    voci = [v for v in voci if v.legacy_anagrafica_id not in cessati]
    ultimo_valido: dict[tuple[int, int], object] = {}
    for cid, lid, dc in (TrainingEmployeeRecord.objects
                         .filter(corso_id__in={v.corso_id for v in voci},
                                 legacy_anagrafica_id__in={v.legacy_anagrafica_id for v in voci},
                                 idoneo=True, data_completamento__lte=oggi)
                         .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
                         .values_list("corso_id", "legacy_anagrafica_id", "data_completamento")):
        if (cid, lid) not in ultimo_valido or dc > ultimo_valido[(cid, lid)]:
            ultimo_valido[(cid, lid)] = dc
    out = []
    for v in voci:
        dc = ultimo_valido.get((v.corso_id, v.legacy_anagrafica_id))
        inizio = _data_di(getattr(v, "inizio", None))
        if dc is not None and (inizio is None or dc >= inizio):
            continue
        out.append(v)
    return out


def _voci_da_completare():
    from types import SimpleNamespace
    from ..models_formazione import TrainingAssignment, TrainingElearningEnrollment

    from .elearning_fruizione import filtro_pubblicati
    pubblicati = filtro_pubblicati("corso__")
    completati = set(
        TrainingElearningEnrollment.objects.filter(stato="COMPLETATO", **pubblicati)
        .values_list("corso_id", "legacy_anagrafica_id", "ciclo")
    )
    voci: dict[tuple[int, int], object] = {}
    for e in (TrainingElearningEnrollment.objects
              .filter(stato__in=["ISCRITTO", "IN_CORSO", "NON_SUPERATO"], **pubblicati)
              .select_related("corso")):
        e.inizio = e.data_iscrizione
        voci[(e.corso_id, e.legacy_anagrafica_id, e.ciclo)] = e
    for a in (TrainingAssignment.objects
              .filter(stato__in=["ASSEGNATO", "IN_CORSO", "SCADUTO"], **pubblicati)
              .select_related("corso")):
        chiave = (a.corso_id, a.legacy_anagrafica_id, a.ciclo)
        if chiave in voci or chiave in completati:
            continue
        voci[chiave] = SimpleNamespace(
            corso=a.corso, corso_id=a.corso_id, legacy_anagrafica_id=a.legacy_anagrafica_id,
            stato="ISCRITTO", ultima_slide_ordine=0, n_slide_totali=0, inizio=a.data_assegnazione,
        )
    return list(voci.values())


def quiz_da_abbinare_per_corso() -> list[tuple[str, int]]:
    """[(titolo del corso, n)] dei quiz superati dal link aperto ancora senza dipendente abbinato:
    finché l'HR non abbina, il corso non risulta fatto da nessuna parte."""
    from django.db.models import Count

    from ..models_elearning import TrainingElearningRispostaAperta as R
    return list(R.objects.filter(superato=True, stato=R.DA_ABBINARE)
                .values("corso__titolo").annotate(n=Count("pk")).order_by("corso__titolo")
                .values_list("corso__titolo", "n"))
