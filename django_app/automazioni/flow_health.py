from datetime import timedelta
from django.db.models import Max, Q
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import OrmQ, Task


def broker_health():
    count = OrmQ.objects.filter(key=Conf.CLUSTER_NAME).count()
    latest = Task.objects.filter(Q(cluster__in=[Conf.CLUSTER_NAME, ""]) | Q(cluster__isnull=True)).aggregate(last=Max("stopped"))["last"]
    return {"queued": count, "last_completed": latest,
            "stalled": bool(count and (latest is None or latest < timezone.now()-timedelta(minutes=10)))}
