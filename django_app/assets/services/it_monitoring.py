"""Authorized snapshots only: opening an asset must never poll a device."""
from django.db import DatabaseError
from django.db.models import OuterRef, Subquery
from django.urls import reverse

from core.middleware import acl_allows_path

LINK_LIMIT = 10
STATE_LABELS = {"OK": "Risposta ricevuta", "WARNING": "Con avvisi", "ERROR": "Errore", "MAI": "Mai interrogato"}


def can_view_monitoring(request, path):
    if not getattr(request.user, "is_authenticated", False):
        return False
    try:
        return acl_allows_path(path, django_user=request.user,
                               legacy_user=getattr(request, "legacy_user", None), request=request)
    except DatabaseError:
        return False


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
    snapshots = {row["id"]: row for row in RilevazioneSNMP.objects.filter(
        pk__in=[row["snapshot_id"] for row in permitted if row["snapshot_id"]],
    ).values("id", "rilevata_il", "stato", "dati_stampante")}
    for device in permitted:
        device["state_label"] = STATE_LABELS.get(device["snmp_stato"], "Esito non noto")
        snapshot = snapshots.get(device["snapshot_id"])
        if snapshot:
            snapshot["state_label"] = STATE_LABELS.get(snapshot["stato"], "Esito non noto")
        device["snapshot"] = snapshot
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
    ).values("id", "reparto", "matricola", "attiva", "snmp_stato", "snmp_ultimo_controllo", "reading_id")[:LINK_LIMIT])
    permitted_machines = []
    for machine in machines:
        machine["url"] = reverse("contatori:macchina", args=[machine["id"]])
        if can_view_monitoring(request, machine["url"]):
            permitted_machines.append(machine)
    readings = {row["id"]: row for row in LetturaMensileContatori.objects.filter(
        pk__in=[row["reading_id"] for row in permitted_machines if row["reading_id"]],
    ).values("id", "mese", "rilevata_il", "a4_bn", "a3_bn", "a4_col", "a3_col")}
    for machine in permitted_machines:
        machine["state_label"] = STATE_LABELS.get(machine["snmp_stato"], "Esito non noto")
        machine["reading"] = readings.get(machine["reading_id"])
    return {"devices": permitted, "machines": permitted_machines, "central_url": central_url}
