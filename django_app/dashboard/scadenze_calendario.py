"""Le scadenze dello Scadenzario nei calendari: file .ics e calendario Outlook personale.

- ``genera_ics``: le voci filtrate di ``/scadenze`` come file iCalendar (RFC 5545),
  un evento di un giorno per scadenza, da importare in Outlook o in qualsiasi
  calendario. Lo scarica chi è collegato: nessun indirizzo pubblico.
- ``sincronizza_utente``: per chi lo sceglie in Impostazioni notifiche, ogni
  mattina il portale tiene allineato il calendario «Scadenze NOVICROM HUB» nella
  sua casella Outlook (Graph, permesso applicativo ``Calendars.ReadWrite``).
  Dal portale a Outlook: scadenze nuove, spostate o chiuse diventano eventi
  creati, aggiornati o tolti. Da Outlook al portale: un evento cancellato dalla
  persona non viene ricreato (finché la scadenza non cambia data).

Le voci sono quelle che la persona vede nello Scadenzario, con gli stessi
permessi (``scadenze_digest.voci_per_utente``), scadute e prossimi 90 giorni.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

NOME_CALENDARIO = "Scadenze NOVICROM HUB"
PERMESSO = "Calendars.ReadWrite"
GIORNI = 90
CATEGORIA = "NOVICROM HUB"


def chiave_voce(v) -> str:
    base = "|".join(str(x or "") for x in (v.source, v.kind, v.soggetto, v.titolo, v.url))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _titolo(v) -> str:
    parti = [v.kind_label or v.source_label, v.titolo]
    testo = ": ".join(p for p in parti if p)
    return f"{testo} — {v.soggetto}" if v.soggetto else testo


def _link(v, base: str = "") -> str:
    """Link assoluto al portale (da ``SITE_URL`` o dall'indirizzo della richiesta); "" se non si può."""
    base = (base or str(getattr(settings, "SITE_URL", "") or "")).rstrip("/")
    if not v.url:
        return ""
    link = v.url if v.url.startswith("http") else f"{base}{v.url}"
    return link if link.startswith(("https://", "http://")) else ""


def impronta(v) -> str:
    return hashlib.sha256(f"{_titolo(v)}|{v.data_scadenza}|{_link(v)}".encode("utf-8")).hexdigest()


# ── .ics ─────────────────────────────────────────────────────────────────────


def _escape(testo: str) -> str:
    return (str(testo or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _piega(riga: str) -> str:
    """Righe al massimo di 75 ottetti (RFC 5545 §3.1)."""
    out, corrente = [], ""
    for car in riga:
        if len((corrente + car).encode("utf-8")) > 75:
            out.append(corrente)
            corrente = " " + car
        else:
            corrente += car
    out.append(corrente)
    return "\r\n".join(out)


def genera_ics(voci, *, adesso=None, base_url: str = "") -> bytes:
    adesso = adesso or timezone.now()
    stamp = adesso.astimezone(timezone.get_fixed_timezone(0)).strftime("%Y%m%dT%H%M%SZ")
    righe = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NOVICROM HUB//Scadenzario//IT", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{NOME_CALENDARIO}"]
    for v in voci:
        if not v.data_scadenza:
            continue
        link = _link(v, base_url)
        descrizione = " · ".join(x for x in (v.source_label, v.reparto, link) if x)
        righe += [
            "BEGIN:VEVENT",
            f"UID:{chiave_voce(v)}@novicrom-hub",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{v.data_scadenza:%Y%m%d}",
            f"DTEND;VALUE=DATE:{(v.data_scadenza + timedelta(days=1)):%Y%m%d}",
            f"SUMMARY:{_escape(_titolo(v))}",
            f"DESCRIPTION:{_escape(descrizione)}",
            f"CATEGORIES:{CATEGORIA}",
            "TRANSP:TRANSPARENT",
        ]
        if link:
            righe.append(f"URL:{link}")
        righe += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(_titolo(v))}", "TRIGGER:-PT15H", "END:VALARM",
                  "END:VEVENT"]
    righe.append("END:VCALENDAR")
    return ("\r\n".join(_piega(r) for r in righe) + "\r\n").encode("utf-8")


# ── Calendario Outlook ───────────────────────────────────────────────────────


def _evento(v) -> dict:
    link = _link(v)
    corpo = f"<p>{v.source_label}{' · ' + v.reparto if v.reparto else ''}</p>"
    if link:
        corpo += f'<p><a href="{link}">Apri nel portale</a></p>'
    giorno = v.data_scadenza
    return {
        "subject": _titolo(v)[:250],
        "body": {"contentType": "HTML", "content": corpo},
        "start": {"dateTime": f"{giorno:%Y-%m-%d}T00:00:00", "timeZone": "Europe/Rome"},
        "end": {"dateTime": f"{(giorno + timedelta(days=1)):%Y-%m-%d}T00:00:00", "timeZone": "Europe/Rome"},
        "isAllDay": True,
        "showAs": "free",
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 15 * 60,  # il giorno prima alle 9
        "categories": [CATEGORIA],
    }


def _url_casella(email: str) -> str:
    from urllib.parse import quote

    from core import m365_graph

    return f"{m365_graph.GRAPH}/users/{quote(email)}"


def _calendario(canali, email: str) -> str:
    """Id del calendario «Scadenze NOVICROM HUB», creato la prima volta."""
    from core import m365_graph

    if canali.outlook_calendario_id:
        stato, _ = m365_graph.scrivi("GET", f"{_url_casella(email)}/calendars/{canali.outlook_calendario_id}",
                                     permesso=PERMESSO)
        if stato != 404:
            return canali.outlook_calendario_id
    calendari = m365_graph.get_all(f"{_url_casella(email)}/calendars", permesso=PERMESSO, params={"$select": "id,name"})
    esistente = next((c for c in calendari if c.get("name") == NOME_CALENDARIO), None)
    if esistente:
        cal_id = str(esistente["id"])
    else:
        _, creato = m365_graph.scrivi("POST", f"{_url_casella(email)}/calendars", permesso=PERMESSO,
                                      json={"name": NOME_CALENDARIO, "color": "lightOrange"})
        cal_id = str(creato.get("id") or "")
    canali.outlook_calendario_id = cal_id
    canali.save(update_fields=["outlook_calendario_id", "updated_at"])
    return cal_id


def sincronizza_utente(canali, *, oggi: date | None = None, voci=None) -> dict:
    from core import m365_graph
    from core.models import ScadenzaOutlook
    from dashboard.scadenze_digest import _email_utente, voci_per_utente

    user = canali.user
    email = _email_utente(user)
    if not email:
        raise m365_graph.GraphError("Nessuna email aziendale per questa persona.")
    if voci is None:
        voci = voci_per_utente(user, giorni=GIORNI, oggi=oggi)
    voci = [v for v in voci if v.data_scadenza]
    cal_id = _calendario(canali, email)
    base = f"{_url_casella(email)}/calendars/{cal_id}/events"
    # Da Outlook: gli eventi ancora presenti (quelli cancellati dalla persona non si ricreano).
    presenti = {str(e.get("id")) for e in m365_graph.get_all(base, permesso=PERMESSO,
                                                             params={"$select": "id", "$top": "500"}, max_pages=20)}
    mappa = {m.chiave: m for m in ScadenzaOutlook.objects.filter(user=user)}
    creati = aggiornati = tolti = saltati = 0
    viste = set()
    for v in voci:
        chiave = chiave_voce(v)
        viste.add(chiave)
        imp = impronta(v)
        riga = mappa.get(chiave)
        if riga and riga.event_id and riga.event_id not in presenti and not riga.rimosso_da_utente:
            riga.rimosso_da_utente = True
            riga.save(update_fields=["rimosso_da_utente", "aggiornato_il"])
        if riga and riga.rimosso_da_utente:
            if riga.data_scadenza == v.data_scadenza:
                saltati += 1
                continue
            riga.rimosso_da_utente = False  # la scadenza è cambiata: torna in calendario
            riga.event_id = ""
        if riga and riga.event_id and riga.impronta == imp:
            continue
        if riga and riga.event_id:
            stato, _ = m365_graph.scrivi("PATCH", f"{base}/{riga.event_id}", permesso=PERMESSO, json=_evento(v))
            if stato != 404:
                riga.impronta, riga.data_scadenza = imp, v.data_scadenza
                riga.save(update_fields=["impronta", "data_scadenza", "aggiornato_il"])
                aggiornati += 1
                continue
        _, evento = m365_graph.scrivi("POST", base, permesso=PERMESSO, json=_evento(v))
        ScadenzaOutlook.objects.update_or_create(
            user=user, chiave=chiave,
            defaults={"event_id": str(evento.get("id") or ""), "data_scadenza": v.data_scadenza, "impronta": imp,
                      "rimosso_da_utente": False},
        )
        creati += 1
    # Scadenze chiuse o non più visibili: l'evento esce dal calendario.
    for chiave, riga in mappa.items():
        if chiave in viste:
            continue
        if riga.event_id and riga.event_id in presenti:
            m365_graph.scrivi("DELETE", f"{base}/{riga.event_id}", permesso=PERMESSO)
        riga.delete()
        tolti += 1
    return {"creati": creati, "aggiornati": aggiornati, "tolti": tolti, "lasciati_fuori": saltati}


def svuota_utente(canali) -> int:
    """La persona ha spento l'opzione: gli eventi del portale escono dal suo calendario."""
    from core import m365_graph
    from core.models import ScadenzaOutlook
    from dashboard.scadenze_digest import _email_utente

    righe = list(ScadenzaOutlook.objects.filter(user=canali.user))
    email = _email_utente(canali.user)
    if email and canali.outlook_calendario_id:
        base = f"{_url_casella(email)}/calendars/{canali.outlook_calendario_id}/events"
        for r in righe:
            if r.event_id and not r.rimosso_da_utente:
                m365_graph.scrivi("DELETE", f"{base}/{r.event_id}", permesso=PERMESSO)
    ScadenzaOutlook.objects.filter(user=canali.user).delete()
    return len(righe)


def sincronizza_tutti(*, oggi: date | None = None) -> dict:
    """Schedule ``scadenze_outlook_sync``: allinea chi ha scelto il calendario, svuota chi l'ha spento."""
    from core import m365_graph
    from core.models import NotificaCanali, ScadenzaOutlook

    if not m365_graph.configurato():
        return {"ok": False, "motivo": "Graph non configurato"}
    esito = {"persone": 0, "errori": 0, "svuotati": 0}
    con_righe = set(ScadenzaOutlook.objects.values_list("user_id", flat=True))
    for canali in NotificaCanali.objects.select_related("user").filter(user__is_active=True):
        if not canali.outlook_scadenze:
            if canali.user_id in con_righe:
                try:
                    svuota_utente(canali)
                    esito["svuotati"] += 1
                except m365_graph.GraphError as exc:
                    logger.warning("Scadenze Outlook: svuotamento %s: %s", canali.user_id, exc)
            continue
        try:
            sincronizza_utente(canali, oggi=oggi)
            canali.outlook_errore = ""
            esito["persone"] += 1
        except Exception as exc:  # noqa: BLE001 - una casella che non risponde non ferma le altre
            logger.warning("Scadenze Outlook: %s: %s", canali.user_id, exc)
            canali.outlook_errore = str(exc)[:300]
            esito["errori"] += 1
        canali.outlook_ultimo_sync = timezone.now()
        canali.save(update_fields=["outlook_errore", "outlook_ultimo_sync", "updated_at"])
    return {"ok": True, **esito}
