"""Estrazioni archiviate: configurazione, snapshot e file rimangono congelati."""
import calendar
import hashlib
import json
import logging
from copy import deepcopy
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_q.tasks import async_task

from assets.models import Asset, AssetReportRun, AssetReportSchedule

logger = logging.getLogger(__name__)


def display_snapshot(snapshot):
    """Date leggibili nel fuso del portale, senza modificare lo snapshot archiviato."""
    data = deepcopy(snapshot)
    def local(value):
        parsed = parse_datetime(value) if value else None
        return timezone.localtime(parsed).strftime("%d/%m/%Y %H:%M %Z") if parsed else value
    if data:
        data["captured_at"] = local(data["captured_at"])
        for row in data.get("trend", []):
            row["date"] = local(row["date"])
        for row in data.get("mfc", []):
            row["data"] = local(row["data"])
        for row in data.get("devices", []):
            row["controllo"] = local(row["controllo"])
    return data


def configuration(plan):
    return {
        "name": plan.name, "asset_type": plan.asset_type,
        "asset_category_id": plan.asset_category_id, "reparto": plan.reparto,
        "scope_label": " · ".join([plan.get_asset_type_display() or "Tutti i tipi", str(plan.asset_category or "Tutte le categorie"), plan.reparto or "Tutti i reparti"]),
        "include_snmp": plan.include_snmp, "export_pdf": plan.export_pdf,
        "export_excel": plan.export_excel,
    }


def scope_key(config):
    scope = {k: config[k] for k in ("asset_type", "asset_category_id", "reparto", "include_snmp")}
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def next_deadline(plan, now):
    if plan.frequency == AssetReportSchedule.Frequency.ONCE:
        return None
    value = timezone.localtime(plan.next_run)
    now = timezone.localtime(now)
    if plan.frequency in ("DAILY", "WEEKLY"):
        days = 1 if plan.frequency == "DAILY" else 7
        jumps = max(1, (now.date() - value.date()).days // days)
        value += timedelta(days=days * jumps)
        if value <= now:
            value += timedelta(days=days)
    else:
        while value <= now:
            year, month = value.year + (value.month == 12), value.month % 12 + 1
            value = value.replace(year=year, month=month, day=min(plan.anchor_day, calendar.monthrange(year, month)[1]))
    return value


def create_run(plan, due_at, user=None):
    config = configuration(plan)
    return AssetReportRun.objects.get_or_create(
        schedule=plan, due_at=due_at,
        defaults={"configuration": config, "scope_key": scope_key(config), "requested_by": user},
    )[0]


def enqueue_run(pk):
    now = timezone.now()
    # Compare-and-set: due dispatcher simultanei non accodano lo stesso report.
    eligible = AssetReportRun.objects.filter(pk=pk, attempts__lt=3).exclude(status="DONE")
    eligible = eligible.filter(Q(enqueued_at__isnull=True) | Q(enqueued_at__lt=now - timedelta(minutes=10)))
    if not eligible.update(enqueued_at=now):
        return False
    try:
        async_task("assets.services.reporting.generate_run", pk, q_options={"timeout": 110})
    except Exception:
        AssetReportRun.objects.filter(pk=pk).update(enqueued_at=None, error="Worker non raggiungibile: nuovo tentativo al prossimo controllo.")
        raise
    return True


def dispatch_due_reports():
    now = timezone.now()
    # Un processo terminato dal timeout non entra nel blocco except del worker.
    AssetReportRun.objects.filter(
        status="RUNNING", attempts__gte=3, started_at__lt=now - timedelta(minutes=10),
    ).update(status="ERROR", error="Elaborazione interrotta dopo tre tentativi. Verificare il worker e riprovare.")
    due_ids = list(AssetReportSchedule.objects.filter(enabled=True, next_run__lte=now).values_list("pk", flat=True)[:100])
    for pk in due_ids:
        with transaction.atomic():
            plan = AssetReportSchedule.objects.select_for_update().get(pk=pk)
            if not plan.enabled or plan.next_run > now:
                continue
            create_run(plan, plan.next_run)
            following = next_deadline(plan, now)
            if following is None:
                plan.enabled = False
            else:
                plan.next_run = following
            plan.save(update_fields=["enabled", "next_run", "updated_at"])
    waiting = AssetReportRun.objects.exclude(status="DONE").filter(attempts__lt=3)
    waiting = waiting.filter(Q(enqueued_at__isnull=True) | Q(enqueued_at__lt=now - timedelta(minutes=10)))
    queued = 0
    for pk in waiting.values_list("pk", flat=True)[:100]:
        queued += int(enqueue_run(pk))
    return {"accodati": queued}


def build_snapshot(config):
    qs = Asset.objects.select_related("asset_category").prefetch_related("endpoints").order_by("asset_tag")
    for key in ("asset_type", "asset_category_id", "reparto"):
        if config.get(key):
            qs = qs.filter(**{key: config[key]})
    if qs.count() > 10000:
        raise ValueError("Oltre 10.000 asset: restringere il perimetro per tipo, categoria o reparto.")
    # Prefetch a blocchi per non superare i 2100 parametri di SQL Server.
    assets = list(qs.iterator(chunk_size=500))
    rows = [{
        "id": a.pk, "tag": a.asset_tag, "nome": a.name,
        "tipo": a.get_asset_type_display(), "categoria": str(a.asset_category or ""),
        "reparto": a.reparto, "stato": a.get_status_display(),
        "seriale": a.serial_number or "", "produttore": a.manufacturer or "", "modello": a.model or "",
        "ubicazione": a.assignment_location, "ip": ", ".join(e.ip for e in a.endpoints.all() if e.ip),
    } for a in assets]
    metrics = {"assets": len(assets), "in_use": sum(a.status == "IN_USE" for a in assets),
               "in_repair": sum(a.status == "IN_REPAIR" for a in assets), "snmp_errors": 0}
    mfc, devices = [], []
    if config.get("include_snmp"):
        from contatori.models import DispositivoSNMP, LetturaMensileContatori, Macchina
        asset_ids = qs.order_by().values("pk")
        for machine in Macchina.objects.filter(asset_id__in=asset_ids).select_related("asset"):
            reading = LetturaMensileContatori.objects.filter(macchina=machine).order_by("-mese").first()
            mfc.append({"asset": machine.asset.asset_tag, "nome": machine.reparto, "stato": machine.snmp_stato,
                        "mese": str(reading.mese) if reading else "", "data": reading.rilevata_il.isoformat() if reading else "",
                        **{k: getattr(reading, k) if reading else None for k in ("a4_bn", "a3_bn", "a4_col", "a3_col")}})
        for device in DispositivoSNMP.objects.filter(asset_id__in=asset_ids).select_related("asset"):
            latest = device.rilevazioni.order_by("-rilevata_il", "-pk").first()
            values = [] if latest is None else [{"sonda": v.sonda.nome, "valore": v.valore_display, "stato": v.stato} for v in latest.valori.select_related("sonda")]
            devices.append({"asset": device.asset.asset_tag, "nome": device.nome, "host": device.host,
                            "stato": device.snmp_stato, "controllo": device.snmp_ultimo_controllo.isoformat() if device.snmp_ultimo_controllo else "", "valori": values})
        metrics["snmp_errors"] = sum(r["stato"] == "ERROR" for r in mfc + devices)
    return {"version": 1, "captured_at": timezone.now().isoformat(), "name": config["name"], "scope_label": config.get("scope_label", ""),
            "metrics": metrics, "assets": rows, "mfc": mfc, "devices": devices}


def generate_run(pk):
    with transaction.atomic():
        run = AssetReportRun.objects.select_for_update().get(pk=pk)
        if run.status == "DONE" or run.attempts >= 3 or (run.status == "RUNNING" and run.started_at and run.started_at > timezone.now() - timedelta(minutes=10)):
            return {"saltato": True}
        run.status, run.started_at = "RUNNING", timezone.now()
        run.attempts += 1
        run.save(update_fields=["status", "started_at", "attempts"])
    try:
        if not run.snapshot:
            run.snapshot = build_snapshot(run.configuration)
            previous = AssetReportRun.objects.filter(
                schedule_id=run.schedule_id, scope_key=run.scope_key, status="DONE",
                completed_at__lt=run.started_at,
            ).order_by("-completed_at").values_list("snapshot", flat=True)[:11]
            run.snapshot["trend"] = [
                {"date": item["captured_at"], **item["metrics"]} for item in reversed(list(previous))
            ] + [{"date": run.snapshot["captured_at"], **run.snapshot["metrics"]}]
            run.save(update_fields=["snapshot"])
        from assets.services.reporting_exports import export_pdf, export_excel
        pdf = export_pdf(run.snapshot) if run.configuration["export_pdf"] else None
        excel = export_excel(run.snapshot) if run.configuration["export_excel"] else None
        AssetReportRun.objects.filter(pk=pk).update(
            pdf_content=pdf, excel_content=excel, completed_at=timezone.now(), status="DONE", error="",
        )
        return {"report_id": pk, "assets": run.snapshot["metrics"]["assets"]}
    except Exception as exc:
        error = str(exc) if isinstance(exc, ValueError) else "Generazione non riuscita; verificare il worker e riprovare."
        AssetReportRun.objects.filter(pk=pk).update(status="ERROR", error=error[:500])
        logger.exception("Report Asset %s non generato", pk)
        raise
