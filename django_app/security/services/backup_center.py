"""Sezione Backup del SOC: KPI, statistiche per dispositivo e per job, log delle esecuzioni.

Tutto si ricava dai ``BackupJobRecord`` già salvati: nessun dato nuovo da importare.
Un job copre più dispositivi e la granularità dipende dal fornitore:

- **Veeam**: ``payload["objects"]`` ha l'esito *di ogni macchina* (stato, dimensione,
  trasferito, durata): la statistica per PC è esatta;
- **Synology Active Backup**: ``payload["devices"]`` elenca i dispositivi del job ma
  l'esito, la durata e i GB sono del job intero: ogni dispositivo eredita l'esito del job
  (marcato ``job_level`` così la pagina lo dice);
- record senza dispositivi: contano solo per il job.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from security.models import BackupJobRecord

OK, WARN, FAIL = "completed", "warning", "failed"
STATUS_LABELS = {OK: "Riuscito", WARN: "Con avvisi", FAIL: "Fallito", "unknown": "Sconosciuto"}
STATUS_TONES = {OK: "success", WARN: "warning", FAIL: "critical"}
PERIODS = [(7, "7 giorni"), (30, "30 giorni"), (90, "90 giorni")]
STALE_DAYS = 3  # un PC senza backup riuscito da più di 3 giorni va guardato
STRIP_RUNS = 14  # esecuzioni mostrate nella striscia di ogni dispositivo


def when(record):
    return record.completed_at or record.started_at or record.created_at


def _size_gb(text):
    """«12,5 GB», «830 MB» → GB. Le tabelle Veeam danno le dimensioni come testo."""
    match = re.match(r"\s*([0-9][0-9.,]*)\s*([KMGT]?B)", str(text or ""), re.I)
    if not match:
        return None
    amount = match.group(1)
    if "," in amount and "." in amount:
        amount = amount.replace(".", "").replace(",", ".")
    else:
        amount = amount.replace(",", ".")
    try:
        value = float(amount)
    except ValueError:
        return None
    return value * {"B": 1 / 1024 ** 3, "KB": 1 / 1024 ** 2, "MB": 1 / 1024, "GB": 1, "TB": 1024}[match.group(2).upper()]


def _duration_seconds(text):
    parts = str(text or "").strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None
    return None


def device_runs(record):
    """Esecuzioni per dispositivo contenute in un record di job."""
    payload = record.payload or {}
    at = when(record)
    objects = payload.get("objects") or []
    if objects:
        return [
            {
                "device": str(obj.get("name") or "").strip(),
                "status": obj.get("status") or record.status,
                "at": at,
                "gb": _size_gb(obj.get("transferred")),
                "seconds": _duration_seconds(obj.get("duration")),
                "job": record.job_name,
                "record_id": record.pk,
                "job_level": False,
                "detail": str(obj.get("details") or "")[:200],
            }
            for obj in objects
            if str(obj.get("name") or "").strip()
        ]
    devices = payload.get("devices") or [d.strip() for d in str(payload.get("device_name") or "").split(",")]
    devices = [d for d in devices if d]
    return [
        {
            "device": device,
            "status": record.status,
            "at": at,
            "gb": payload.get("transferred_size_gb") if len(devices) == 1 else None,
            "seconds": payload.get("duration_seconds") if len(devices) == 1 else None,
            "job": record.job_name,
            "record_id": record.pk,
            "job_level": len(devices) > 1,
            "detail": "",
        }
        for device in devices
    ]


def _records(since):
    return BackupJobRecord.objects.filter(
        Q(completed_at__gte=since) | Q(completed_at__isnull=True, started_at__gte=since)
        | Q(completed_at__isnull=True, started_at__isnull=True, created_at__gte=since)
    ).select_related("source")


def _rate(ok, total):
    return round(100 * ok / total, 1) if total else None


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def overview(days=30, now=None):
    now = now or timezone.now()
    since = now - timedelta(days=days)
    records = sorted(_records(since), key=when)

    status_counts = defaultdict(int)
    jobs = {}
    devices = {}
    for record in records:
        status_counts[record.status] += 1
        payload = record.payload or {}
        job = jobs.setdefault(record.job_name, {
            "name": record.job_name, "vendor": payload.get("vendor") or "", "nas": payload.get("nas_name") or "",
            "runs": 0, "ok": 0, "warn": 0, "fail": 0, "gb": [], "seconds": [], "last": None, "last_ok": None, "devices": set(),
        })
        job["runs"] += 1
        job["ok"] += record.status == OK
        job["warn"] += record.status == WARN
        job["fail"] += record.status == FAIL
        job["gb"].append(payload.get("transferred_size_gb"))
        job["seconds"].append(payload.get("duration_seconds"))
        job["last"] = record
        if record.status == OK:
            job["last_ok"] = when(record)
        for run in device_runs(record):
            job["devices"].add(run["device"])
            dev = devices.setdefault(run["device"].casefold(), {
                "name": run["device"], "runs": [], "jobs": set(), "job_level": False,
            })
            dev["runs"].append(run)
            dev["jobs"].add(run["job"])
            dev["job_level"] = dev["job_level"] or run["job_level"]

    device_rows = [_device_row(dev, now) for dev in devices.values()]
    # Prima chi è in difficoltà: ultimo esito fallito, poi senza riuscito recente, poi tasso basso.
    device_rows.sort(key=lambda r: (r["last_status"] != FAIL, not r["stale"], r["rate"] if r["rate"] is not None else 100, r["name"].casefold()))
    job_rows = []
    for job in jobs.values():
        last = job["last"]
        job_rows.append({
            "name": job["name"], "vendor": job["vendor"], "nas": job["nas"], "runs": job["runs"],
            "ok": job["ok"], "warn": job["warn"], "fail": job["fail"], "rate": _rate(job["ok"], job["runs"]),
            "avg_gb": _mean(job["gb"]), "avg_minutes": (_mean(job["seconds"]) or 0) / 60 if _mean(job["seconds"]) else None,
            "last_status": last.status, "last_at": when(last), "last_ok": job["last_ok"], "devices": len(job["devices"]),
            "tone": STATUS_TONES.get(last.status, "muted"),
            "last_label": STATUS_LABELS.get(last.status, last.status),
        })
    job_rows.sort(key=lambda r: (r["last_status"] != FAIL, r["rate"] if r["rate"] is not None else 100, r["name"].casefold()))

    total = len(records)
    gb_total = sum(v for v in ((r.payload or {}).get("transferred_size_gb") for r in records) if isinstance(v, (int, float)))
    try:
        from security.services.backup_monitoring import missing_backup_candidates

        missing = missing_backup_candidates(now)
    except Exception:  # noqa: BLE001 - un controllo che fallisce non blocca la pagina
        missing = []
    findings = [
        {"level": "high", "title": f"Backup atteso non arrivato: {m['job_name']}",
         "detail": f"{m['device_name'] + ' · ' if m.get('device_name') else ''}nessun esito nelle ultime {m['config'].missing_after_hours} ore", "device": ""}
        for m in missing
    ]
    findings += [
        {"level": "high", "title": f"{r['name']}: ultimo backup fallito", "detail": f"{r['last_at']:%d/%m %H:%M} · {', '.join(r['jobs'])}", "device": r["name"]}
        for r in device_rows if r["last_status"] == FAIL
    ]
    findings += [
        {"level": "warning", "title": f"{r['name']}: nessun backup riuscito da {'oltre ' + str(days) + ' giorni' if r['last_ok'] is None else str(r['days_since_ok']) + ' giorni'}",
         "detail": ", ".join(r["jobs"]), "device": r["name"]}
        for r in device_rows if r["stale"] and r["last_status"] != FAIL
    ]
    return {
        "days": days,
        "since": since,
        "findings": findings,
        "kpi": {
            "runs": total,
            "ok": status_counts.get(OK, 0),
            "warn": status_counts.get(WARN, 0),
            "fail": status_counts.get(FAIL, 0),
            "rate": _rate(status_counts.get(OK, 0), total),
            "gb": gb_total,
            "avg_minutes": (_mean([(r.payload or {}).get("duration_seconds") for r in records]) or 0) / 60 if records else None,
            "devices": len(device_rows),
            "devices_stale": sum(1 for r in device_rows if r["stale"]),
            "devices_failing": sum(1 for r in device_rows if r["last_status"] == FAIL),
            "jobs": len(job_rows),
            "missing": len(missing),
        },
        "devices": device_rows,
        "jobs": job_rows,
        "missing": missing,
        "daily": daily_chart(records, days, now),
    }


def _device_row(dev, now):
    runs = sorted(dev["runs"], key=lambda r: r["at"])
    last = runs[-1]
    ok_runs = [r for r in runs if r["status"] == OK]
    last_ok = ok_runs[-1]["at"] if ok_runs else None
    days_since_ok = (now - last_ok).days if last_ok else None
    strip = [
        {"tone": STATUS_TONES.get(r["status"], "muted"), "label": STATUS_LABELS.get(r["status"], r["status"]), "at": r["at"], "job": r["job"]}
        for r in runs[-STRIP_RUNS:]
    ]
    return {
        "name": dev["name"],
        "jobs": sorted(dev["jobs"]),
        "runs": len(runs),
        "ok": len(ok_runs),
        "fail": sum(1 for r in runs if r["status"] == FAIL),
        "rate": _rate(len(ok_runs), len(runs)),
        "last_status": last["status"],
        "last_label": STATUS_LABELS.get(last["status"], last["status"]),
        "last_tone": STATUS_TONES.get(last["status"], "muted"),
        "last_at": last["at"],
        "last_ok": last_ok,
        "days_since_ok": days_since_ok,
        "stale": last_ok is None or days_since_ok > STALE_DAYS,
        "gb": sum(r["gb"] for r in runs if r["gb"] is not None) or None,
        "avg_minutes": (_mean([r["seconds"] for r in runs]) or 0) / 60 if _mean([r["seconds"] for r in runs]) else None,
        "job_level": dev["job_level"],
        "strip": strip,
    }


def device_detail(name, days=90, now=None):
    """Storico di un dispositivo: esecuzioni (anche dei job condivisi) dalla più recente."""
    now = now or timezone.now()
    key = name.casefold()
    runs = []
    for record in _records(now - timedelta(days=days)):
        runs += [r for r in device_runs(record) if r["device"].casefold() == key]
    if not runs:
        return None
    dev = {"name": runs[0]["device"], "runs": runs, "jobs": {r["job"] for r in runs}, "job_level": any(r["job_level"] for r in runs)}
    row = _device_row(dev, now)
    for run in runs:
        run["label"] = STATUS_LABELS.get(run["status"], run["status"])
        run["tone"] = STATUS_TONES.get(run["status"], "muted")
        run["minutes"] = run["seconds"] / 60 if run["seconds"] else None
    row["history"] = sorted(runs, key=lambda r: r["at"], reverse=True)
    row["asset"] = _hub_asset(dev["name"])
    return row


def _hub_asset(name):
    """Asset HUB collegato (stesso nome host nei dispositivi SOC), se c'è."""
    from security.models import SecurityAsset

    match = SecurityAsset.objects.filter(hostname__iexact=name, hub_asset__isnull=False).select_related("hub_asset").first()
    return match.hub_asset if match else None


def log_rows(params, limit=300):
    """Log delle esecuzioni con filtri: esito, job, dispositivo o testo libero."""
    qs = BackupJobRecord.objects.select_related("source").order_by("-completed_at", "-started_at", "-created_at")
    status = params.get("esito", "")
    if status in STATUS_LABELS:
        qs = qs.filter(status=status)
    job = params.get("job", "").strip()
    if job:
        qs = qs.filter(job_name=job)
    days = params.get("giorni", "")
    if days.isdigit():
        since = timezone.now() - timedelta(days=int(days))
        qs = qs.filter(Q(completed_at__gte=since) | Q(completed_at__isnull=True, created_at__gte=since))
    text = params.get("q", "").strip().casefold()
    rows = []
    for record in qs[:2000]:
        payload = record.payload or {}
        devices = [run["device"] for run in device_runs(record)]
        if text and text not in record.job_name.casefold() and not any(text in d.casefold() for d in devices):
            continue
        rows.append({
            "record": record,
            "at": when(record),
            "label": STATUS_LABELS.get(record.status, record.status),
            "tone": STATUS_TONES.get(record.status, "muted"),
            "vendor": payload.get("vendor") or "",
            "devices": devices,
            "gb": payload.get("transferred_size_gb"),
            "minutes": payload["duration_seconds"] / 60 if payload.get("duration_seconds") else None,
            "objects_error": payload.get("objects_error"),
        })
        if len(rows) >= limit:
            break
    return rows


def daily_chart(records, days, now):
    """Barre impilate per giorno: riusciti, con avvisi, falliti (stesse coordinate del grafico VPN)."""
    today = timezone.localtime(now).date()
    day_from = today - timedelta(days=days - 1)
    counts = defaultdict(lambda: {OK: 0, WARN: 0, FAIL: 0})
    for record in records:
        day = timezone.localtime(when(record)).date()
        if day >= day_from and record.status in (OK, WARN, FAIL):
            counts[day][record.status] += 1
    span = days
    width, height, top, left = 760, 170, 14, 34  # stesse proporzioni del grafico Accessi VPN
    peak = max([sum(c.values()) for c in counts.values()] or [1]) or 1
    slot = (width - left) / span
    bar = max(slot * 0.68, 3)
    baseline = top + height
    out = []
    for i in range(span):
        day = day_from + timedelta(days=i)
        c = counts.get(day, {OK: 0, WARN: 0, FAIL: 0})
        y = baseline
        segments = []
        for status, css in ((OK, "bar-ok"), (WARN, "bar-warn"), (FAIL, "bar-ko")):
            h = height * c[status] / peak
            if h:
                # 2px di stacco tra i segmenti impilati (resta il colore della superficie).
                y -= h
                segments.append({"css": css, "y": round(y, 1), "h": round(max(h - 2, 1), 1)})
        out.append({
            "date": day, "x": round(left + i * slot + (slot - bar) / 2, 1), "w": round(bar, 1),
            "label_x": round(left + i * slot + slot / 2, 1), "segments": segments,
            "ok": c[OK], "warn": c[WARN], "fail": c[FAIL], "total": sum(c.values()),
            "show_label": i % max(span // 8, 1) == 0,
        })
    return {"days": out, "peak": peak, "width": width, "height": height + top + 24, "baseline": baseline, "top": top,
            "left": left, "empty": not counts}
