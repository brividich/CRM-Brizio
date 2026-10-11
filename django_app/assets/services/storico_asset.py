"""Servizio unico dello storico di stato, assegnazione e rete degli asset (PROMPT 06 - C).

Ogni via che modifica questi campi (form, modifica in blocco, import, admin, API di
altri moduli, job) passa da qui con lo stesso schema:

    with storico_asset.traccia([asset.pk], fonte=FONTE_FORM, utente=request.user) as t:
        ...scritture esistenti (save, update, endpoint)...
        t.aggiungi(nuovo_asset.pk)      # per gli asset creati dentro il blocco

Il blocco apre una transazione: fotografa i campi prima, lascia lavorare il codice
esistente (anche ``queryset.update()``, che salta ``save()`` e i segnali) e alla
fine scrive una riga per ogni campo davvero cambiato. Se il codice solleva, rollback
di modifica e storico insieme. Nessun segnale sparso.

Query: 2 per fotografia (asset + endpoint), a blocchi di ``CHUNK`` id per stare
sotto il limite di 2.100 parametri di SQL Server.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

CHUNK = 1000

#: Campi dell'asset tracciati, con etichetta per la timeline.
CAMPI_ASSET = {
    "status": "Stato",
    "reparto": "Reparto",
    "assigned_legacy_user_id": "Assegnatario (utente)",
    "assignment_to": "Assegnato a",
    "assignment_reparto": "Reparto assegnazione",
    "assignment_location": "Ubicazione",
}
#: Campi del punto rete (AssetEndpoint); il nome del campo storico e' ``endpoint.<campo>``.
CAMPI_ENDPOINT = {
    "endpoint_name": "Nome punto rete",
    "ip": "IP",
    "vlan": "VLAN",
    "switch_name": "Switch",
    "switch_port": "Porta switch",
    "punto": "Porta patch panel",
}
CAMPO_ENDPOINT_PRESENZA = "endpoint"
ETICHETTE = {
    **CAMPI_ASSET,
    **{f"endpoint.{k}": v for k, v in CAMPI_ENDPOINT.items()},
    CAMPO_ENDPOINT_PRESENZA: "Punto rete",
}
GRUPPI = {
    "stato": ["status"],
    "assegnazione": ["reparto", "assigned_legacy_user_id", "assignment_to", "assignment_reparto", "assignment_location"],
    "rete": [CAMPO_ENDPOINT_PRESENZA] + [f"endpoint.{k}" for k in CAMPI_ENDPOINT],
}


def _testo(value) -> str:
    return "" if value is None else str(value).strip()


def _chunks(ids):
    ids = list(ids)
    for i in range(0, len(ids), CHUNK):
        yield ids[i:i + CHUNK]


def fotografia(asset_ids) -> dict[int, dict]:
    """``{asset_id: {"campi": {...}, "endpoint": {endpoint_id: {...}}}}`` dei campi tracciati."""
    from ..models import Asset, AssetEndpoint

    ids = sorted({int(pk) for pk in asset_ids if pk})
    out: dict[int, dict] = {}
    for chunk in _chunks(ids):
        for row in Asset.objects.filter(pk__in=chunk).values("id", *CAMPI_ASSET):
            out[row.pop("id")] = {"campi": {k: _testo(v) for k, v in row.items()}, "endpoint": {}}
        for row in AssetEndpoint.objects.filter(asset_id__in=chunk).values("id", "asset_id", *CAMPI_ENDPOINT):
            asset_id, endpoint_id = row.pop("asset_id"), row.pop("id")
            if asset_id in out:
                out[asset_id]["endpoint"][endpoint_id] = {k: _testo(v) for k, v in row.items()}
    return out


def _etichetta_endpoint(valori: dict) -> str:
    return " · ".join(x for x in (valori.get("endpoint_name"), valori.get("ip"),
                                   f"VLAN {valori['vlan']}" if valori.get("vlan") else "") if x)[:255]


def _autore(utente):
    if utente is None or not getattr(utente, "is_authenticated", False):
        return None, ""
    nome = (utente.get_full_name() or utente.get_username() or "").strip()
    return utente, nome[:200]


def differenze(prima: dict, dopo: dict, *, fonte: str, utente=None, dettaglio: str = "", quando=None) -> list:
    """Righe ``AssetFieldHistory`` (non salvate) per i soli campi cambiati."""
    from ..models import AssetFieldHistory

    quando = quando or timezone.now()
    autore, autore_display = _autore(utente)
    dettaglio = (dettaglio or "")[:255]
    righe = []

    def riga(asset_id, campo, vecchio, nuovo, endpoint_id=None, endpoint_label=""):
        righe.append(AssetFieldHistory(
            asset_id=asset_id, campo=campo, valore_prima=vecchio, valore_dopo=nuovo,
            endpoint_id=endpoint_id, endpoint_label=endpoint_label, fonte=fonte,
            autore=autore, autore_display=autore_display, dettaglio=dettaglio, cambiato_il=quando,
        ))

    for asset_id, stato_dopo in dopo.items():
        stato_prima = prima.get(asset_id, {"campi": {}, "endpoint": {}})
        for campo in CAMPI_ASSET:
            vecchio, nuovo = stato_prima["campi"].get(campo, ""), stato_dopo["campi"].get(campo, "")
            if vecchio != nuovo:
                riga(asset_id, campo, vecchio, nuovo)
        ep_prima, ep_dopo = stato_prima["endpoint"], stato_dopo["endpoint"]
        for endpoint_id, valori in ep_dopo.items():
            label = _etichetta_endpoint(valori)
            vecchi = ep_prima.get(endpoint_id)
            if vecchi is None:
                riga(asset_id, CAMPO_ENDPOINT_PRESENZA, "", "aggiunto", endpoint_id, label)
                vecchi = {}
            for campo in CAMPI_ENDPOINT:
                if vecchi.get(campo, "") != valori.get(campo, ""):
                    riga(asset_id, f"endpoint.{campo}", vecchi.get(campo, ""), valori.get(campo, ""), endpoint_id, label)
        for endpoint_id, valori in ep_prima.items():
            if endpoint_id not in ep_dopo:
                riga(asset_id, CAMPO_ENDPOINT_PRESENZA, "presente", "eliminato", endpoint_id, _etichetta_endpoint(valori))
    return righe


class _Traccia:
    def __init__(self, ids):
        self.ids = {int(pk) for pk in ids if pk}

    def aggiungi(self, *asset_ids):
        self.ids.update(int(pk) for pk in asset_ids if pk)


@contextmanager
def traccia(asset_ids=(), *, fonte: str, utente=None, dettaglio: str = ""):
    """Blocco transazionale che registra lo storico delle modifiche fatte al suo interno."""
    from ..models import AssetFieldHistory

    tracker = _Traccia(asset_ids)
    with transaction.atomic():
        prima = fotografia(tracker.ids)
        yield tracker
        dopo = fotografia(tracker.ids)
        righe = differenze(prima, dopo, fonte=fonte, utente=utente, dettaglio=dettaglio)
        if righe:
            AssetFieldHistory.objects.bulk_create(righe, batch_size=200)


def registra_eliminazione_endpoint(endpoint, *, fonte: str, utente=None, dettaglio: str = ""):
    """Per chi elimina un punto rete fuori da un blocco ``traccia``."""
    with traccia([endpoint.asset_id], fonte=fonte, utente=utente, dettaglio=dettaglio):
        endpoint.delete()


# ── Lettura ──────────────────────────────────────────────────────────────────


def inizio_giorno(giorno):
    from datetime import datetime, time

    return timezone.make_aware(datetime.combine(giorno, time.min))


def _visualizza(campo: str, valore: str) -> str:
    if campo == "status" and valore:
        from ..models import Asset

        return dict(Asset.STATUS_CHOICES).get(valore, valore)
    return valore


def timeline(asset, *, gruppo: str = "", campo: str = "", dal=None, al=None, limite: int = 200) -> list[dict]:
    """Voci "cosa e' cambiato" per la scheda, piu' recenti prima, con filtri."""
    qs = asset.field_history.all()
    if gruppo in GRUPPI:
        qs = qs.filter(campo__in=GRUPPI[gruppo])
    if campo:
        qs = qs.filter(campo=campo)
    # Intervalli su datetime locali (usano l'indice; __date su SQL Server no).
    if dal:
        qs = qs.filter(cambiato_il__gte=inizio_giorno(dal))
    if al:
        qs = qs.filter(cambiato_il__lt=inizio_giorno(al + timedelta(days=1)))
    out = []
    for r in qs.order_by("-cambiato_il", "-id")[:limite]:
        out.append({
            "quando": r.cambiato_il, "campo": r.campo, "etichetta": ETICHETTE.get(r.campo, r.campo),
            "prima": _visualizza(r.campo, r.valore_prima), "dopo": _visualizza(r.campo, r.valore_dopo),
            "fonte": r.get_fonte_display(), "fonte_code": r.fonte, "autore": r.autore_display,
            "endpoint": r.endpoint_label, "dettaglio": r.dettaglio,
        })
    return out


def stato_alla_data(asset, quando) -> dict:
    """Com'era l'asset alla data/ora ``quando``: ultimo valore registrato per campo.

    Prima del primo punto di storico (baseline) il valore non e' noto: ``None``.
    """
    campi = {}
    endpoint: dict[int, dict] = {}
    righe = asset.field_history.filter(cambiato_il__lte=quando).order_by("cambiato_il", "id").values(
        "campo", "valore_dopo", "endpoint_id", "endpoint_label")
    for r in righe:
        if r["endpoint_id"] is None:
            campi[r["campo"]] = r["valore_dopo"]
            continue
        ep = endpoint.setdefault(r["endpoint_id"], {"label": r["endpoint_label"], "campi": {}, "attivo": True})
        ep["label"] = r["endpoint_label"] or ep["label"]
        if r["campo"] == CAMPO_ENDPOINT_PRESENZA:
            ep["attivo"] = r["valore_dopo"] != "eliminato"
        else:
            ep["campi"][r["campo"].split(".", 1)[1]] = r["valore_dopo"]
    return {
        "campi": [{"campo": k, "etichetta": v, "valore": _visualizza(k, campi[k]) if k in campi else None}
                  for k, v in CAMPI_ASSET.items()],
        "endpoint": [
            {"label": ep["label"], "campi": [{"etichetta": CAMPI_ENDPOINT[k], "valore": ep["campi"].get(k, "")}
                                             for k in CAMPI_ENDPOINT]}
            for ep in endpoint.values() if ep["attivo"]
        ],
        "tracciato": bool(campi or endpoint),
    }


# ── Retention ────────────────────────────────────────────────────────────────


def giorni_retention() -> int:
    """0 = conserva tutto (default)."""
    return int(getattr(settings, "ASSETS_STORICO_RETENTION_GIORNI", 0) or 0)


def applica_retention(ora=None) -> int:
    """Elimina le voci piu' vecchie della retention, MAI l'ultima di ogni campo (resta il "com'era")."""
    from django.db.models import Max

    from ..models import AssetFieldHistory

    giorni = giorni_retention()
    if giorni <= 0:
        return 0
    limite = (ora or timezone.now()) - timedelta(days=giorni)
    ultime = (AssetFieldHistory.objects.values("asset_id", "campo", "endpoint_id")
              .annotate(ultimo=Max("id")).order_by().values_list("ultimo", flat=True))
    eliminate, _ = AssetFieldHistory.objects.filter(cambiato_il__lt=limite).exclude(id__in=ultime).delete()
    return eliminate
