"""Authorized snapshots only: opening an asset must never poll a device."""
from decimal import Decimal

from django.db import DatabaseError
from django.db.models import OuterRef, Subquery
from django.urls import reverse

from core.middleware import acl_allows_path

LINK_LIMIT = 10
READING_LIMIT = 30
READING_STATE_LABELS = {"OK": "Regolare", "WARNING": "Attenzione", "ERROR": "Critico o non letto"}
STATE_LABELS = {"OK": "Risposta ricevuta", "WARNING": "Con avvisi", "ERROR": "Errore", "MAI": "Mai interrogato"}


def can_view_monitoring(request, path):
    if not getattr(request.user, "is_authenticated", False):
        return False
    try:
        return acl_allows_path(path, django_user=request.user,
                               legacy_user=getattr(request, "legacy_user", None), request=request)
    except DatabaseError:
        return False


def _format_reading(number, unit):
    """Numero leggibile in italiano: migliaia con punto, al massimo 2 decimali, durate in g/h."""
    unit = (unit or "").strip()
    if unit == "s" and number >= 0:
        days, rest = divmod(int(number), 86400)
        hours, rest = divmod(rest, 3600)
        return f"{days} g {hours} h" if days else f"{hours} h {rest // 60} min"
    rounded = number.quantize(Decimal("1") if abs(number) >= 100 else Decimal("0.01")).normalize()
    integer, _, decimals = format(rounded, "f").partition(".")
    sign = "-" if integer.startswith("-") else ""
    text = sign + f"{int(integer.lstrip('-') or 0):,}".replace(",", ".")
    if decimals:
        text += "," + decimals
    return f"{text} {unit}".strip()


def _probe_readings(snapshot_ids):
    """Valori delle sonde dell'ultima rilevazione, senza i messaggi d'errore tecnici."""
    from contatori.models import ValoreSNMP, etichetta_valore

    out = {}
    rows = ValoreSNMP.objects.filter(rilevazione_id__in=snapshot_ids).order_by(
        "rilevazione_id", "sonda__ordine", "sonda__nome",
    ).values("rilevazione_id", "sonda__nome", "sonda__unita", "sonda__etichette",
             "valore_numero", "valore_testo", "stato")
    for row in rows:
        readings = out.setdefault(row["rilevazione_id"], [])
        if len(readings) >= READING_LIMIT:
            continue
        label = etichetta_valore(row["sonda__etichette"], row["valore_numero"])
        if label:
            value = label
        elif row["valore_numero"] is not None:
            value = _format_reading(row["valore_numero"], row["sonda__unita"])
        else:
            value = row["valore_testo"] or "Non disponibile"
        readings.append({
            "name": row["sonda__nome"], "value": value, "state": row["stato"],
            "state_label": READING_STATE_LABELS.get(row["stato"], "Esito non noto"),
        })
    return out


def monitoring_for_asset(request, asset):
    central_url = reverse("contatori:snmp_centrale")
    if not can_view_monitoring(request, central_url):
        return None
    from contatori.models import DispositivoSNMP, LetturaMensileContatori, Macchina, RilevazioneSNMP

    latest = RilevazioneSNMP.objects.filter(dispositivo_id=OuterRef("pk")).order_by("-rilevata_il", "-pk")
    devices = list(DispositivoSNMP.objects.filter(asset=asset).order_by("nome", "pk").annotate(
        snapshot_id=Subquery(latest.values("pk")[:1]),
    ).values("id", "nome", "host", "attivo", "snmp_stato", "snmp_ultimo_controllo", "snapshot_id")[:LINK_LIMIT])
    permitted = []
    for device in devices:
        device["url"] = reverse("contatori:snmp_dispositivo", args=[device["id"]])
        if can_view_monitoring(request, device["url"]):
            permitted.append(device)
    snapshot_ids = [row["snapshot_id"] for row in permitted if row["snapshot_id"]]
    snapshots = {row["id"]: row for row in RilevazioneSNMP.objects.filter(
        pk__in=snapshot_ids,
    ).values("id", "rilevata_il", "stato", "dati_stampante")}
    readings_by_snapshot = _probe_readings(snapshot_ids)
    for device in permitted:
        device["state_label"] = STATE_LABELS.get(device["snmp_stato"], "Esito non noto")
        snapshot = snapshots.get(device["snapshot_id"])
        if snapshot:
            snapshot["state_label"] = STATE_LABELS.get(snapshot["stato"], "Esito non noto")
        device["snapshot"] = snapshot
        device["readings"] = readings_by_snapshot.get(device["snapshot_id"], [])
        payload = snapshot.get("dati_stampante") if snapshot else {}
        payload = payload if isinstance(payload, dict) else {}
        counters = payload.get("contatori") or []
        supplies = payload.get("consumabili") or []
        device["counters"] = [row for row in counters[:20] if isinstance(row, dict)] if isinstance(counters, list) else []
        device["supplies"] = [row for row in supplies[:20] if isinstance(row, dict)] if isinstance(supplies, list) else []
        device["partial"] = bool(payload.get("errori"))
        # Explicit unknowns, including 0% vs None; never turn unknown into zero.
        for supply in device["supplies"]:
            pct = supply.get("pct")
            supply["display_pct"] = pct if type(pct) in (int, float) and 0 <= pct <= 100 else None

    last_reading = LetturaMensileContatori.objects.filter(macchina_id=OuterRef("pk")).order_by("-rilevata_il", "-pk")
    machines = list(Macchina.objects.filter(asset=asset).order_by("reparto", "pk").annotate(
        reading_id=Subquery(last_reading.values("pk")[:1]),
    ).values("id", "reparto", "matricola", "modello", "host", "contratto", "fornitore", "attiva", "snmp_stato", "snmp_ultimo_controllo", "reading_id")[:LINK_LIMIT])
    permitted_machines = []
    for machine in machines:
        machine["url"] = reverse("contatori:macchina", args=[machine["id"]])
        if can_view_monitoring(request, machine["url"]):
            supplies_url = reverse("contatori:macchina_consumabili", args=[machine["id"]])
            machine["supplies_url"] = supplies_url if machine["host"] and machine["attiva"] and can_view_monitoring(request, supplies_url) else ""
            permitted_machines.append(machine)
    readings = {row["id"]: row for row in LetturaMensileContatori.objects.filter(
        pk__in=[row["reading_id"] for row in permitted_machines if row["reading_id"]],
    ).values("id", "mese", "rilevata_il", "a4_bn", "a3_bn", "a4_col", "a3_col")}
    for machine in permitted_machines:
        machine["state_label"] = STATE_LABELS.get(machine["snmp_stato"], "Esito non noto")
        machine["reading"] = readings.get(machine["reading_id"])
    return {"devices": permitted, "machines": permitted_machines, "central_url": central_url}
