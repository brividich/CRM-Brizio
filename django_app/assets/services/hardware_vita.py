"""Hardware a fine vita: età, garanzia, memoria, disco e guasti di PC, notebook e server, per decidere cosa sostituire.

Niente punteggio: un giudizio in tre livelli con i motivi scritti.

- **Da sostituire**: età da ``ETA_SOSTITUZIONE`` anni in su, oppure garanzia scaduta **e** almeno ``GUASTI_SOGLIA`` ticket
  negli ultimi 12 mesi, oppure RAM sotto ``RAM_MINIMA_GB`` su un PC.
- **Da pianificare**: età da ``ETA_PIANIFICA`` anni, garanzia scaduta o in scadenza entro 90 giorni, disco pieno oltre
  ``DISCO_PIENO_PCT``, almeno ``GUASTI_SOGLIA`` ticket in 12 mesi.
- **A posto**: nessuno dei motivi; **non valutabile** se non si sa né l'età né la garanzia né l'hardware.

L'età viene da «Data acquisto» (o «Data fabbricazione») dell'asset, la garanzia da «Fine garanzia», RAM e disco da Intune
(``DispositivoIntune``), i guasti dai ticket aperti sull'asset. Stessa funzione per la scheda «Hardware a fine vita» e per il
riquadro Rischio della scheda asset.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from assets.models import Asset, DispositivoIntune

ETA_SOSTITUZIONE = 6
ETA_PIANIFICA = 5
RAM_MINIMA_GB = 8
DISCO_PIENO_PCT = 90
GUASTI_SOGLIA = 3
GIORNI_GARANZIA_PREAVVISO = 90
TIPI = (Asset.TYPE_PC, Asset.TYPE_NOTEBOOK, Asset.TYPE_SERVER)
SOSTITUIRE, PIANIFICARE, OK, NON_VALUTABILE = "sostituire", "pianificare", "ok", "non_valutabile"
ETICHETTE = {SOSTITUIRE: "Da sostituire", PIANIFICARE: "Da pianificare", OK: "A posto", NON_VALUTABILE: "Non valutabile"}
ORDINE = {SOSTITUIRE: 0, PIANIFICARE: 1, NON_VALUTABILE: 2, OK: 3}


def _guasti(asset_ids, oggi):
    from tickets.models import StatoTicket, Ticket

    da = timezone.make_aware(timezone.datetime.combine(oggi - timedelta(days=365), timezone.datetime.min.time()))
    out = {}
    for asset_id in (Ticket.objects.filter(asset_id__in=asset_ids, created_at__gte=da).exclude(stato=StatoTicket.ANNULLATO)
                     .values_list("asset_id", flat=True)):
        out[asset_id] = out.get(asset_id, 0) + 1
    return out


def _intune(asset_ids):
    out = {}
    for d in DispositivoIntune.objects.filter(asset_id__in=asset_ids, presente=True).order_by("-ultima_sync"):
        out.setdefault(d.asset_id, d)
    return out


def valuta(asset, oggi=None, *, guasti=None, intune=None) -> dict:
    """Giudizio e motivi di un asset. ``guasti`` e ``intune`` si passano dall'elenco per non rifare le query."""
    oggi = oggi or timezone.localdate()
    if guasti is None:
        guasti = _guasti([asset.pk], oggi).get(asset.pk, 0)
    if intune is None:
        intune = _intune([asset.pk]).get(asset.pk)
    data = asset.purchase_date or asset.production_date
    eta = round((oggi - data).days / 365.25, 1) if data else None
    garanzia = asset.warranty_end
    garanzia_stato = None
    if garanzia:
        garanzia_stato = "scaduta" if garanzia < oggi else ("in_scadenza" if garanzia <= oggi + timedelta(days=GIORNI_GARANZIA_PREAVVISO) else "ok")
    ram_gb = round(intune.ram_bytes / 1024 ** 3, 1) if intune and intune.ram_bytes else None
    disco_pct = intune.disco_usato_pct if intune else None
    sostituire, pianificare = [], []
    if eta is not None and eta >= ETA_SOSTITUZIONE:
        sostituire.append(f"{eta:g} anni (acquistato il {data:%d/%m/%Y})".replace(".", ","))
    elif eta is not None and eta >= ETA_PIANIFICA:
        pianificare.append(f"{eta:g} anni (acquistato il {data:%d/%m/%Y})".replace(".", ","))
    if garanzia_stato == "scaduta":
        (sostituire if guasti >= GUASTI_SOGLIA else pianificare).append(f"garanzia scaduta il {garanzia:%d/%m/%Y}")
    elif garanzia_stato == "in_scadenza":
        pianificare.append(f"garanzia fino al {garanzia:%d/%m/%Y}")
    if ram_gb is not None and ram_gb < RAM_MINIMA_GB and asset.asset_type != Asset.TYPE_SERVER:
        sostituire.append(f"{ram_gb:g} GB di RAM".replace(".", ","))
    if disco_pct is not None and disco_pct >= DISCO_PIENO_PCT:
        pianificare.append(f"disco pieno al {disco_pct}%")
    if guasti >= GUASTI_SOGLIA:
        pianificare.append(f"{guasti} ticket negli ultimi 12 mesi")
    if sostituire:
        giudizio = SOSTITUIRE
    elif pianificare:
        giudizio = PIANIFICARE
    elif eta is None and garanzia is None and intune is None:
        giudizio = NON_VALUTABILE
    else:
        giudizio = OK
    return {
        "giudizio": giudizio, "etichetta": ETICHETTE[giudizio], "motivi": sostituire + pianificare,
        "eta": eta, "data": data, "garanzia": garanzia, "garanzia_stato": garanzia_stato, "ram_gb": ram_gb,
        "disco_pct": disco_pct, "guasti": guasti, "intune": intune,
    }


def elenco(oggi=None) -> list[dict]:
    """Tutti i PC, notebook e server non dismessi con il loro giudizio, i peggiori prima."""
    oggi = oggi or timezone.localdate()
    assets = list(Asset.objects.filter(asset_type__in=TIPI).exclude(status=Asset.STATUS_RETIRED).order_by("name"))
    ids = [a.pk for a in assets]
    guasti, intune = _guasti(ids, oggi), _intune(ids)
    righe = [{"asset": a, **valuta(a, oggi, guasti=guasti.get(a.pk, 0), intune=intune.get(a.pk))} for a in assets]
    righe.sort(key=lambda r: (ORDINE[r["giudizio"]], -(r["eta"] or 0), r["asset"].name.casefold()))
    return righe


ETA_SCALA = 8  # anni: la barra dell'età è piena a questa età, con i segni alle soglie


def filtra(righe, giudizio):
    """Le righe con quel giudizio (``sostituire``, ``pianificare``, ``non_valutabile``, ``ok``); tutte se non è un giudizio."""
    if giudizio not in ETICHETTE:
        return righe
    return [r for r in righe if r["giudizio"] == giudizio]


def eta_percento(eta) -> int | None:
    """Larghezza della barra dell'età in percentuale della scala (``ETA_SCALA`` anni), tra 2 e 100."""
    if eta is None:
        return None
    return max(2, min(100, round(100 * eta / ETA_SCALA)))


def conteggi(righe) -> dict:
    out = {k: 0 for k in ETICHETTE}
    for r in righe:
        out[r["giudizio"]] += 1
    return out
