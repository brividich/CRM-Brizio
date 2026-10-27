"""Le assenze approvate nel calendario Outlook del capo, via Microsoft Graph.

Con «Assenze approvate nel calendario Outlook del capo» acceso (Area HR →
Calendario aziendale → Orario, patrono e solleciti), il job
``assenze_outlook_sync`` tiene allineato il calendario «Assenze del team
(NOVICROM HUB)» nelle caselle che lo hanno chiesto. Due modi:

- «su richiesta» (predefinito): solo le assenze per cui qualcuno ha chiesto
  «metti nel calendario» (``richiedi``): spunta all'inserimento, pulsante
  «Approva e metti in calendario» nella mail, spunta nella pagina del capo.
  Fa fede la casella di chi chiede; via mail, senza login, quella a cui è
  arrivato il link personale (il caporeparto);
- «tutte»: ogni assenza approvata va nel calendario del capo che la approva.

Per ogni casella:

- richiesta approvata (o programmata) → evento creato;
- richiesta spostata o cambiata → evento aggiornato;
- richiesta rifiutata, eliminata o tornata in attesa → evento tolto;
- evento cancellato dal capo in Outlook → non viene ricreato, finché la
  richiesta non cambia.

Nel modo «tutte» il capo è quello che approva: il capo scelto nella richiesta,
altrimenti quello dell'organigramma. Gli eventi sono «liberi»: non occupano l'agenda del capo.
Permesso applicativo Graph: ``Calendars.ReadWrite`` (lo stesso dello Scadenzario).
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
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


def _modo() -> str:
    from .hr import impostazioni

    try:
        return str(impostazioni().outlook_capo_modo or "richiesta")
    except Exception:
        return "richiesta"


def su_richiesta() -> bool:
    """Acceso e nel modo «su richiesta»: ha senso offrire la spunta / il pulsante."""
    return attivo() and _modo() == "richiesta"


def richiedi(assenza_ids, email: str, *, da: str = "") -> int:
    """Segna le richieste da mettere nel calendario di ``email``. Ritorna quante righe nuove.

    Una richiesta capofila di un permesso ripetuto porta con sé tutta la serie.
    Il job scrive l'evento al giro successivo, se e quando la richiesta è approvata.
    """
    from .models import AssenzaOutlook, AssenzaSerie

    email = str(email or "").strip().lower()
    if not email or "@" not in email or not attivo():
        return 0
    ids = {int(i) for i in (assenza_ids if isinstance(assenza_ids, (list, tuple, set)) else [assenza_ids])
           if str(i or "").strip().lstrip("-").isdigit()}
    if not ids:
        return 0
    ids |= set(AssenzaSerie.objects.filter(capofila_id__in=ids).values_list("assenza_id", flat=True))
    nuove = 0
    for rid in sorted(ids):
        _, creata = AssenzaOutlook.objects.get_or_create(
            assenza_id=rid, email=email, defaults={"richiesto_da": str(da or "")[:200]},
        )
        nuove += int(creata)
    return nuove


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

    tutte = _modo() == "tutte"
    oggi = timezone.localdate()
    dal = datetime(oggi.year, oggi.month, oggi.day) - timedelta(days=GIORNI_INDIETRO)
    al = datetime(oggi.year, oggi.month, oggi.day) + timedelta(days=GIORNI_AVANTI)
    righe = _richieste_approvate(dal, al)
    ids = [int(r["id"]) for r in righe]
    scelti = dict(AssenzaCapoScelto.objects.filter(assenza_id__in=ids).values_list("assenza_id", "capo_legacy_user_id"))
    mappa: dict[int, list] = defaultdict(list)
    for m in AssenzaOutlook.objects.all():
        mappa[m.assenza_id].append(m)
    cache_cal: dict[str, str] = {}
    creati = aggiornati = tolti = saltati = errori = scritture = 0

    def errore(rec, testo):
        nonlocal errori
        errori += 1
        rec.ultimo_errore = str(testo)[:500]
        rec.save()

    def togli_evento(rec) -> bool:
        """Cancella l'evento in Outlook (se c'è). False se Graph ha dato errore."""
        nonlocal scritture
        if not (rec.event_id and rec.email and not rec.rimosso_da_utente):
            return True
        try:
            cal_id = _calendario(rec.email, cache_cal)
            scritture += 1
            m365_graph.scrivi("DELETE", f"{_url_casella(rec.email)}/calendars/{cal_id}/events/{rec.event_id}",
                              permesso=PERMESSO)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("assenze.outlook: eliminazione evento assenza %s: %s", rec.assenza_id, exc)
            errore(rec, exc)
            return False

    for row in righe:
        if scritture >= MAX_SCRITTURE:
            break
        rid = int(row["id"])
        recs = mappa.pop(rid, [])
        if tutte and not recs:
            recs = [AssenzaOutlook(assenza_id=rid, email=_email_capo(row, scelti))]
        if not recs:
            continue  # su richiesta: nessuno l'ha chiesta
        payload = _evento(row)
        if payload is None:
            continue
        imp = impronta(payload)
        for rec in recs:
            if scritture >= MAX_SCRITTURE:
                break
            if rec.rimosso_da_utente:
                if rec.impronta == imp:
                    saltati += 1
                    continue
                rec.rimosso_da_utente, rec.event_id = False, ""  # la richiesta è cambiata: torna in calendario
            if rec.event_id and rec.impronta == imp and not rec.ultimo_errore:
                continue
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
                        # Cancellato in Outlook: non lo si ricrea finché la richiesta non cambia.
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
            except Exception as exc:  # noqa: BLE001 - una casella con problemi non ferma le altre
                logger.warning("assenze.outlook: assenza %s verso %s: %s", rid, rec.email, exc)
                errore(rec, exc)

    # Richieste fuori dall'elenco: approvate ma passate, in attesa, rifiutate o eliminate.
    restanti = [rec for recs in mappa.values() for rec in recs]
    stati: dict[int, int] = {}
    if restanti and _helpers._table_exists("assenze"):
        id_restanti = sorted({rec.assenza_id for rec in restanti})
        segnaposto = ", ".join(["%s"] * len(id_restanti))
        stati = {
            int(r["id"]): int(r.get("stato") or 0) for r in _helpers._fetch_all_dict(
                f"SELECT id, COALESCE(moderation_status, 2) AS stato FROM assenze WHERE id IN ({segnaposto})",
                id_restanti,
            )
        }
    for rec in restanti:
        stato_richiesta = stati.get(rec.assenza_id)
        if stato_richiesta in (0, 4):
            rec.delete()  # ancora approvata ma passata: l'evento resta, la riga no
            continue
        if scritture >= MAX_SCRITTURE:
            break
        in_attesa = stato_richiesta is not None and stato_richiesta not in (1,)
        if not togli_evento(rec):
            continue
        if in_attesa and rec.pk:
            # Tornata in attesa (o non ancora approvata): la richiesta di calendario resta.
            if rec.event_id or rec.impronta:
                tolti += int(bool(rec.event_id))
                rec.event_id, rec.impronta, rec.rimosso_da_utente, rec.ultimo_errore = "", "", False, ""
                rec.save()
            continue
        if rec.pk:
            rec.delete()
        tolti += int(bool(rec.event_id))

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
