"""Le assenze approvate nel calendario Outlook del capo, via Microsoft Graph.

Con «Assenze approvate nel calendario Outlook del capo» acceso (Area HR →
Calendario aziendale → Orario, patrono e solleciti), il job
``assenze_outlook_sync`` tiene allineato nella casella di ogni capo il
calendario «Assenze del team (NOVICROM HUB)»:

- richiesta approvata (o programmata) → evento creato;
- richiesta spostata o cambiata → evento aggiornato;
- richiesta rifiutata, eliminata o tornata in attesa → evento tolto;
- evento cancellato dal capo in Outlook → non viene ricreato, finché la
  richiesta non cambia.

Il capo è quello che approva: il capo scelto nella richiesta, altrimenti quello
dell'organigramma. Gli eventi sono «liberi»: non occupano l'agenda del capo.
Permesso applicativo Graph: ``Calendars.ReadWrite`` (lo stesso dello Scadenzario).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

PERMESSO = "Calendars.ReadWrite"
NOME_CALENDARIO = "Assenze del team (NOVICROM HUB)"
CATEGORIA = "NOVICROM HUB"
# Finestra delle richieste tenute in calendario: da una settimana fa a un anno avanti.
GIORNI_INDIETRO = 7
GIORNI_AVANTI = 365
MAX_SCRITTURE = 300  # per giro: il resto al giro dopo


def attivo() -> bool:
    from .hr import impostazioni

    try:
        return bool(impostazioni().outlook_capo_attivo)
    except Exception:
        return False


def _url_casella(email: str) -> str:
    from urllib.parse import quote

    from core import m365_graph

    return f"{m365_graph.GRAPH}/users/{quote(email)}"


def _calendario(email: str, cache: dict) -> str:
    """Id del calendario «Assenze del team (NOVICROM HUB)» del capo, creato la prima volta."""
    from core import m365_graph

    from .models import CalendarioOutlookCapo

    if email in cache:
        return cache[email]
    rec = CalendarioOutlookCapo.objects.filter(email=email).first()
    if rec and rec.calendario_id:
        stato, _ = m365_graph.scrivi("GET", f"{_url_casella(email)}/calendars/{rec.calendario_id}", permesso=PERMESSO)
        if stato != 404:
            cache[email] = rec.calendario_id
            return rec.calendario_id
    calendari = m365_graph.get_all(f"{_url_casella(email)}/calendars", permesso=PERMESSO, params={"$select": "id,name"})
    esistente = next((c for c in calendari if c.get("name") == NOME_CALENDARIO), None)
    if esistente:
        cal_id = str(esistente["id"])
    else:
        _, creato = m365_graph.scrivi("POST", f"{_url_casella(email)}/calendars", permesso=PERMESSO,
                                      json={"name": NOME_CALENDARIO, "color": "lightTeal"})
        cal_id = str(creato.get("id") or "")
    CalendarioOutlookCapo.objects.update_or_create(email=email, defaults={"calendario_id": cal_id})
    cache[email] = cal_id
    return cal_id


def _evento(row: dict) -> dict | None:
    """Payload Graph per una riga ``assenze``; ``None`` senza date leggibili."""
    from automazioni.calendario_outlook import evento_assenza

    from .views import _helpers

    tipo = _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta"))
    ev = evento_assenza("assenze", {**row, "dipendente_nome": str(row.get("copia_nome") or "").upper(),
                                    "tipo_assenza": tipo, "moderation_status": None}, forza=True)
    if ev is None:
        return None
    base = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    corpo = f"<p>{ev['descrizione']}</p>"
    if base.startswith(("https://", "http://")):
        corpo += f'<p><a href="{base}/assenze/calendario">Apri il calendario assenze</a></p>'
    if ev["giornata_intera"]:
        start = {"dateTime": f"{ev['inizio']:%Y-%m-%d}T00:00:00", "timeZone": "Europe/Rome"}
        end = {"dateTime": f"{ev['fine'].date() + timedelta(days=1):%Y-%m-%d}T00:00:00", "timeZone": "Europe/Rome"}
    else:
        start = {"dateTime": f"{ev['inizio']:%Y-%m-%dT%H:%M:%S}", "timeZone": "Europe/Rome"}
        end = {"dateTime": f"{ev['fine']:%Y-%m-%dT%H:%M:%S}", "timeZone": "Europe/Rome"}
    return {
        "subject": ev["titolo"][:250],
        "body": {"contentType": "HTML", "content": corpo},
        "start": start,
        "end": end,
        "isAllDay": ev["giornata_intera"],
        "showAs": "free",
        "isReminderOn": False,
        "categories": [CATEGORIA],
    }


def impronta(payload: dict) -> str:
    base = "|".join(str(payload.get(k)) for k in ("subject", "start", "end", "isAllDay"))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _richieste_approvate(dal: datetime, al: datetime) -> list[dict]:
    from .views import _helpers

    if not _helpers._table_exists("assenze"):
        return []
    cols = [c for c in (
        "id", "copia_nome", "email_esterna", "utente_id", "aliasusername", "tipo_assenza", "data_inizio",
        "data_fine", "motivazione_richiesta", "capo_reparto_id", "consenso", "moderation_status",
    ) if _helpers._has_assenze_column(c)]
    rows = _helpers._fetch_all_dict(
        f"SELECT {_helpers._quoted_columns(cols)} FROM assenze "
        "WHERE data_fine >= %s AND data_inizio < %s AND COALESCE(moderation_status, 2) IN (0, 4)",
        [dal, al],
    )
    return [r for r in rows if _helpers._tipo_for_display(r.get("tipo_assenza"), r.get("motivazione_richiesta"))
            != "Certifica presenza"]


def _email_capo(row: dict, scelti: dict) -> str:
    from .solleciti import _email_capo_scelto
    from .views import _helpers

    rid = int(row["id"])
    if rid in scelti:
        return _email_capo_scelto(scelti[rid])
    return _helpers._capo_email_for_row(row)


def sincronizza(now=None) -> dict:
    """Un giro di allineamento. Ritorna i contatori per il Run-log."""
    from core import m365_graph

    from .models import AssenzaCapoScelto, AssenzaOutlook
    from .views import _helpers

    if not attivo():
        return {"skipped": "calendario Outlook del capo spento nelle impostazioni HR"}
    if not m365_graph.configurato():
        return {"skipped": "Microsoft Graph non configurato"}

    now = now or timezone.now()
    oggi = timezone.localdate()
    dal = datetime(oggi.year, oggi.month, oggi.day) - timedelta(days=GIORNI_INDIETRO)
    al = datetime(oggi.year, oggi.month, oggi.day) + timedelta(days=GIORNI_AVANTI)
    righe = _richieste_approvate(dal, al)
    ids = [int(r["id"]) for r in righe]
    scelti = dict(AssenzaCapoScelto.objects.filter(assenza_id__in=ids).values_list("assenza_id", "capo_legacy_user_id"))
    mappa = {m.assenza_id: m for m in AssenzaOutlook.objects.all()}
    cache_cal: dict[str, str] = {}
    creati = aggiornati = tolti = saltati = errori = scritture = 0

    def errore(rec, testo):
        nonlocal errori
        errori += 1
        rec.ultimo_errore = str(testo)[:500]
        rec.save()

    for row in righe:
        if scritture >= MAX_SCRITTURE:
            break
        rid = int(row["id"])
        payload = _evento(row)
        if payload is None:
            continue
        imp = impronta(payload)
        rec = mappa.pop(rid, None)
        if rec is not None and rec.rimosso_da_utente:
            if rec.impronta == imp:
                saltati += 1
                continue
            rec.rimosso_da_utente, rec.event_id = False, ""  # la richiesta è cambiata: torna in calendario
        if rec is not None and rec.event_id and rec.impronta == imp and not rec.ultimo_errore:
            continue
        if rec is None:
            rec = AssenzaOutlook(assenza_id=rid)
        if not rec.email:
            rec.email = _email_capo(row, scelti)
        if not rec.email:
            errore(rec, "Capo senza email aziendale: impossibile scrivere nel suo calendario.")
            continue
        try:
            cal_id = _calendario(rec.email, cache_cal)
            base = f"{_url_casella(rec.email)}/calendars/{cal_id}/events"
            scritture += 1
            if rec.event_id:
                stato, _ = m365_graph.scrivi("PATCH", f"{base}/{rec.event_id}", permesso=PERMESSO, json=payload)
                if stato == 404:
                    # Cancellato dal capo in Outlook: non lo si ricrea finché la richiesta non cambia.
                    rec.rimosso_da_utente, rec.impronta, rec.ultimo_errore = True, imp, ""
                    rec.save()
                    saltati += 1
                    continue
                aggiornati += 1
            else:
                _, evento = m365_graph.scrivi("POST", base, permesso=PERMESSO, json=payload)
                rec.event_id = str(evento.get("id") or "")
                creati += 1
            rec.impronta, rec.ultimo_errore = imp, ""
            rec.save()
        except Exception as exc:  # noqa: BLE001 - un capo con problemi non ferma gli altri
            logger.warning("assenze.outlook: assenza %s verso %s: %s", rid, rec.email, exc)
            errore(rec, exc)

    # Richieste non più approvate (rifiutate, eliminate, tornate in attesa) o fuori finestra.
    restanti = list(mappa.values())
    ancora = set()
    if restanti and _helpers._table_exists("assenze"):
        segnaposto = ", ".join(["%s"] * len(restanti))
        ancora = {
            int(r["id"]) for r in _helpers._fetch_all_dict(
                f"SELECT id FROM assenze WHERE id IN ({segnaposto}) AND COALESCE(moderation_status, 2) IN (0, 4)",
                [m.assenza_id for m in restanti],
            )
        }
    for rec in restanti:
        if rec.assenza_id in ancora:
            rec.delete()  # ancora approvata ma passata: l'evento resta, la riga no
            continue
        if scritture >= MAX_SCRITTURE:
            break
        if rec.event_id and rec.email and not rec.rimosso_da_utente:
            try:
                cal_id = _calendario(rec.email, cache_cal)
                scritture += 1
                m365_graph.scrivi("DELETE", f"{_url_casella(rec.email)}/calendars/{cal_id}/events/{rec.event_id}",
                                  permesso=PERMESSO)
            except Exception as exc:  # noqa: BLE001
                logger.warning("assenze.outlook: eliminazione evento assenza %s: %s", rec.assenza_id, exc)
                errore(rec, exc)
                continue
        rec.delete()
        tolti += 1

    return {"creati": creati, "aggiornati": aggiornati, "tolti": tolti, "lasciati_fuori": saltati, "errori": errori}


def stato() -> dict:
    """Riepilogo per la pagina HR: quanti eventi, quanti errori e gli ultimi messaggi."""
    from .models import AssenzaOutlook

    qs = AssenzaOutlook.objects.all()
    errori = list(qs.exclude(ultimo_errore="").order_by("-aggiornato_il")[:5])
    ultimo = qs.order_by("-aggiornato_il").values_list("aggiornato_il", flat=True).first()
    return {
        "eventi": qs.exclude(event_id="").filter(rimosso_da_utente=False).count(),
        "rimossi": qs.filter(rimosso_da_utente=True).count(),
        "n_errori": qs.exclude(ultimo_errore="").count(),
        "errori": errori,
        "ultimo": ultimo,
    }
