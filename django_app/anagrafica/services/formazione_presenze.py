"""Scrittura delle presenze di una giornata a partire dalle firme rilevate.

Esiste per una ragione sola: **una sola strada di scrittura**.

Le firme di una giornata possono arrivare da due parti — la pagina di conferma
compilata da una persona, e la cartella di acquisizione dove la fotocopiatrice
deposita le scansioni. Se ciascuna si scrivesse le presenze per conto proprio,
prima o poi le due divergerebbero: una ricalcola le ore e l'altra no, una marca
il metodo di firma e l'altra se lo dimentica. Sarebbero due verità sullo stesso
fatto, e in audit una delle due sarebbe sbagliata.

Qui invece si passa un dizionario `{id_persona: (ingresso, uscita)}` e la
scrittura è quella, identica, da qualunque parte arrivi.

Chi non compare nel dizionario, o compare senza nessuna firma, **non viene
toccato**: l'assenza di una firma non è la prova di un'assenza, e sovrascrivere
una presenza già registrata a mano sarebbe un danno.
"""
from __future__ import annotations

__all__ = ["applica_firme_lezione"]


def applica_firme_lezione(lezione, firme: dict, *, utente=None, metodo: str = "UPLOAD") -> list:
    """Registra le firme sulla giornata. Ritorna gli iscritti toccati.

    `firme` è `{legacy_anagrafica_id: (firma_ingresso, firma_uscita)}`.
    Lo stato diventa `PRESENTE` con entrambe le firme, `PARZIALE` con una sola.
    """
    from django.utils import timezone

    from ..models_formazione import TrainingLessonAttendance
    from ..views import _ricalcola_presenza_enrollment
    from .training_turni import iscritti_attesi_lezione

    adesso = timezone.now()
    toccati = []

    for iscritto in iscritti_attesi_lezione(lezione.sessione, lezione):
        ingresso, uscita = firme.get(iscritto.legacy_anagrafica_id, (False, False))
        if not ingresso and not uscita:
            continue

        presenza, _ = TrainingLessonAttendance.objects.get_or_create(
            lezione=lezione, legacy_anagrafica_id=iscritto.legacy_anagrafica_id,
            defaults={"registrato_da": utente},
        )
        presenza.firma_ingresso = ingresso
        presenza.firma_uscita = uscita
        presenza.signature_status = "FIRMATO"
        presenza.signature_method = metodo
        presenza.signed_at = adesso
        presenza.stato_presenza = "PRESENTE" if (ingresso and uscita) else "PARZIALE"
        presenza.registrato_da = utente
        presenza.save()
        toccati.append(iscritto)

    for iscritto in toccati:
        _ricalcola_presenza_enrollment(iscritto)

    return toccati
