"""Sincronizzazione bidirezionale ticket MAN <-> lista SharePoint «Ticket» (CNManutenzioni).

Stesso schema delle assenze (``assenze/views/sharepoint.py``):

- ogni salvataggio di un ticket MAN entra nella coda ``TicketSharePointOutbox``
  (segnale ``post_save``); il giro periodico la invia a SharePoint via Graph;
- poi legge solo gli elementi cambiati su SharePoint (delta query) e li applica
  ai ticket collegati da ``sharepoint_item_id``; gli elementi nuovi diventano
  ticket MAN;
- un ticket con modifiche ancora in coda non viene sovrascritto dalla lettura:
  vince la modifica locale non ancora inviata;
- le scritture della lettura non rimettono il ticket in coda e non fanno partire
  le automazioni del portale (le mail partirebbero due volte).

Interruttore, sito e lista in Ticket → Impostazioni → Manutenzione. Spento =
nessuna chiamata a SharePoint e nessuna riga in coda. Commenti, allegati,
interventi, SLA ed escalation restano solo sul portale.
"""
from __future__ import annotations

import logging
import threading

import requests
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_save
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    PrioritaTicket,
    StatoTicket,
    Ticket,
    TicketCommento,
    TicketImpostazioni,
    TicketSharePointOutbox,
    TicketStatoLog,
    TipoTicket,
)

logger = logging.getLogger("tickets.sharepoint_man")

GRAPH = "https://graph.microsoft.com/v1.0"
AUTORE_SYNC = "SharePoint"

# Nomi interni delle colonne della lista «Ticket» di CNManutenzioni.
COL_TITOLO = "Title"
COL_DESCRIZIONE = "Description"
COL_PRIORITA = "Priority"
COL_STATO = "Status"
COL_TIPOLOGIA = "Tipologiaproblema"
COL_MACCHINARIO = "Macchinario"
COL_NOTE = "Note"
COL_CHIUSO = "Chiuso"
COL_DATA_CHIUSURA = "Datachiusuraticket"
COL_DATA_FINE_LAVORI = "Datafinelavori"
COL_DATA_SEGNALAZIONE = "DateReported"
COL_SICUREZZA = "Impattosusicurezza"
COL_ASSEGNATO = "Assegnatoa_x003a_"

PRIORITA_A_SP = {
    PrioritaTicket.URGENTE: "Critica",
    PrioritaTicket.ALTA: "Alta",
    PrioritaTicket.MEDIA: "Normale",
    PrioritaTicket.BASSA: "Bassa",
}
PRIORITA_DA_SP = {v.lower(): k for k, v in PRIORITA_A_SP.items()}

STATO_A_SP = {
    StatoTicket.APERTA: "Nuovo",
    StatoTicket.IN_CARICO: "In corso",
    StatoTicket.IN_ATTESA: "Bloccato",
    StatoTicket.RISOLTO: "Completato",
    StatoTicket.CHIUSO: "Completato",
    StatoTicket.ANNULLATO: "Non implementabile",
}
STATO_DA_SP = {
    "nuovo": StatoTicket.APERTA,
    "in corso": StatoTicket.IN_CARICO,
    "bloccato": StatoTicket.IN_ATTESA,
    "da progettazione": StatoTicket.IN_ATTESA,
    "completato": StatoTicket.RISOLTO,
    "duplica": StatoTicket.ANNULLATO,
    "non implementabile": StatoTicket.ANNULLATO,
}
# Su SharePoint «Chiuso» vale per CHIUSO e ANNULLATO; RISOLTO = Completato ma non chiuso.
STATI_CHIUSI_SP = (StatoTicket.CHIUSO, StatoTicket.ANNULLATO)

TIPOLOGIA_STRUTTURALE = "Manutenzione strutturale"
TIPOLOGIA_MACCHINARIO = "Manutenzione macchinario"
TIPOLOGIA_ALTRO = "Altro"
CATEGORIE_MACCHINARIO = {"CNC", "MACCHINARIO"}
CATEGORIA_DA_TIPOLOGIA = {
    TIPOLOGIA_STRUTTURALE.lower(): "STRUTTURALE",
    TIPOLOGIA_MACCHINARIO.lower(): "MACCHINARIO",
    TIPOLOGIA_ALTRO.lower(): "ALTRO_MAN",
}

_LOCK_KEY = "tickets:man_sp_sync:lock"
_LOCK_TTL = 600

_locale = threading.local()


# ─── Configurazione ──────────────────────────────────────────────────────────

def configurazione() -> dict | None:
    """Sito e lista se la sincronizzazione MAN e' accesa e completa, altrimenti None."""
    from core.graph_utils import is_placeholder_value

    cfg = TicketImpostazioni.objects.filter(tipo=TipoTicket.MAN).first()
    if not cfg or not cfg.sharepoint_sync_attivo:
        return None
    site_id = (cfg.sharepoint_site_id or "").strip()
    list_id = (cfg.sharepoint_list_id or "").strip()
    if not site_id or not list_id:
        return None
    cred = _credenziali()
    if any(not v or is_placeholder_value(v) for v in cred.values()):
        return None
    return {"site_id": site_id, "list_id": list_id}


def _credenziali() -> dict[str, str]:
    from config.env_config import get_first_env_value

    return {
        "tenant_id": get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
    }


def _headers() -> dict[str, str]:
    from core.graph_utils import acquire_graph_token

    c = _credenziali()
    token = acquire_graph_token(c["tenant_id"], c["client_id"], c["client_secret"])
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _items_url(conf: dict) -> str:
    return f"{GRAPH}/sites/{conf['site_id']}/lists/{conf['list_id']}/items"


def _delta_key(conf: dict) -> str:
    return f"tickets:man_sp_sync:delta:{conf['list_id']}"


# ─── Coda locale ─────────────────────────────────────────────────────────────

def accoda(ticket: Ticket) -> bool:
    """Mette il ticket MAN in coda verso SharePoint. No-op se la sync e' spenta."""
    if getattr(_locale, "in_lettura", False):
        return False
    if not ticket or not ticket.pk or ticket.tipo != TipoTicket.MAN:
        return False
    if configurazione() is None:
        return False
    row, created = TicketSharePointOutbox.objects.get_or_create(ticket_id=ticket.pk)
    if not created:
        row.save(update_fields=["queued_at"])
    transaction.on_commit(_invio_immediato)
    return True


def _invio_immediato() -> None:
    """Invio subito dopo il salvataggio; se il cluster non c'e' ci pensa il giro periodico."""
    try:
        from django_q.tasks import async_task

        async_task("tickets.tasks.run_ticket_man_sharepoint_push")
    except Exception:
        logger.debug("invio immediato ticket MAN non accodato", exc_info=True)


def _su_salvataggio_ticket(sender, instance: Ticket, **kwargs) -> None:
    if kwargs.get("raw"):
        return
    try:
        accoda(instance)
    except Exception:
        # La coda non deve mai far fallire il salvataggio del ticket.
        logger.exception("Ticket %s: accodamento verso SharePoint fallito", instance.pk)


def collega_segnali() -> None:
    post_save.connect(_su_salvataggio_ticket, sender=Ticket, dispatch_uid="tickets_man_sharepoint_outbox")


# ─── Portale -> SharePoint ───────────────────────────────────────────────────

def _tipologia_per_categoria(categoria: str) -> str:
    cat = (categoria or "").upper()
    if cat == "STRUTTURALE":
        return TIPOLOGIA_STRUTTURALE
    if cat in CATEGORIE_MACCHINARIO:
        return TIPOLOGIA_MACCHINARIO
    return TIPOLOGIA_ALTRO


def campi_per_sharepoint(ticket: Ticket, *, nuovo: bool) -> dict:
    campi = {
        COL_TITOLO: (ticket.titolo or ticket.numero_ticket)[:255],
        COL_DESCRIZIONE: ticket.descrizione or "",
        COL_PRIORITA: PRIORITA_A_SP.get(ticket.priorita, "Normale"),
        COL_STATO: STATO_A_SP.get(ticket.stato, "Nuovo"),
        COL_TIPOLOGIA: _tipologia_per_categoria(ticket.categoria),
        COL_NOTE: ticket.note_interne or "",
        COL_SICUREZZA: bool(ticket.incide_sicurezza),
        COL_CHIUSO: ticket.stato in STATI_CHIUSI_SP,
        COL_DATA_CHIUSURA: (
            ticket.closed_at.isoformat() if ticket.stato in STATI_CHIUSI_SP and ticket.closed_at else None
        ),
    }
    macchinario = (ticket.asset_descrizione_libera or "").strip() or (
        ticket.asset.name if ticket.asset_id and ticket.asset else ""
    )
    if macchinario:
        campi[COL_MACCHINARIO] = macchinario[:255]
    if nuovo:
        campi[COL_DATA_SEGNALAZIONE] = (ticket.created_at or timezone.now()).isoformat()
        if campi[COL_DATA_CHIUSURA] is None:
            del campi[COL_DATA_CHIUSURA]
    return campi


def invia_coda(limite: int = 200) -> dict:
    conf = configurazione()
    if conf is None:
        return {"skipped": "sincronizzazione spenta"}
    totali = {"creati": 0, "aggiornati": 0, "falliti": 0}
    righe = list(TicketSharePointOutbox.objects.select_related("ticket", "ticket__asset").order_by("queued_at")[:limite])
    if not righe:
        return totali
    headers = _headers()
    base = _items_url(conf)
    for row in righe:
        ticket = row.ticket
        try:
            if ticket.sharepoint_item_id:
                r = requests.patch(
                    f"{base}/{ticket.sharepoint_item_id}/fields",
                    headers=headers, json=campi_per_sharepoint(ticket, nuovo=False), timeout=20,
                )
                if r.status_code not in (200, 204):
                    raise RuntimeError(f"Graph {r.status_code}: {r.text[:300]}")
                totali["aggiornati"] += 1
            else:
                r = requests.post(
                    base, headers=headers, json={"fields": campi_per_sharepoint(ticket, nuovo=True)}, timeout=20,
                )
                if r.status_code not in (200, 201):
                    raise RuntimeError(f"Graph {r.status_code}: {r.text[:300]}")
                sp_id = str((r.json() or {}).get("id") or "")
                if sp_id:
                    Ticket.objects.filter(pk=ticket.pk).update(sharepoint_item_id=sp_id)
                totali["creati"] += 1
            # Se nel frattempo il ticket e' stato rimesso in coda la riga resta.
            TicketSharePointOutbox.objects.filter(pk=row.pk, queued_at=row.queued_at).delete()
        except Exception as exc:
            totali["falliti"] += 1
            TicketSharePointOutbox.objects.filter(pk=row.pk).update(
                tentativi=row.tentativi + 1, ultimo_errore=str(exc)[:2000],
            )
            logger.warning("Ticket %s: invio a SharePoint fallito: %s", ticket.pk, exc)
    return totali


# ─── SharePoint -> portale ───────────────────────────────────────────────────

def _testo(fields: dict, col: str) -> str:
    raw = fields.get(col)
    if raw is None:
        return ""
    return str(raw).strip()


def _data(fields: dict, col: str):
    raw = fields.get(col)
    if not raw:
        return None
    dt = parse_datetime(str(raw))
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _stato_da_sharepoint(fields: dict, attuale: Ticket | None) -> str:
    """Stato portale dall'elemento SharePoint.

    Sulla lista la chiusura passa da «Chiuso» / «Data chiusura ticket», mentre
    «Stato» resta quasi sempre «Nuovo» (il valore predefinito). Per un ticket
    aperto sul portale quindi «Nuovo», o lo stesso stato che il portale ha gia'
    inviato, non cambiano niente: altrimenti ogni modifica fatta su SharePoint
    riporterebbe ad «Aperta» un ticket in carico.
    """
    raw = _testo(fields, COL_STATO)
    stato_sp = STATO_DA_SP.get(raw.lower())
    chiuso = bool(fields.get(COL_CHIUSO)) or _data(fields, COL_DATA_CHIUSURA) is not None
    if chiuso:
        return StatoTicket.ANNULLATO if stato_sp == StatoTicket.ANNULLATO else StatoTicket.CHIUSO
    candidato = stato_sp or StatoTicket.APERTA
    if attuale is not None and attuale.stato not in STATI_CHIUSI_SP and candidato != StatoTicket.ANNULLATO:
        if candidato == StatoTicket.APERTA or STATO_A_SP.get(attuale.stato) == raw:
            return attuale.stato
    return candidato


def valori_da_sharepoint(fields: dict, attuale: Ticket | None = None) -> dict:
    """Valori del ticket portale corrispondenti all'elemento SharePoint."""
    valori: dict = {
        "titolo": _testo(fields, COL_TITOLO)[:300] or "(senza titolo)",
        "descrizione": _testo(fields, COL_DESCRIZIONE),
        "note_interne": _testo(fields, COL_NOTE),
        "incide_sicurezza": bool(fields.get(COL_SICUREZZA)),
    }
    priorita = PRIORITA_DA_SP.get(_testo(fields, COL_PRIORITA).lower())
    if priorita:
        valori["priorita"] = priorita
    if valori["incide_sicurezza"]:
        valori["priorita"] = PrioritaTicket.URGENTE

    macchinario = _testo(fields, COL_MACCHINARIO)
    if macchinario or attuale is None:
        valori["asset_descrizione_libera"] = macchinario[:300]

    # Categoria: si cambia solo se la tipologia non corrisponde gia' a quella
    # attuale (CNC e MACCHINARIO sono entrambe «Manutenzione macchinario»).
    tipologia = _testo(fields, COL_TIPOLOGIA)
    if tipologia and (attuale is None or _tipologia_per_categoria(attuale.categoria).lower() != tipologia.lower()):
        valori["categoria"] = CATEGORIA_DA_TIPOLOGIA.get(tipologia.lower(), "ALTRO_MAN")
    elif attuale is None:
        valori["categoria"] = "ALTRO_MAN"

    valori["stato"] = _stato_da_sharepoint(fields, attuale)
    stato = valori["stato"]
    data_chiusura = _data(fields, COL_DATA_CHIUSURA) or _data(fields, COL_DATA_FINE_LAVORI)

    if stato in STATI_CHIUSI_SP or stato == StatoTicket.RISOLTO:
        valori["closed_at"] = data_chiusura or (attuale.closed_at if attuale and attuale.closed_at else timezone.now())
    else:
        valori["closed_at"] = None
    return valori


def _al_secondo(value):
    # SharePoint salva le date al secondo: i microsecondi locali non sono una modifica.
    return value.replace(microsecond=0) if hasattr(value, "microsecond") else value


def _differenze(ticket: Ticket, valori: dict) -> dict:
    return {k: v for k, v in valori.items() if _al_secondo(getattr(ticket, k)) != _al_secondo(v)}


def _autore(item: dict) -> tuple[str, str]:
    user = ((item.get("createdBy") or {}).get("user") or {})
    return (str(user.get("displayName") or AUTORE_SYNC)[:200], str(user.get("email") or "")[:200])


def _collega_asset(ticket_id: int, descrizione: str, cache_asset: dict) -> None:
    if not descrizione:
        return
    if "elenco" not in cache_asset:
        try:
            from assets.models import Asset

            cache_asset["elenco"] = list(Asset.objects.only("id", "name"))
        except Exception:
            cache_asset["elenco"] = []
    from .views import _resolve_asset_by_name

    asset = _resolve_asset_by_name(descrizione, cache_asset["elenco"])
    if asset:
        Ticket.objects.filter(pk=ticket_id, asset__isnull=True).update(asset=asset)


def _registra_cambio_stato(ticket: Ticket, da: str, a: str) -> None:
    labels = dict(StatoTicket.choices)
    TicketStatoLog.objects.create(
        ticket=ticket, da_stato=da, a_stato=a, utente_nome=AUTORE_SYNC, nota="Modifica fatta su SharePoint",
    )
    TicketCommento.objects.create(
        ticket=ticket, autore_nome=AUTORE_SYNC, is_interno=True,
        testo=f"Stato aggiornato da SharePoint: {labels.get(da, da)} → {labels.get(a, a)}",
    )


def _applica(item: dict, cache_asset: dict, *, completa: bool = False) -> str:
    from .views import _silenzia_automazioni_import

    sp_id = str(item.get("id") or "")
    fields = item.get("fields") or {}
    ticket = Ticket.objects.filter(tipo=TipoTicket.MAN, sharepoint_item_id=sp_id).first()

    if item.get("deleted"):
        if ticket is None:
            return "ignorati"
        Ticket.objects.filter(pk=ticket.pk).update(sharepoint_item_id="")
        TicketCommento.objects.create(
            ticket=ticket, autore_nome=AUTORE_SYNC, is_interno=True,
            testo="Elemento eliminato su SharePoint: il ticket resta sul portale, scollegato dalla lista.",
        )
        _silenzia_automazioni_import([ticket.pk])
        return "scollegati"

    if ticket is None:
        nome, email = _autore(item)
        valori = valori_da_sharepoint(fields)
        closed_at = valori.pop("closed_at")
        assegnato = _testo(fields, COL_ASSEGNATO)[:200]
        ticket = Ticket(
            tipo=TipoTicket.MAN, sharepoint_item_id=sp_id[:100],
            richiedente_nome=nome, richiedente_email=email, assegnato_a=assegnato, **valori,
        )
        ticket.save()
        aggiornamenti = {"closed_at": closed_at}
        creato = _data(fields, COL_DATA_SEGNALAZIONE) or _data(fields, "Created")
        if creato:
            aggiornamenti["created_at"] = creato
        if valori["stato"] == StatoTicket.IN_CARICO:
            aggiornamenti["data_presa_in_carico"] = timezone.now()
        Ticket.objects.filter(pk=ticket.pk).update(**aggiornamenti)
        _collega_asset(ticket.pk, valori.get("asset_descrizione_libera", ""), cache_asset)
        _silenzia_automazioni_import([ticket.pk])
        return "creati"

    if completa:
        # Lettura completa (primo giro o token delta scaduto): i ticket gia' collegati
        # non si toccano, perche' portale e lista hanno vissuto separati fino a qui.
        # Da questo punto passano solo le modifiche vere.
        return "invariati"
    if TicketSharePointOutbox.objects.filter(ticket_id=ticket.pk).exists():
        return "saltati_in_coda"

    diff = _differenze(ticket, valori_da_sharepoint(fields, ticket))
    if not diff:
        return "invariati"
    if "stato" in diff:
        _registra_cambio_stato(ticket, ticket.stato, diff["stato"])
        if diff["stato"] == StatoTicket.IN_CARICO and not ticket.data_presa_in_carico:
            diff["data_presa_in_carico"] = timezone.now()
    diff["updated_at"] = timezone.now()
    Ticket.objects.filter(pk=ticket.pk).update(**diff)
    if "asset_descrizione_libera" in diff and not ticket.asset_id:
        _collega_asset(ticket.pk, diff["asset_descrizione_libera"], cache_asset)
    _silenzia_automazioni_import([ticket.pk])
    return "aggiornati"


def _delta(conf: dict, delta_link: str | None, headers: dict) -> tuple[list[dict], str, bool]:
    """Elementi cambiati dopo ``delta_link``; il terzo valore dice se e' una lettura completa."""
    url = delta_link or f"{_items_url(conf)}/delta?$expand=fields"
    items: list[dict] = []
    nuovo = ""
    while url:
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code == 410 and delta_link:
            logger.warning("ticket MAN: token delta scaduto, rilettura completa")
            return _delta(conf, None, headers)
        if r.status_code != 200:
            raise RuntimeError(f"Graph delta {r.status_code}: {r.text[:300]}")
        payload = r.json()
        items.extend(payload.get("value") or [])
        nuovo = payload.get("@odata.deltaLink") or nuovo
        url = payload.get("@odata.nextLink")
    return items, nuovo, not delta_link


def leggi_modifiche() -> dict:
    conf = configurazione()
    if conf is None:
        return {"skipped": "sincronizzazione spenta"}
    headers = _headers()
    delta_link = cache.get(_delta_key(conf)) or None
    items, nuovo_link, completa = _delta(conf, delta_link, headers)

    # Lo stesso elemento puo' comparire piu' volte nel feed: vale l'ultima occorrenza.
    ultimi: dict[str, dict] = {}
    for item in items:
        sp_id = str(item.get("id") or "").strip()
        if sp_id:
            ultimi[sp_id] = item

    totali = {"creati": 0, "aggiornati": 0, "invariati": 0, "saltati_in_coda": 0,
              "scollegati": 0, "ignorati": 0, "falliti": 0}
    cache_asset: dict = {}
    _locale.in_lettura = True
    try:
        for sp_id, item in ultimi.items():
            try:
                if not item.get("deleted") and not item.get("fields"):
                    r = requests.get(f"{_items_url(conf)}/{sp_id}?$expand=fields", headers=headers, timeout=20)
                    if r.status_code != 200:
                        continue
                    item = r.json()
                with transaction.atomic():
                    esito = _applica(item, cache_asset, completa=completa)
                totali[esito] += 1
            except Exception:
                totali["falliti"] += 1
                logger.exception("ticket MAN: elemento SharePoint %s non applicato", sp_id)
    finally:
        _locale.in_lettura = False

    # Con errori il token non avanza: il giro dopo rilegge le stesse modifiche.
    if nuovo_link and totali["falliti"] == 0:
        cache.set(_delta_key(conf), nuovo_link, timeout=None)
    return {"completa": completa, **totali}


def invia_subito() -> dict:
    """Solo la coda, senza lettura: chiamato subito dopo un salvataggio."""
    if configurazione() is None:
        return {"skipped": "sincronizzazione spenta"}
    if not cache.add(_LOCK_KEY, "1", timeout=_LOCK_TTL):
        return {"skipped": "sincronizzazione gia' in corso"}
    try:
        return invia_coda()
    finally:
        cache.delete(_LOCK_KEY)


def sincronizza() -> dict:
    """Giro completo: prima la coda verso SharePoint, poi le modifiche da SharePoint."""
    if configurazione() is None:
        return {"skipped": "sincronizzazione spenta"}
    if not cache.add(_LOCK_KEY, "1", timeout=_LOCK_TTL):
        return {"skipped": "sincronizzazione gia' in corso"}
    try:
        return {"invio": invia_coda(), "lettura": leggi_modifiche()}
    finally:
        cache.delete(_LOCK_KEY)


def stato_sincronizzazione() -> dict:
    """Per la pagina Impostazioni: righe in coda e ultimo errore."""
    righe = TicketSharePointOutbox.objects.all()
    errore = righe.exclude(ultimo_errore="").order_by("-queued_at").values_list("ultimo_errore", flat=True).first()
    return {"in_coda": righe.count(), "ultimo_errore": errore or ""}
