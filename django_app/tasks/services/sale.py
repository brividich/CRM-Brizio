"""Sale riunioni degli incontri KICK-OFF: disponibilità del giorno e risposta della sala.

Due fonti, sempre insieme:
- il portale: gli incontri già fissati in quella sala (funziona anche senza Outlook);
- Outlook (Graph ``getSchedule``): occupato/libero delle caselle delle sale e dei
  partecipanti, se l'integrazione è configurata e autorizzata.
Un errore di Outlook non toglie mai la vista del portale.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from ..models import KickoffMeeting, MeetingRoom, MeetingStatus

logger = logging.getLogger(__name__)

ORA_INIZIO = 8
ORA_FINE = 19

RISPOSTE = {
    "accepted": ("Sala confermata", "ok"),
    "tentativelyAccepted": ("Sala in forse", "warn"),
    "declined": ("Sala rifiutata: è già occupata", "danger"),
    "none": ("In attesa della risposta della sala", "info"),
    "notResponded": ("In attesa della risposta della sala", "info"),
    "organizer": ("Sala confermata", "ok"),
}


def _hhmm(valore: datetime) -> str:
    return valore.strftime("%H:%M")


def finestra_incontro(meeting) -> tuple[datetime, datetime] | None:
    from ..meeting_outlook import meeting_duration_minutes

    if not meeting.ora:
        return None
    inizio = datetime.combine(meeting.data, meeting.ora)
    return inizio, inizio + timedelta(minutes=meeting_duration_minutes(meeting))


def _si_sovrappone(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def sale_attive():
    return MeetingRoom.objects.filter(attiva=True).order_by("ordine", "nome")


def incontri_in_sala(giorno: date, *, escludi_id=None):
    qs = (
        KickoffMeeting.objects.filter(data=giorno, sala__isnull=False)
        .exclude(stato=MeetingStatus.ANNULLATO)
        .select_related("project", "sala")
        .prefetch_related("agenda_rows")
    )
    if escludi_id:
        qs = qs.exclude(pk=escludi_id)
    return qs


def _visite_reception(giorno: date) -> list[dict]:
    try:
        from reception.sale import blocchi_giorno

        return blocchi_giorno(giorno)
    except Exception as exc:  # noqa: BLE001 - la reception non toglie mai la vista degli incontri
        logger.warning("Visite della reception non lette (%s): %s", giorno, exc)
        return []


def disponibilita_giorno(
    giorno: date, *, escludi_id=None, organizer_email: str = "", partecipanti: list[str] | None = None,
) -> dict:
    sale = list(sale_attive())
    righe = {s.pk: {"id": s.pk, "nome": s.nome, "email": s.email, "capienza": s.capienza, "blocchi": []} for s in sale}
    finestre_portale: dict[int, list[tuple[datetime, datetime]]] = {}
    for m in incontri_in_sala(giorno, escludi_id=escludi_id):
        finestra = finestra_incontro(m)
        if finestra is None or m.sala_id not in righe:
            continue
        finestre_portale.setdefault(m.sala_id, []).append(finestra)
        righe[m.sala_id]["blocchi"].append({
            "inizio": _hhmm(finestra[0]), "fine": _hhmm(finestra[1]), "fonte": "portale",
            "titolo": f"Incontro {m.numero} · {m.project.name}",
        })
    # Le visite della reception con sala prenotata occupano la sala come gli incontri.
    for v in _visite_reception(giorno):
        if v["sala_id"] not in righe:
            continue
        finestre_portale.setdefault(v["sala_id"], []).append((v["inizio"], v["fine"]))
        righe[v["sala_id"]]["blocchi"].append({
            "inizio": _hhmm(v["inizio"]), "fine": _hhmm(v["fine"]), "fonte": "portale", "titolo": v["titolo"],
        })

    esito = {
        "giorno": giorno.isoformat(), "ora_inizio": ORA_INIZIO, "ora_fine": ORA_FINE,
        "sale": list(righe.values()), "partecipanti": None, "outlook": "non_configurato", "outlook_msg": "",
    }

    from core.outlook_calendar import get_schedule, graph_ready

    caselle_sale = {s.email.lower(): s.pk for s in sale if s.email}
    persone = [e for e in (partecipanti or []) if e and "@" in e][:15]
    if not graph_ready():
        esito["outlook_msg"] = "Outlook non configurato sul server: vedi solo gli incontri del portale."
        return esito
    if not organizer_email:
        esito["outlook_msg"] = "Manca un'email per interrogare Outlook: vedi solo gli incontri del portale."
        return esito
    if not caselle_sale and not persone:
        esito["outlook"] = "ok"
        return esito
    inizio = datetime.combine(giorno, time(ORA_INIZIO))
    fine = datetime.combine(giorno, time(ORA_FINE))
    escluso = None
    if escludi_id:
        corrente = KickoffMeeting.objects.filter(pk=escludi_id).prefetch_related("agenda_rows").first()
        escluso = finestra_incontro(corrente) if corrente else None
    try:
        calendario = get_schedule(
            organizer_email=organizer_email, emails=list(caselle_sale) + persone, start=inizio, end=fine,
        )
    except Exception as exc:
        logger.warning("Disponibilità sale da Outlook non letta (%s): %s", giorno, exc)
        esito["outlook"] = "errore"
        esito["outlook_msg"] = "Outlook non risponde o non autorizza la lettura dei calendari: vedi solo gli incontri del portale."
        return esito

    esito["outlook"] = "ok"
    for casella, sala_id in caselle_sale.items():
        for item in calendario.get(casella, []):
            finestra = (item["start"], item["end"])
            # L'incontro che stai modificando e quelli del portale già sincronizzati non si contano due volte.
            if escluso and finestra == escluso:
                continue
            if any(finestra == f for f in finestre_portale.get(sala_id, [])):
                continue
            righe[sala_id]["blocchi"].append({
                "inizio": _hhmm(item["start"]), "fine": _hhmm(item["end"]), "fonte": "outlook",
                "titolo": "Occupata in Outlook" if item["status"] != "tentative" else "Provvisoria in Outlook",
            })
    if persone:
        nomi = _nomi_per_email(persone)
        blocchi = []
        for email in persone:
            for item in calendario.get(email.lower(), []):
                finestra = (item["start"], item["end"])
                if escluso and finestra == escluso:
                    continue
                blocchi.append({
                    "inizio": _hhmm(item["start"]), "fine": _hhmm(item["end"]), "fonte": "persona",
                    "titolo": f"{nomi.get(email.lower(), email)} occupato" + (" (fuori sede)" if item["status"] == "oof" else ""),
                })
        esito["partecipanti"] = {"n": len(persone), "blocchi": blocchi}
    return esito


def _nomi_per_email(emails: list[str]) -> dict[str, str]:
    from django.contrib.auth import get_user_model

    nomi = {}
    for u in get_user_model().objects.filter(email__in=emails).only("email", "first_name", "last_name", "username"):
        nomi[(u.email or "").lower()] = u.get_full_name() or u.get_username()
    return nomi


def conflitti_portale(meeting) -> list[str]:
    """Incontri del portale nella stessa sala che si sovrappongono a questo."""
    if not meeting.sala_id:
        return []
    finestra = finestra_incontro(meeting)
    if finestra is None:
        return []
    messaggi = []
    for altro in incontri_in_sala(meeting.data, escludi_id=meeting.pk).filter(sala_id=meeting.sala_id):
        f = finestra_incontro(altro)
        if f and _si_sovrappone(finestra, f):
            messaggi.append(
                f"La sala {meeting.sala.nome} è già prenotata dalle {_hhmm(f[0])} alle {_hhmm(f[1])} "
                f"per l'incontro {altro.numero} di {altro.project.name}."
            )
    for v in _visite_reception(meeting.data):
        if v["sala_id"] == meeting.sala_id and _si_sovrappone(finestra, (v["inizio"], v["fine"])):
            messaggi.append(
                f"La sala {meeting.sala.nome} è già prenotata dalle {_hhmm(v['inizio'])} alle {_hhmm(v['fine'])} "
                f"per una visita ({v['titolo']})."
            )
    return messaggi


def aggiorna_risposta_sala(meeting) -> tuple[str, str]:
    """Legge da Outlook la risposta della sala all'invito e la salva. Ritorna (etichetta, classe)."""
    from core.outlook_calendar import get_event, graph_ready

    sala = meeting.sala if meeting.sala_id else None
    if sala is None or not sala.email:
        return ("", "")
    if not (graph_ready() and meeting.outlook_event_id and meeting.outlook_organizer_email):
        return ("Sala non prenotata in Outlook", "warn")
    evento = get_event(target_email=meeting.outlook_organizer_email, event_id=meeting.outlook_event_id)
    risposta = "none"
    for att in evento.get("attendees") or []:
        indirizzo = str((att.get("emailAddress") or {}).get("address") or "").lower()
        if indirizzo == sala.email.lower():
            risposta = str((att.get("status") or {}).get("response") or "none")
            break
    KickoffMeeting.objects.filter(pk=meeting.pk).update(sala_risposta=risposta, sala_risposta_at=timezone.now())
    meeting.sala_risposta = risposta
    return RISPOSTE.get(risposta, RISPOSTE["none"])
