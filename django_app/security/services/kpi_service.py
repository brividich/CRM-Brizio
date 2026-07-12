from django.db.models import Count, Q
from django.utils import timezone

from security.models import BackupJobRecord, SecurityEventRecord, SecurityKpiSnapshot, SecurityReportMetric


def build_daily_kpi_snapshots(snapshot_date=None):
    snapshot_date = snapshot_date or timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(snapshot_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(snapshot_date, timezone.datetime.max.time()))
    created = 0
    rows = (
        SecurityEventRecord.objects.filter(occurred_at__range=(start, end))
        .values("source", "event_type")
        .annotate(total=Count("id"))
    )
    for row in rows:
        _upsert_snapshot(row["source"], snapshot_date, row["event_type"], row["total"])
        created += 1
    created += _build_report_metric_snapshots(snapshot_date)
    created += _build_backup_kpi_snapshots(snapshot_date, start, end)
    return created


def _build_report_metric_snapshots(snapshot_date):
    created = 0
    metric_rows = (
        SecurityReportMetric.objects.filter(report__report_date=snapshot_date)
        .values("report__source", "name")
        .annotate(total=Count("id"))
    )
    for row in metric_rows:
        values = SecurityReportMetric.objects.filter(
            report__report_date=snapshot_date,
            report__source=row["report__source"],
            name=row["name"],
        ).values_list("value", flat=True)
        _upsert_snapshot(row["report__source"], snapshot_date, row["name"], sum(values))
        created += 1
    return created


def _build_backup_kpi_snapshots(snapshot_date, start, end):
    created = 0
    backup_rows = (
        BackupJobRecord.objects.filter(
            Q(completed_at__range=(start, end))
            | Q(completed_at__isnull=True, started_at__range=(start, end))
            | Q(completed_at__isnull=True, started_at__isnull=True, created_at__range=(start, end))
        )
        .values("source")
        .annotate(
            completed=Count("id", filter=Q(status="completed")),
            failed=Count("id", filter=Q(status="failed")),
            warning=Count("id", filter=Q(status="warning")),
        )
    )
    for row in backup_rows:
        source_id = row["source"]
        records = BackupJobRecord.objects.filter(
            source_id=source_id,
        ).filter(
            Q(completed_at__range=(start, end))
            | Q(completed_at__isnull=True, started_at__range=(start, end))
            | Q(completed_at__isnull=True, started_at__isnull=True, created_at__range=(start, end))
        )
        durations = [record.payload.get("duration_seconds") for record in records if record.payload.get("duration_seconds") is not None]
        transferred_sizes = [
            record.payload.get("transferred_size_gb")
            for record in records
            if record.payload.get("transferred_size_gb") is not None
        ]
        devices = {record.payload.get("device_name") for record in records if record.payload.get("device_name")}
        metric_values = {
            "backup_completed_count": row["completed"],
            "backup_failed_count": row["failed"],
            "backup_warning_count": row["warning"],
            "backup_transferred_total_gb": sum(transferred_sizes),
            "backup_duration_avg_seconds": sum(durations) / len(durations) if durations else 0,
            "backup_duration_max_seconds": max(durations) if durations else 0,
            "backup_devices_backed_up": len(devices),
        }
        for name, value in metric_values.items():
            _upsert_snapshot(source_id, snapshot_date, name, value)
            created += 1
        # TODO: add missing_expected_backups when an expected-backup schedule model exists.
    return created


def _upsert_snapshot(source_id, snapshot_date, name, value):
    SecurityKpiSnapshot.objects.update_or_create(
        source_id=source_id,
        snapshot_date=snapshot_date,
        name=name,
        defaults={"value": value, "labels": {"source_id": source_id}},
    )
