"""Fruizione dei corsi e-learning da parte del discente: accesso, avanzamento, tentativi.

Regole verificate **lato server** (rilascio 1 del prompt 05):

- **Accesso**: il corso deve essere un e-learning pubblicato (attivo, stato ATTIVO).
  Il discente lo vede se gli è stato **assegnato** (assegnazione non esonerata)
  oppure se il corso è in **self-service** (``elearning_self_service``). Gli
  editor della formazione vedono anche le bozze in anteprima, senza che venga
  registrato nulla.
- **Avanzamento sequenziale**: la slide N si serve solo se tutte le precedenti sono
  già state viste; non si salta alla fine chiedendo l'URL dell'ultima.
- **Quiz**: disponibile solo dopo aver visto tutte le slide e solo se restano
  tentativi; a corso completato non si rifà.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

STATI_ASSEGNAZIONE_ATTIVI = ("ASSEGNATO", "IN_CORSO", "COMPLETATO", "SCADUTO", "RIMANDATO")


# Un corso è online solo con le regole FAD confermate dall'RSPP: l'interruttore
# «online» o una modifica delle regole non bastano a renderlo fruibile.
FILTRO_PUBBLICATI = {"is_elearning": True, "is_active": True, "stato": "ATTIVO",
                     "regola_superamento__confermata_rspp_il__isnull": False}


def corsi_pubblicati():
    from ..models_formazione import TrainingCourse
    return TrainingCourse.objects.filter(**FILTRO_PUBBLICATI)


def filtro_pubblicati(prefisso: str) -> dict:
    return {f"{prefisso}{k}": v for k, v in FILTRO_PUBBLICATI.items()}


def corso_pubblicato(corso) -> bool:
    if not (corso.is_elearning and corso.is_active and corso.stato == "ATTIVO"):
        return False
    from ..models_formazione import TrainingCompletionRule
    return TrainingCompletionRule.objects.filter(corso=corso, confermata_rspp_il__isnull=False).exists()


@dataclass
class Accesso:
    consentito: bool
    anteprima: bool = False  # editor su corso non pubblicato o non assegnato: nessuna registrazione
    motivo: str = ""


def accesso_discente(corso, legacy_id: int | None, *, is_editor: bool) -> Accesso:
    """Può il discente fruire del corso? (anteprima = solo visione per gli editor)."""
    if not corso.is_elearning:
        return Accesso(False, motivo="Non è un corso e-learning.")
    if not corso_pubblicato(corso):
        return Accesso(is_editor, anteprima=is_editor, motivo="Corso non pubblicato.")
    if legacy_id and (assegnato(corso, legacy_id) or corso.elearning_self_service):
        return Accesso(True)
    if is_editor:
        return Accesso(True, anteprima=True, motivo="Anteprima editor: non assegnato.")
    if not legacy_id:
        return Accesso(False, motivo="Il tuo profilo non è collegato all'anagrafica: contatta HR.")
    return Accesso(False, motivo="Questo corso non ti è stato assegnato.")


def assegnato(corso, legacy_id: int) -> bool:
    from ..models_formazione import TrainingAssignment
    return TrainingAssignment.objects.filter(
        corso=corso, legacy_anagrafica_id=legacy_id, stato__in=STATI_ASSEGNAZIONE_ATTIVI,
    ).exists()


def ordini_slide(corso) -> list[int]:
    return list(corso.slides.filter(is_active=True).order_by("ordine", "pk").values_list("ordine", flat=True))


def slide_consentita(enr, ordine: int, ordini: list[int]) -> bool:
    """La slide si serve se è già stata raggiunta o è la successiva alla più avanti vista."""
    if ordine not in ordini:
        return False
    if enr is None:
        return True  # anteprima editor
    raggiunte = [o for o in ordini if o <= (enr.ultima_slide_ordine or 0)]
    prossima = ordini[len(raggiunte)] if len(raggiunte) < len(ordini) else ordini[-1]
    return ordine <= prossima


def tutte_viste(enr, ordini: list[int]) -> bool:
    return bool(enr) and bool(ordini) and (enr.ultima_slide_ordine or 0) >= max(ordini)


def segna_slide_vista(corso, legacy_id: int, ordine: int, n_slide: int):
    """Aggiorna l'avanzamento sotto lock (avanza solo di una slide alla volta)."""
    with transaction.atomic():
        enr = iscrizione(corso, legacy_id, n_slide, lock=True)
        campi = []
        if ordine > (enr.ultima_slide_ordine or 0):
            enr.ultima_slide_ordine = ordine
            campi.append("ultima_slide_ordine")
        if enr.stato == "ISCRITTO":
            enr.stato = "IN_CORSO"
            campi.append("stato")
        if campi:
            enr.save(update_fields=campi + ["updated_at"])
    return enr


def ciclo_per_nuova_assegnazione(corso, legacy_id: int) -> int:
    """Ciclo di un'assegnazione manuale: se il ciclo corrente è già completato, il successivo."""
    from ..models_formazione import TrainingElearningEnrollment
    ciclo = ciclo_corrente(corso, legacy_id)
    completato = TrainingElearningEnrollment.objects.filter(
        corso=corso, legacy_anagrafica_id=legacy_id, ciclo=ciclo, stato="COMPLETATO").exists()
    return ciclo + 1 if completato else ciclo


def ciclo_corrente(corso, legacy_id: int) -> int:
    """Il ciclo in corso: il più alto fra iscrizioni e assegnazioni (1 se nessuno)."""
    from django.db.models import Max
    from ..models_formazione import TrainingAssignment, TrainingElearningEnrollment
    a = TrainingAssignment.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).aggregate(m=Max("ciclo"))["m"]
    e = TrainingElearningEnrollment.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).aggregate(m=Max("ciclo"))["m"]
    return max(a or 1, e or 1)


def iscrizione(corso, legacy_id: int, n_slide: int, *, lock: bool = False):
    """L'iscrizione del discente al ciclo corrente (creata se manca); ``lock`` = select_for_update."""
    from django.db import IntegrityError
    from ..models_formazione import TrainingElearningEnrollment
    chiave = {"corso": corso, "legacy_anagrafica_id": legacy_id, "ciclo": ciclo_corrente(corso, legacy_id)}
    try:
        with transaction.atomic():
            enr, _ = TrainingElearningEnrollment.objects.get_or_create(
                **chiave, defaults={"stato": "ISCRITTO", "n_slide_totali": n_slide,
                                    "versione_label_snapshot": (corso.versione or "")[:50]},
            )
    except IntegrityError:  # due richieste in parallelo (slide + battito): vale quella già scritta
        enr = TrainingElearningEnrollment.objects.get(**chiave)
    if lock:
        enr = TrainingElearningEnrollment.objects.select_for_update().get(pk=enr.pk)
    if enr.n_slide_totali != n_slide:
        enr.n_slide_totali = n_slide
        enr.save(update_fields=["n_slide_totali"])
    return enr


def sblocca_tentativi(enr, *, user, motivo: str, n: int | None = None):
    """Sblocco HR dei tentativi esauriti: aggiunge ``n`` tentativi (default: un giro intero)."""
    from django.core.exceptions import ValidationError
    from ..models_formazione import TrainingElearningEnrollment
    from .elearning_regole import regola_corso

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Il motivo dello sblocco è obbligatorio.")
    with transaction.atomic():
        enr = TrainingElearningEnrollment.objects.select_for_update().select_related("corso").get(pk=enr.pk)
        aggiunti = int(n or regola_corso(enr.corso).max_tentativi or 1)
        enr.tentativi_extra = (enr.tentativi_extra or 0) + aggiunti
        enr.save(update_fields=["tentativi_extra", "updated_at"])
    return enr, aggiunti
