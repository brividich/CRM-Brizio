"""Fruizione dei corsi e-learning da parte del discente: accesso, avanzamento, tentativi.

Regole verificate **lato server** (rilascio 1 del prompt 05):

- **Accesso**: il corso deve essere un e-learning pubblicato (attivo, stato ATTIVO).
  Il discente lo vede se gli è stato **assegnato** (assegnazione non esonerata)
  oppure se il corso è **facoltativo** (self-service: ``obbligatorio=False``). Gli
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


def corso_pubblicato(corso) -> bool:
    return bool(corso.is_elearning and corso.is_active and corso.stato == "ATTIVO")


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
    if legacy_id and (assegnato(corso, legacy_id) or not corso.obbligatorio):
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


def tentativi_massimi(enr, cfg) -> int:
    """0 = illimitati. Lo sblocco HR aggiunge tentativi (``tentativi_extra``)."""
    base = int(cfg.max_tentativi_quiz or 0)
    return base + int(getattr(enr, "tentativi_extra", 0) or 0) if base else 0


def tentativi_esauriti(enr, cfg) -> bool:
    massimo = tentativi_massimi(enr, cfg)
    return bool(massimo) and (enr.n_tentativi or 0) >= massimo


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


def iscrizione(corso, legacy_id: int, n_slide: int, *, lock: bool = False):
    """L'iscrizione del discente (creata se manca); ``lock`` = select_for_update."""
    from ..models_formazione import TrainingElearningEnrollment
    enr, _ = TrainingElearningEnrollment.objects.get_or_create(
        corso=corso, legacy_anagrafica_id=legacy_id,
        defaults={"stato": "ISCRITTO", "n_slide_totali": n_slide},
    )
    if lock:
        enr = TrainingElearningEnrollment.objects.select_for_update().get(pk=enr.pk)
    if enr.n_slide_totali != n_slide:
        enr.n_slide_totali = n_slide
        enr.save(update_fields=["n_slide_totali"])
    return enr


def sblocca_tentativi(enr, *, user, motivo: str, n: int | None = None):
    """Sblocco HR dei tentativi esauriti: aggiunge ``n`` tentativi (default: un giro intero)."""
    from django.core.exceptions import ValidationError
    from ..models_formazione import ElearningConfig, TrainingElearningEnrollment

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Il motivo dello sblocco è obbligatorio.")
    cfg = ElearningConfig.get_instance()
    with transaction.atomic():
        enr = TrainingElearningEnrollment.objects.select_for_update().get(pk=enr.pk)
        aggiunti = int(n or cfg.max_tentativi_quiz or 1)
        enr.tentativi_extra = (enr.tentativi_extra or 0) + aggiunti
        enr.save(update_fields=["tentativi_extra", "updated_at"])
    return enr, aggiunti
