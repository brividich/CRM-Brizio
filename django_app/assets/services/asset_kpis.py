"""Cruscotto della scheda asset: i numeri che contano per QUEL tipo di dispositivo.

- Stampante / MFC: stato SNMP, pagine stampate (ultimo mese e totali), quota
  colore, toner piu' basso.
- Firewall / rete: stato SNMP e uptime, le prime sonde numeriche lette, alert
  SOC aperti ed eventi degli ultimi 7 giorni.
- PC / server / VM: ultimo backup, antivirus/EDR (rilevamenti 30 giorni),
  alert e vulnerabilita' aperte, stato SNMP se monitorato.

Solo dati gia' raccolti (nessuna interrogazione all'apertura) e solo dai moduli
che l'utente puo' vedere. Ogni riquadro ha un livello: ok / warn / bad / none.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from assets.services.it_coverage import SILENT_AFTER, can_view_snmp, can_view_soc

LOW_TONER_PCT = 15
PROBE_TILES = 3


TAB_MONITORING = "#tab-monitoraggio"
TAB_SECURITY = "#tab-sicurezza"


SPARK_POINTS = 12
BACKUP_BARS = 14


def _tile(label, value, sub="", level="none", href=""):
    return {"label": label, "value": value, "sub": sub, "level": level, "href": href}


def _spark(values, hint="") -> dict | None:
    """Mini-andamento (polyline SVG 100x24) dai valori piu' vecchi ai piu' recenti."""
    values = [float(v) for v in values if v is not None][-SPARK_POINTS:]
    if len(values) < 2:
        return None
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = 100 / (len(values) - 1)
    points = " ".join(f"{i * step:.1f},{22 - (v - low) / span * 20:.1f}" for i, v in enumerate(values))
    return {"points": points, "hint": hint}


def _fmt_int(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def _fmt_uptime(seconds) -> str:
    days, rest = divmod(int(seconds), 86400)
    return f"{days} g {rest // 3600} h" if days else f"{rest // 3600} h {(rest % 3600) // 60} min"


def _when(dt) -> str:
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M") if dt else ""


def _snmp_state_tile(objs, now):
    """Stato del monitoraggio: il peggiore fra i dispositivi collegati."""
    worst, worst_rank = None, -1
    for obj in objs:
        last = obj.snmp_ultimo_controllo
        if obj.snmp_stato == "ERROR":
            rank, value, level = 3, "Non risponde", "bad"
        elif last is None:
            rank, value, level = 2, "Mai letto", "warn"
        elif now - last > SILENT_AFTER:
            rank, value, level = 2, f"Muto da {(now - last).days} gg", "warn"
        elif obj.snmp_stato == "WARNING":
            rank, value, level = 1, "Con avvisi", "warn"
        else:
            rank, value, level = 0, "Raggiungibile", "ok"
        if rank > worst_rank:
            worst_rank, worst = rank, _tile("Monitoraggio SNMP", value, f"Ultimo contatto {_when(last)}" if last else "Nessun contatto registrato", level, TAB_MONITORING)
    return worst


def profile_for(asset, it_presentation=None) -> str:
    """Profilo del cruscotto: dal profilo IT o dai collegamenti di monitoraggio."""
    profile = (it_presentation or {}).get("profile") if isinstance(it_presentation, dict) else None
    if profile:
        return profile
    if asset.asset_type in ("FIREWALL",):
        return "network"
    try:
        if asset.contatori_macchine.exists():
            return "printer"
        categories = set(asset.dispositivi_snmp.values_list("categoria", flat=True))
    except DatabaseError:
        return ""
    if categories & {"FIREWALL", "RETE"}:
        return "network"
    if categories & {"STAMPANTE"}:
        return "printer"
    if categories & {"SERVER", "STORAGE"}:
        return "server"
    return "generic" if categories else ""


def _printer_tiles(asset, now):
    from contatori.models import DispositivoSNMP, LetturaConsumabile, LetturaMensileContatori, Macchina, RilevazioneSNMP

    tiles = []
    machines = list(Macchina.objects.filter(asset=asset))
    devices = list(DispositivoSNMP.objects.filter(asset=asset))
    state = _snmp_state_tile(machines + devices, now)
    if state:
        tiles.append(state)
    readings = list(LetturaMensileContatori.objects.filter(macchina__in=machines).order_by("macchina_id", "-mese")[:24])
    by_machine = {}
    for reading in readings:
        by_machine.setdefault(reading.macchina_id, []).append(reading)
    if by_machine:
        total = sum(rows[0].totale for rows in by_machine.values())
        colour = sum(rows[0].a4_col + rows[0].a3_col for rows in by_machine.values())
        month = [rows[0].totale - rows[1].totale for rows in by_machine.values() if len(rows) > 1]
        last_month = max(rows[0].mese for rows in by_machine.values())
        if month:
            tile = _tile("Pagine ultimo mese", _fmt_int(sum(month)), f"Lettura di {last_month:%m/%Y}", "none", TAB_MONITORING)
            per_month = {}
            for rows in by_machine.values():
                for newer, older in zip(rows, rows[1:]):
                    per_month[newer.mese] = per_month.get(newer.mese, 0) + max(newer.totale - older.totale, 0)
            tile["spark"] = _spark([per_month[key] for key in sorted(per_month)], "Pagine al mese")
            tiles.append(tile)
        tiles.append(_tile("Pagine totali", _fmt_int(total), "Contatore cumulativo", "none", TAB_MONITORING))
        if total:
            tiles.append(_tile("Quota colore", f"{round(100 * colour / total)}%", "Sul totale stampato", "none"))
    # Toner: ultimo livello per consumabile (MFC) o dall'ultima rilevazione SNMP (dispositivi).
    levels = []
    seen = set()
    for row in LetturaConsumabile.objects.filter(macchina__in=machines).order_by("-rilevata_il")[:60]:
        key = (row.macchina_id, row.nome)
        if key in seen:
            continue
        seen.add(key)
        if row.pct is not None:
            levels.append((row.pct, row.nome))
    for device in devices:
        snap = RilevazioneSNMP.objects.filter(dispositivo=device).order_by("-rilevata_il", "-pk").values("dati_stampante").first()
        payload = (snap or {}).get("dati_stampante") or {}
        for supply in (payload.get("consumabili") or []) if isinstance(payload, dict) else []:
            pct = supply.get("pct") if isinstance(supply, dict) else None
            if type(pct) in (int, float) and 0 <= pct <= 100:
                levels.append((pct, str(supply.get("nome") or "Consumabile")))
    if levels:
        pct, name = min(levels)
        tiles.append(_tile("Consumabile più basso", f"{int(pct)}%", name[:40], "bad" if pct <= LOW_TONER_PCT else "ok", TAB_MONITORING))
    return tiles


def _probe_tiles(asset):
    from contatori.models import DispositivoSNMP, RilevazioneSNMP, ValoreSNMP, etichetta_valore

    from assets.services.it_monitoring import _format_reading

    tiles = []
    for device in DispositivoSNMP.objects.filter(asset=asset, attivo=True)[:2]:
        if device.sys_uptime_seconds:
            tiles.append(_tile("Uptime", _fmt_uptime(device.sys_uptime_seconds), device.nome, "none", TAB_MONITORING))
        snap = RilevazioneSNMP.objects.filter(dispositivo=device).order_by("-rilevata_il", "-pk").first()
        if snap is None:
            continue
        values = (ValoreSNMP.objects.filter(rilevazione=snap, valore_numero__isnull=False)
                  .select_related("sonda").order_by("sonda__ordine", "sonda__nome")[:PROBE_TILES])
        for value in values:
            label = etichetta_valore(value.sonda.etichette, value.valore_numero)
            shown = label or _format_reading(value.valore_numero, value.sonda.unita)
            level = {"OK": "ok", "WARNING": "warn", "ERROR": "bad"}.get(value.stato, "none")
            tile = _tile(value.sonda.nome[:40], shown, f"Letto {_when(snap.rilevata_il)}", level, TAB_MONITORING)
            history = list(ValoreSNMP.objects.filter(sonda=value.sonda, valore_numero__isnull=False)
                           .order_by("-rilevazione__rilevata_il").values_list("valore_numero", flat=True)[:SPARK_POINTS])
            tile["spark"] = _spark(list(reversed(history)), "Ultime rilevazioni")
            tiles.append(tile)
    return tiles


def _soc_tiles(asset, profile, now):
    from security.models import SecurityAlert, SecurityAssetSignal, SecurityEventRecord, SecurityVulnerabilityFinding
    from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

    if not asset.security_assets.exists():
        return [_tile("Sicurezza (SOC)", "Non collegato", "Collega il dispositivo dal SOC", "none", reverse("security:assets"))]
    tiles = []
    signals = SecurityAssetSignal.objects.filter(asset__hub_asset=asset)
    if profile in ("workstation", "server", "vm"):
        backup = signals.filter(kind=SecurityAssetSignal.KIND_BACKUP).order_by("-occurred_at", "-id").first()
        if backup is None:
            tiles.append(_tile("Ultimo backup", "Nessun dato", "Nessun job riportato", "none", TAB_SECURITY))
        else:
            ok = backup.status == "completed"
            old = now - backup.occurred_at > timedelta(days=2)
            value = {"completed": "Riuscito", "failed": "Fallito", "warning": "Con avvisi"}.get(backup.status, backup.status or "Non noto")
            tile = _tile("Ultimo backup", value, _when(backup.occurred_at),
                         "bad" if backup.status == "failed" else ("warn" if not ok or old else "ok"), TAB_SECURITY)
            runs = list(signals.filter(kind=SecurityAssetSignal.KIND_BACKUP).order_by("-occurred_at", "-id")
                        .values_list("status", flat=True)[:BACKUP_BARS])
            if len(runs) > 1:
                tile["bars"] = [{"completed": "ok", "failed": "bad"}.get(status, "warn") for status in reversed(runs)]
            tiles.append(tile)
        since = now - timedelta(days=30)
        detections = signals.filter(kind__in=(SecurityAssetSignal.KIND_DETECTIONS, SecurityAssetSignal.KIND_THREAT),
                                    occurred_at__gte=since).count()
        details = getattr(asset, "it_details", None)
        edr = "EDR dichiarato" if details and details.edr_enabled else "EDR non dichiarato"
        tiles.append(_tile("Antivirus / EDR", (f"{detections} rilevamenti" if detections > 1 else "1 rilevamento") if detections else "Nessun rilevamento",
                           f"Ultimi 30 giorni · {edr}", "warn" if detections else "ok", TAB_SECURITY))
    alerts = SecurityAlert.objects.filter(event__asset__hub_asset=asset, status__in=ACTIVE_ALERT_STATUSES).count()
    tiles.append(_tile("Alert SOC aperti", str(alerts), "Compresi rinviati e silenziati", "bad" if alerts else "ok", TAB_SECURITY))
    if profile == "network":
        events = SecurityEventRecord.objects.filter(asset__hub_asset=asset, suppressed=False,
                                                    occurred_at__gte=now - timedelta(days=7)).count()
        tiles.append(_tile("Eventi 7 giorni", str(events), "Dai report del firewall", "none", TAB_SECURITY))
    else:
        vulns = SecurityVulnerabilityFinding.objects.filter(asset__hub_asset=asset, status__in=ACTIVE_ALERT_STATUSES)
        critical = vulns.filter(cvss__gte=9.0).count()
        total = vulns.count()
        tiles.append(_tile("Vulnerabilità aperte", str(total), (f"{critical} critiche" if critical > 1 else "1 critica") if critical else "Nessuna critica",
                           "bad" if critical else ("warn" if total else "ok"), TAB_SECURITY))
    return tiles


def device_kpis(request, asset, it_presentation=None) -> dict | None:
    """``{"profile", "title", "tiles"}`` oppure ``None`` se non c'e' nulla da mostrare."""
    profile = profile_for(asset, it_presentation)
    if not profile:
        return None
    now = timezone.now()
    show_snmp, show_soc = can_view_snmp(request), can_view_soc(request)
    tiles = []
    try:
        if show_snmp:
            if profile == "printer":
                tiles += _printer_tiles(asset, now)
            else:
                from contatori.models import DispositivoSNMP, Macchina

                state = _snmp_state_tile(list(DispositivoSNMP.objects.filter(asset=asset))
                                         + list(Macchina.objects.filter(asset=asset)), now)
                if state:
                    tiles.append(state)
                if profile in ("network", "server", "generic"):
                    tiles += _probe_tiles(asset)
    except DatabaseError:
        pass
    try:
        if show_soc and profile != "printer":
            tiles += _soc_tiles(asset, profile, now)
    except DatabaseError:
        pass
    if not tiles:
        return None
    titles = {
        "printer": "Stampa e consumabili", "network": "Rete e sicurezza perimetrale",
        "workstation": "Protezione della postazione", "server": "Servizio e protezione",
        "vm": "Servizio e protezione", "generic": "Monitoraggio",
    }
    return {"profile": profile, "title": titles.get(profile, "Monitoraggio"), "tiles": tiles[:8]}
