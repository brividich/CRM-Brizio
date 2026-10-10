"""Tempo di fruizione misurato lato server (heartbeat) e completamento delle slide.

Regole:

- **una sola sessione attiva** per iscrizione: aprire il player chiude le altre
  (più schede non raddoppiano il tempo);
- il tempo si accredita solo da **heartbeat** (``beat``): limite ≥ 30 s fra due
  battiti (prima di allora nessun credito), credito massimo 60 s per battito,
  nessun credito se la pagina non è visibile, se il discente è inattivo oltre
  la soglia della regola o se la slide dichiarata non è quella servita;
- **tetto giornaliero** di 8 ore per iscrizione;
- una slide è **completata** quando il tempo su di essa raggiunge il minimo
  (slide o regola del corso); l'avanzamento (``ultima_slide_ordine``) cresce solo
  su slide completate in sequenza.

Il browser invia solo segnali (visibile, millisecondi dall'ultima interazione):
il tempo lo misura il server con il proprio orologio.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .elearning_regole import Regola, secondi_richiesti_slide

INTERVALLO_MIN_SECONDI = 30
CREDITO_MAX_SECONDI = 60
TETTO_GIORNALIERO_SECONDI = 8 * 3600


def _ip(request):
    return (request.META.get("REMOTE_ADDR") or "")[:45] or None if request is not None else None


def avvia_sessione(enr, request=None):
    """Chiude le sessioni aperte dell'iscrizione e ne apre una nuova."""
    from ..models_elearning import TrainingElearningSessione
    from ..models_formazione import TrainingElearningEnrollment

    with transaction.atomic():
        TrainingElearningEnrollment.objects.select_for_update().filter(pk=enr.pk).first()
        TrainingElearningSessione.objects.filter(enrollment=enr, chiusa=False).update(chiusa=True)
        ua = (request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:500]
        return TrainingElearningSessione.objects.create(
            enrollment=enr, ultimo_beat_il=timezone.now(), ip=_ip(request),
            ua_hash=hashlib.sha256(ua.encode()).hexdigest() if ua else "",
        )


def sessione_attiva(enr):
    from ..models_elearning import TrainingElearningSessione
    return TrainingElearningSessione.objects.filter(enrollment=enr, chiusa=False).order_by("-avviata_il").first()


def registra_vista(enr, slide, regola: Regola, ordini: list[int]):
    """La slide è stata servita: diventa la corrente della sessione; completata subito se non c'è minimo."""
    from ..models_elearning import TrainingElearningSlideView

    with transaction.atomic():
        vista, _ = TrainingElearningSlideView.objects.get_or_create(enrollment=enr, slide=slide)
        sessione = sessione_attiva(enr)
        if sessione is not None and sessione.slide_corrente_id != slide.pk:
            sessione.slide_corrente = slide
            sessione.save(update_fields=["slide_corrente"])
        if not vista.completata and secondi_richiesti_slide(slide, regola) <= vista.secondi:
            vista.completata = True
            vista.save(update_fields=["completata", "ultima_vista"])
        if enr.stato == "ISCRITTO":
            enr.stato = "IN_CORSO"
            enr.save(update_fields=["stato", "updated_at"])
        _ricalcola_avanzamento(enr, ordini)
    return vista


def _ricalcola_avanzamento(enr, ordini: list[int]):
    """``ultima_slide_ordine`` = ultima slide della catena di slide completate dall'inizio."""
    from ..models_elearning import TrainingElearningSlideView

    completate = set(
        TrainingElearningSlideView.objects.filter(enrollment=enr, completata=True, slide__is_active=True)
        .values_list("slide__ordine", flat=True)
    )
    ultima = 0
    for ordine in ordini:
        if ordine not in completate:
            break
        ultima = ordine
    if ultima != (enr.ultima_slide_ordine or 0):
        type(enr).objects.filter(pk=enr.pk).update(ultima_slide_ordine=ultima, updated_at=timezone.now())
        enr.ultima_slide_ordine = ultima
    return ultima


def beat(enr, *, slide_id: int | None, visibile: bool, inattivo_ms: int, regola: Regola, ordini: list[int]) -> dict:
    """Heartbeat: accredita il tempo trascorso dall'ultimo battito, se ammesso."""
    from ..models_elearning import TrainingElearningSessione, TrainingElearningSlideView

    with transaction.atomic():
        sessione = (TrainingElearningSessione.objects.select_for_update()
                    .filter(enrollment=enr, chiusa=False).order_by("-avviata_il").first())
        if sessione is None:
            return {"ok": False, "motivo": "sessione_assente"}
        adesso = timezone.now()
        delta = (adesso - sessione.ultimo_beat_il).total_seconds()
        if delta < INTERVALLO_MIN_SECONDI:
            return {"ok": False, "motivo": "troppo_presto", "retry_in": int(INTERVALLO_MIN_SECONDI - delta) + 1}
        sessione.ultimo_beat_il = adesso
        credito = 0
        motivo = "accreditato"
        if not visibile:
            motivo = "pagina_non_visibile"
        elif slide_id is None or slide_id != sessione.slide_corrente_id:
            motivo = "slide_non_corrente"
        elif int(inattivo_ms or 0) / 1000 > regola.inattivita_secondi:
            motivo = "inattivo"
        elif delta > 2 * CREDITO_MAX_SECONDI + INTERVALLO_MIN_SECONDI:
            motivo = "pausa"  # battiti saltati: il periodo non è coperto
        else:
            oggi = timezone.localdate()
            fatto_oggi = (TrainingElearningSessione.objects
                          .filter(enrollment=enr, avviata_il__date=oggi)
                          .aggregate(s=Sum("secondi_accreditati"))["s"] or 0)
            credito = int(min(delta, CREDITO_MAX_SECONDI, max(TETTO_GIORNALIERO_SECONDI - fatto_oggi, 0)))
            if credito <= 0:
                motivo = "tetto_giornaliero"
        sessione.save(update_fields=["ultimo_beat_il"])
        completata = False
        if credito:
            TrainingElearningSessione.objects.filter(pk=sessione.pk).update(
                secondi_accreditati=F("secondi_accreditati") + credito)
            type(enr).objects.filter(pk=enr.pk).update(
                secondi_accreditati=F("secondi_accreditati") + credito, updated_at=adesso)
            vista, _ = TrainingElearningSlideView.objects.select_for_update().get_or_create(
                enrollment=enr, slide_id=slide_id)
            vista.secondi = (vista.secondi or 0) + credito
            campi = ["secondi", "ultima_vista"]
            if not vista.completata and vista.secondi >= secondi_richiesti_slide(vista.slide, regola):
                vista.completata = True
                completata = True
                campi.append("completata")
            vista.save(update_fields=campi)
            if completata:
                enr.refresh_from_db(fields=["ultima_slide_ordine"])
                _ricalcola_avanzamento(enr, ordini)
        return {"ok": True, "motivo": motivo, "credito": credito, "slide_completata": completata}


def secondi_mancanti_slide(enr, slide, regola: Regola) -> int:
    from ..models_elearning import TrainingElearningSlideView
    vista = TrainingElearningSlideView.objects.filter(enrollment=enr, slide=slide).first()
    fatti = vista.secondi if vista else 0
    return max(secondi_richiesti_slide(slide, regola) - fatti, 0)


def chiudi_sessioni_inattive(minuti: int = 30) -> int:
    """Chiude le sessioni senza battito da ``minuti`` (job o apertura player)."""
    from ..models_elearning import TrainingElearningSessione
    soglia = timezone.now() - timedelta(minutes=minuti)
    return TrainingElearningSessione.objects.filter(chiusa=False, ultimo_beat_il__lt=soglia).update(chiusa=True)
