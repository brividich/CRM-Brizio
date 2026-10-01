from datetime import timedelta
from django.db.models import Max, Q
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import OrmQ, Task
from .models import ClusterHeartbeat, ClusterWatchdogState


def broker_health():
    now = timezone.now()
    count = OrmQ.objects.using(Conf.ORM).filter(key=Conf.CLUSTER_NAME).count()
    latest = Task.objects.using(Conf.ORM).filter(Q(cluster__in=[Conf.CLUSTER_NAME, ""]) | Q(cluster__isnull=True)).aggregate(last=Max("stopped"))["last"]
    beats = ClusterHeartbeat.objects.using(Conf.ORM).filter(cluster=Conf.CLUSTER_NAME)
    running = beats.filter(status="running", seen_at__gte=now-timedelta(seconds=120)).exists()
    last_heartbeat = beats.aggregate(last=Max("seen_at"))["last"]
    stalled = bool(count and (latest is None or latest < now-timedelta(minutes=10)))
    watchdog = ClusterWatchdogState.objects.using(Conf.ORM).filter(cluster=Conf.CLUSTER_NAME).first()
    checked_at = watchdog.checked_at if watchdog else None
    return {"queued": count, "last_completed": latest, "stalled": stalled,
            "worker_alive": running, "last_heartbeat": last_heartbeat,
            "unhealthy": not running or stalled,
            "reason": "worker_unavailable" if not running else ("queue_stalled" if stalled else "ok"),
            "watchdog_checked_at": checked_at,
            "watchdog_stale": not checked_at or checked_at < now-timedelta(minutes=5)}
