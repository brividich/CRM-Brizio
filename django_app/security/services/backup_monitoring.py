from django.utils import timezone

from security.models import BackupExpectedJobConfig, BackupJobRecord


def missing_backup_candidates(now=None):
    now = now or timezone.now()
    candidates = []
    for config in BackupExpectedJobConfig.objects.filter(enabled=True, alert_on_missing=True):
        cutoff = now - timezone.timedelta(hours=config.missing_after_hours)
        jobs = BackupJobRecord.objects.filter(job_name=config.job_name, created_at__gte=cutoff)
        if config.device_name:
            jobs = jobs.filter(payload__device_name=config.device_name)
        if config.nas_name:
            jobs = jobs.filter(payload__nas_name=config.nas_name)
        if not jobs.exists():
            candidates.append(
                {
                    "config": config,
                    "job_name": config.job_name,
                    "device_name": config.device_name,
                    "nas_name": config.nas_name,
                    "reason": f"No backup job seen in the last {config.missing_after_hours} hours",
                    "severity": "critical" if config.critical_asset else "warning",
                }
            )
    return candidates


def last_seen_backup_status(config):
    jobs = BackupJobRecord.objects.filter(job_name=config.job_name).order_by("-created_at")
    if config.device_name:
        jobs = jobs.filter(payload__device_name=config.device_name)
    if config.nas_name:
        jobs = jobs.filter(payload__nas_name=config.nas_name)
    return jobs.first()
