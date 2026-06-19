"""Turni delle lezioni — assegnazione iscritto × lezione (NOVICROM HUB).

Una sessione può erogare lo stesso contenuto in più lezioni-turno (mattina /
pomeriggio, per la gestione dei turni di lavoro). :class:`TrainingEnrollmentLesson`
dice a quale turno partecipa ciascun iscritto.

Semantica **backward-compatible**: un'iscrizione *senza* alcuna riga turno è
considerata assegnata a **tutte** le lezioni della sessione (comportamento storico).
Appena le si assegna almeno un turno, vale solo quello/quelli.
"""
from __future__ import annotations


def mappa_turni_sessione(sessione) -> dict[int, set[int]]:
    """``{enrollment_id: {lezione_id, ...}}`` per gli iscritti che hanno turni espliciti.

    Gli iscritti assenti dalla mappa sono quelli "su tutte le lezioni" (default).
    """
    from ..models_formazione import TrainingEnrollmentLesson

    out: dict[int, set[int]] = {}
    for enr_id, lez_id in (
        TrainingEnrollmentLesson.objects
        .filter(enrollment__sessione=sessione)
        .values_list("enrollment_id", "lezione_id")
    ):
        out.setdefault(enr_id, set()).add(lez_id)
    return out


def iscritti_attesi_lezione(sessione, lezione, iscrizioni=None) -> list:
    """Iscrizioni *attese* alla ``lezione``: chi non ha turni (→ tutte) o è assegnato qui.

    ``iscrizioni`` opzionale = lista già caricata di :class:`TrainingEnrollment` della
    sessione (evita una query in più quando il chiamante le ha già).
    """
    from ..models_formazione import TrainingEnrollment

    if iscrizioni is None:
        iscrizioni = list(
            TrainingEnrollment.objects.filter(sessione=sessione)
            .order_by("legacy_anagrafica_id")
        )
    turni = mappa_turni_sessione(sessione)
    if not turni:
        return list(iscrizioni)  # nessun turno definito → tutti a tutte le lezioni
    return [
        e for e in iscrizioni
        if e.pk not in turni or lezione.pk in turni[e.pk]
    ]


def set_turni(enrollment, lezione_ids, user=None) -> None:
    """Imposta i turni di un'iscrizione = esattamente ``lezione_ids`` (idempotente).

    ``lezione_ids`` vuoto ⇒ rimuove tutte le righe (l'iscritto torna "su tutte le
    lezioni"). Vengono accettate solo lezioni appartenenti alla sessione dell'iscrizione.
    """
    from ..models_formazione import TrainingEnrollmentLesson, TrainingLesson

    valide = set(
        TrainingLesson.objects
        .filter(sessione_id=enrollment.sessione_id, pk__in=list(lezione_ids))
        .values_list("pk", flat=True)
    )
    attuali = set(
        TrainingEnrollmentLesson.objects
        .filter(enrollment=enrollment)
        .values_list("lezione_id", flat=True)
    )
    da_aggiungere = valide - attuali
    da_rimuovere = attuali - valide
    if da_rimuovere:
        TrainingEnrollmentLesson.objects.filter(
            enrollment=enrollment, lezione_id__in=da_rimuovere
        ).delete()
    for lez_id in da_aggiungere:
        TrainingEnrollmentLesson.objects.create(
            enrollment=enrollment, lezione_id=lez_id, assegnato_da=user,
        )
