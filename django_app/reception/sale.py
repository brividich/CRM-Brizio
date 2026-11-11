"""Sala riunioni per una visita: le stesse sale del KICK-OFF (``tasks.MeetingRoom``).

- ``verifica``: la sala è libera nel portale (incontri KICK-OFF e altre visite)? Outlook decide
  poi da sé: una sala già occupata in Outlook rifiuta l'invito.
- ``prenota``: con la casella Microsoft 365 della sala l'evento nasce nel calendario del referente
  con la sala invitata come risorsa (come gli incontri KICK-OFF). Senza casella resta segnata
  solo nel portale.
- ``libera``: alla cancellazione dell'invito l'evento Outlook si cancella e la sala torna libera.
- ``blocchi_giorno``: le visite con sala di un giorno, per la griglia della reception (il KICK-OFF
  non le vede: per lui la sala risulta occupata da Outlook).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

MINUTI_PREDEFINITI = 60
FUSO_OUTLOOK = "W. Europe Standard Time"


def sale_attive():
    """Le sale proposte negli inviti: attive e scelte in Reception → Configurazione → Sale."""
    from tasks.services.sale import sale_attive as attive

    from .models import SalaInviti

    return attive().filter(pk__in=SalaInviti.objects.values("sala_id"))


def finestra(giorno: date | None, inizio: time | None, fine: time | None) -> tuple[datetime, datetime] | None:
    if not giorno or not inizio:
        return None
    a = datetime.combine(giorno, inizio)
    b = datetime.combine(giorno, fine) if fine else a + timedelta(minutes=MINUTI_PREDEFINITI)
    return (a, b) if b > a else (a, a + timedelta(minutes=MINUTI_PREDEFINITI))


def _visite_con_sala(giorno: date, *, escludi_pk=None):
    from .models import Preregistrazione

    qs = Preregistrazione.objects.select_related("sala").filter(data_visita=giorno, sala__isnull=False,
                                                                ora_inizio__isnull=False, scade_il__gte=timezone.now())
    return qs.exclude(pk=escludi_pk) if escludi_pk else qs


def blocchi_giorno(giorno: date) -> list[dict]:
    """``{sala_id, inizio, fine, titolo}`` delle visite con sala: nel titolo solo il referente, mai l'ospite."""
    righe = []
    for p in _visite_con_sala(giorno):
        f = finestra(p.data_visita, p.ora_inizio, p.ora_fine)
        if f:
            righe.append({"sala_id": p.sala_id, "inizio": f[0], "fine": f[1], "titolo": f"Visita ospiti · {p.referente_nome}"})
    return righe


def verifica(sala, giorno: date | None, inizio: time | None, fine: time | None, *, escludi_pk=None) -> str:
    """Messaggio d'errore se la sala non si può prenotare, stringa vuota se va bene."""
    f = finestra(giorno, inizio, fine)
    if f is None:
        return "Per prenotare la sala servono il giorno e l'ora di arrivo."
    from tasks.services.sale import finestra_incontro, incontri_in_sala

    for m in incontri_in_sala(giorno).filter(sala_id=sala.pk):
        altro = finestra_incontro(m)
        if altro and f[0] < altro[1] and altro[0] < f[1]:
            return f"La sala {sala.nome} è già prenotata dalle {altro[0]:%H:%M} alle {altro[1]:%H:%M} per un incontro KICK-OFF."
    for p in _visite_con_sala(giorno, escludi_pk=escludi_pk).filter(sala_id=sala.pk):
        altro = finestra(p.data_visita, p.ora_inizio, p.ora_fine)
        if altro and f[0] < altro[1] and altro[0] < f[1]:
            return f"La sala {sala.nome} è già prenotata dalle {altro[0]:%H:%M} alle {altro[1]:%H:%M} per una visita di {p.referente_nome}."
    return ""


def prenota(pre) -> tuple[str, str]:
    """Prenota in Outlook la sala della pre-registrazione. Ritorna (livello, messaggio) per l'utente."""
    from core.outlook_calendar import create_event, graph_ready

    sala = pre.sala
    if sala is None:
        return ("", "")
    if not sala.email:
        return ("info", f"Sala {sala.nome} segnata nel portale: non ha una casella Microsoft 365, in Outlook non è prenotata.")
    if not graph_ready():
        return ("warning", f"Sala {sala.nome} segnata nel portale, ma Outlook non è configurato sul server: prenotala anche in Outlook.")
    organizzatore = (pre.referente_email or "").strip().lower()
    f = finestra(pre.data_visita, pre.ora_inizio, pre.ora_fine)
    if "@" not in organizzatore or f is None:
        return ("warning", f"Sala {sala.nome} segnata nel portale, ma senza email del referente o ora non si prenota in Outlook.")
    azienda = f" ({pre.ospite_azienda})" if pre.ospite_azienda else ""
    payload = {
        "subject": f"Visita di {pre.ospite_nome}{azienda}"[:255],
        "body": {"contentType": "HTML", "content": f"<p>Visita prenotata dal NOVICROM HUB. Codice di accesso dell'ospite: <strong>{pre.codice}</strong>.</p>"
                                                    + (f"<p>Motivo: {pre.motivo}</p>" if pre.motivo else "")},
        "start": {"dateTime": f[0].strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": FUSO_OUTLOOK},
        "end": {"dateTime": f[1].strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": FUSO_OUTLOOK},
        "location": {"displayName": sala.nome, "locationEmailAddress": sala.email, "locationType": "conferenceRoom"},
        "attendees": [{"emailAddress": {"address": sala.email, "name": sala.nome}, "type": "resource"}],
        "showAs": "busy", "isReminderOn": True, "reminderMinutesBeforeStart": 15,
        "transactionId": f"hub-reception-prereg-{pre.pk}-{pre.codice}",
    }
    try:
        evento = create_event(target_email=organizzatore, payload=payload)
    except Exception as exc:  # noqa: BLE001 - la visita resta valida, la sala va prenotata a mano
        logger.warning("Reception: sala %s non prenotata in Outlook (prereg %s): %s", sala.pk, pre.pk, exc)
        return ("warning", f"Sala {sala.nome} segnata nel portale, ma Outlook non ha accettato la prenotazione: prenotala a mano.")
    type(pre).objects.filter(pk=pre.pk).update(outlook_event_id=str(evento.get("id") or "")[:255],
                                                outlook_organizer_email=organizzatore[:255])
    pre.outlook_event_id, pre.outlook_organizer_email = str(evento.get("id") or "")[:255], organizzatore[:255]
    return ("success", f"Sala {sala.nome} richiesta in Outlook dal calendario di {organizzatore}: se è già occupata la sala rifiuta e ti arriva la risposta.")


def libera(pre) -> None:
    """Cancella l'evento Outlook della visita (la sala torna libera). Gli errori si registrano e basta."""
    if not (pre.outlook_event_id and pre.outlook_organizer_email):
        return
    from core.outlook_calendar import delete_event, graph_ready

    if not graph_ready():
        return
    try:
        delete_event(target_email=pre.outlook_organizer_email, event_id=pre.outlook_event_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reception: evento Outlook della prereg %s non cancellato: %s", pre.pk, exc)
