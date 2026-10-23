"""«Aggiungi al calendario Outlook» nelle mail che riguardano un'assenza.

Due strade, perché il capo può leggere la mail da Outlook web o dal desktop:
- un pulsante che apre Outlook web (Microsoft 365) con l'evento già compilato;
- un allegato ``.ics`` che Outlook desktop apre come evento da salvare.

L'evento è l'assenza di un collaboratore, non un impegno del capo: è segnato
«libero» (TRANSP:TRANSPARENT, BUSYSTATUS FREE) così non occupa la sua agenda.
Tutto è best-effort: senza date leggibili non si aggiunge niente.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlencode

from django.utils import timezone

OUTLOOK_COMPOSE = "https://outlook.office.com/calendar/0/deeplink/compose"
ETICHETTA = "Aggiungi al calendario Outlook"


def _dt(value) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str) and value.strip():
        testo = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(testo)
        except ValueError:
            for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(testo[:16], fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt).replace(tzinfo=None)
    return dt


def sincronizzazione_graph_attiva() -> bool:
    """Con il calendario del capo scritto via Graph il pulsante creerebbe un doppione."""
    try:
        from assenze.outlook_sync import attivo

        return attivo()
    except Exception:
        return False


def evento_assenza(source_code, payload, *, forza: bool = False) -> dict | None:
    """Evento da calendario per una richiesta di assenza, oppure ``None``.

    Senza ``forza`` restituisce ``None`` anche quando le assenze arrivano già nel
    calendario del capo via Graph (``assenze.outlook_sync``): pulsante e allegato
    servirebbero solo a fare doppioni.
    """
    if str(source_code or "") != "assenze" or not isinstance(payload, dict):
        return None
    if not forza and sincronizzazione_graph_attiva():
        return None
    stato = str(payload.get("moderation_status") if payload.get("moderation_status") is not None else "").strip()
    if stato == "1" or "rifiut" in str(payload.get("consenso") or "").lower():
        return None
    inizio, fine = _dt(payload.get("data_inizio")), _dt(payload.get("data_fine"))
    if inizio is None or fine is None or fine < inizio:
        return None
    nome = str(payload.get("dipendente_nome") or payload.get("copia_nome") or "").strip() or "Dipendente"
    tipo = str(payload.get("tipo_assenza") or "Assenza").strip()
    intera = fine.date() > inizio.date() or (
        (inizio.hour, inizio.minute) == (0, 0) and (fine.hour, fine.minute) >= (23, 59)
    )
    motivo = str(payload.get("motivazione_richiesta") or "").strip()
    return {
        "uid": f"assenza-{payload.get('id') or inizio.strftime('%Y%m%d%H%M')}@novicromhub",
        "titolo": f"{tipo}: {nome}",
        "descrizione": f"{tipo} di {nome}" + (f" - {motivo}" if motivo else "") + ". Inserito da NOVICROM HUB.",
        "inizio": inizio,
        "fine": fine,
        "giornata_intera": intera,
    }


def link_outlook(ev: dict) -> str:
    """Apre Outlook web con l'evento compilato (giorni interi: fine esclusa, come vuole Outlook)."""
    if ev["giornata_intera"]:
        start = ev["inizio"].date().isoformat()
        end = (ev["fine"].date() + timedelta(days=1)).isoformat()
    else:
        start = ev["inizio"].strftime("%Y-%m-%dT%H:%M:%S")
        end = ev["fine"].strftime("%Y-%m-%dT%H:%M:%S")
    query = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": ev["titolo"],
        "startdt": start,
        "enddt": end,
        "allday": "true" if ev["giornata_intera"] else "false",
        "body": ev["descrizione"],
    }
    return f"{OUTLOOK_COMPOSE}?{urlencode(query)}"


def _ics_testo(value: str) -> str:
    return (str(value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r", "").replace("\n", "\\n"))


def ics(ev: dict) -> bytes:
    """File iCalendar (RFC 5545) con un evento «libero»."""
    if ev["giornata_intera"]:
        start = f"DTSTART;VALUE=DATE:{ev['inizio'].strftime('%Y%m%d')}"
        end = f"DTEND;VALUE=DATE:{(ev['fine'].date() + timedelta(days=1)).strftime('%Y%m%d')}"
    else:
        # Orari locali convertiti in UTC: nessuna definizione di fuso da allegare.
        def utc(dt):
            return timezone.make_aware(dt).astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        start = f"DTSTART:{utc(ev['inizio'])}"
        end = f"DTEND:{utc(ev['fine'])}"
    righe = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//NOVICROM HUB//Assenze//IT",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{ev['uid']}",
        f"DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        start,
        end,
        f"SUMMARY:{_ics_testo(ev['titolo'])}",
        f"DESCRIPTION:{_ics_testo(ev['descrizione'])}",
        "TRANSP:TRANSPARENT",
        "X-MICROSOFT-CDO-BUSYSTATUS:FREE",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(righe) + "\r\n").encode("utf-8")


def pulsante_html(ev: dict) -> str:
    """Pulsante per la riga CTA della mail (stesso stile dei pulsanti Approva/Rifiuta)."""
    return (
        f'<a href="{html.escape(link_outlook(ev))}" class="ecta" style="display:inline-block;padding:12px 22px;'
        f'background:#0f6cbd;color:#ffffff;text-decoration:none;border-radius:9px;font-size:14px;font-weight:800;'
        f'margin:0 10px 10px 0;">{ETICHETTA}</a>'
    )


def allega(message, ev: dict | None) -> None:
    """Allega l'evento ``.ics`` a un ``EmailMessage``. Non solleva mai."""
    if not ev:
        return
    try:
        message.attach("assenza.ics", ics(ev), "text/calendar; charset=utf-8; method=PUBLISH")
    except Exception:  # noqa: BLE001 - l'allegato non deve fermare la mail
        pass
