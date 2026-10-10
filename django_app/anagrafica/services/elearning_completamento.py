"""Completamento e-learning: verifica dei requisiti e registrazione una sola volta.

Il completamento nasce solo qui, dentro una transazione con l'iscrizione
bloccata (``select_for_update``):

1. se esiste già (``TrainingElearningCompletamento``, OneToOne sull'iscrizione)
   si restituisce quello: idempotente anche con invii ripetuti o simultanei;
2. altrimenti si **riverificano lato server** tutti i requisiti della regola del
   corso (slide completate, tempo effettivo accreditato, quiz superato);
3. si creano il ``TrainingEmployeeRecord`` e la riga del registro con la
   fotografia dei requisiti verificati e la sua impronta SHA-256.

L'attestato parte dopo il commit (vedi ``_crea_record_completamento_elearning``).
"""
from __future__ import annotations

import hashlib
import json

from django.db import IntegrityError, transaction
from django.utils import timezone

from .elearning_regole import Regola, regola_corso


class RequisitiNonSoddisfatti(Exception):
    def __init__(self, mancanti: list[str]):
        super().__init__("; ".join(mancanti))
        self.mancanti = mancanti


def verifica(enr, regola: Regola, *, tentativo=None) -> tuple[dict, list[str]]:
    """Fotografia dei requisiti e lista di quelli mancanti (vuota = completabile)."""
    from ..models_elearning import TrainingElearningSlideView

    slide_attive = list(enr.corso.slides.filter(is_active=True).values_list("pk", flat=True))
    completate = set(TrainingElearningSlideView.objects.filter(
        enrollment=enr, completata=True, slide_id__in=slide_attive).values_list("slide_id", flat=True))
    secondi = int(type(enr).objects.filter(pk=enr.pk).values_list("secondi_accreditati", flat=True).first() or 0)
    mancanti = []
    if regola.richiede_tutte_slide and len(completate) < len(slide_attive):
        mancanti.append(f"slide completate {len(completate)}/{len(slide_attive)}")
    if regola.tempo_minimo_minuti and secondi < regola.tempo_minimo_minuti * 60:
        mancanti.append(f"tempo effettivo {secondi // 60}/{regola.tempo_minimo_minuti} minuti")
    quiz_ok = bool(tentativo and tentativo.superato and tentativo.enrollment_id == enr.pk)
    if regola.richiede_quiz and not quiz_ok:
        mancanti.append("quiz finale non superato")
    foto = {
        "ciclo": enr.ciclo,
        "slide_totali": len(slide_attive),
        "slide_completate": len(completate),
        "secondi_effettivi": secondi,
        "quiz": ({"tentativo": tentativo.pk, "token": tentativo.token, "punteggio_pct": str(tentativo.punteggio_pct),
                  "corrette": tentativo.n_corrette, "totali": tentativo.n_totali,
                  "iniziato_il": tentativo.iniziato_il.isoformat() if tentativo.iniziato_il else None,
                  "inviato_il": tentativo.inviato_il.isoformat() if tentativo.inviato_il else None}
                 if tentativo else None),
        "tentativi": enr.n_tentativi,
        "regola": regola.come_dict(),
        "verificato_il": timezone.now().isoformat(),
    }
    return foto, mancanti


class _CorsaPersa(Exception):
    pass


def completa(enr, *, tentativo=None, user=None):
    """Registra il completamento (una volta sola). Ritorna il ``TrainingEmployeeRecord``."""
    from ..models_elearning import TrainingElearningCompletamento
    try:
        return _completa(enr, tentativo=tentativo, user=user)
    except _CorsaPersa:
        # Corsa persa (DB senza lock reale): vale il completamento già scritto.
        return TrainingElearningCompletamento.objects.get(enrollment_id=enr.pk).record


def _completa(enr, *, tentativo=None, user=None):
    from ..models_elearning import TrainingElearningCompletamento
    from ..models_formazione import TrainingAssignment, TrainingElearningEnrollment

    with transaction.atomic():
        enr = TrainingElearningEnrollment.objects.select_for_update().select_related("corso").get(pk=enr.pk)
        # Stesso lucchetto di ``elearning_versioni.registra``: il completamento si
        # registra sulla versione in vigore, non su una che sta cambiando.
        from ..models_formazione import TrainingCourse
        enr.corso = TrainingCourse.objects.select_for_update().get(pk=enr.corso_id)
        esistente = TrainingElearningCompletamento.objects.filter(enrollment=enr).select_related("record").first()
        if esistente is not None:
            return esistente.record
        regola = regola_corso(enr.corso)
        foto, mancanti = verifica(enr, regola, tentativo=tentativo)
        if mancanti:
            raise RequisitiNonSoddisfatti(mancanti)
        from ..views import _crea_record_completamento_elearning
        record = _crea_record_completamento_elearning(enr.corso, enr.legacy_anagrafica_id, tentativo, user)
        canonico = json.dumps(foto, sort_keys=True, ensure_ascii=False)
        try:
            with transaction.atomic():
                TrainingElearningCompletamento.objects.create(
                    enrollment=enr, record=record, tentativo=tentativo, verifica_json=foto,
                    sha256=hashlib.sha256(canonico.encode()).hexdigest(),
                    creato_da=user if getattr(user, "is_authenticated", False) else None,
                )
        except IntegrityError:
            raise _CorsaPersa()
        enr.stato = "COMPLETATO"
        enr.data_completamento = timezone.localdate()
        enr.record_completamento = record
        enr.save(update_fields=["stato", "data_completamento", "record_completamento", "updated_at"])
        if tentativo is not None and tentativo.record_id is None:
            type(tentativo).objects.filter(pk=tentativo.pk).update(record=record)
        TrainingAssignment.objects.filter(
            corso=enr.corso, legacy_anagrafica_id=enr.legacy_anagrafica_id, ciclo=enr.ciclo,
        ).exclude(stato__in=("COMPLETATO", "ESONERATO")).update(stato="COMPLETATO")
        return record
