"""ORM broker: coalesce only registered recurring flows, preserve manual jobs."""
from django.db import transaction
from django_q.brokers.orm import ORM
from django_q.conf import Conf
from django_q.signing import SignedPackage


class FlowBroker(ORM):
    def set_stat(self, key, value, timeout):
        # Sentinel calls this even when the queue is empty. Rate-limit SQL writes,
        # but persist every state transition (especially STOPPING/STOPPED).
        import time
        from datetime import timedelta
        from django.utils import timezone
        from .models import ClusterHeartbeat

        stat = SignedPackage.loads(value)
        status = "running" if stat.status in (Conf.IDLE, Conf.WORKING) else "unavailable"
        now_tick = time.monotonic()
        previous = getattr(self, "_heartbeat_write", None)
        if previous is None or previous[1] != status or now_tick - previous[0] >= 15:
            now = timezone.now()
            ClusterHeartbeat.objects.using(Conf.ORM).update_or_create(
                instance=str(stat.cluster_id),
                defaults={"cluster": self.list_key, "seen_at": now, "status": status},
            )
            # Keep restart history bounded, without deleting current instances.
            if previous is None:
                ClusterHeartbeat.objects.using(Conf.ORM).filter(
                    cluster=self.list_key, seen_at__lt=now - timedelta(days=7)
                ).delete()
            self._heartbeat_write = (now_tick, status)
        return super().set_stat(key, value, timeout)

    def enqueue(self, task):
        from .models import ManagedFlow
        package = SignedPackage.loads(task)
        code = package.get("group")
        if (package.get("func") != "automazioni.managed_flows.run_managed_flow"
                or tuple(package.get("args", ())) != (code,)
                or package.get("kwargs") or package.get("hook")):
            return super().enqueue(task)
        with transaction.atomic(using=Conf.ORM):
            binding = ManagedFlow.objects.using(Conf.ORM).select_for_update().filter(code=code, kind="schedule").first()
            if not binding:
                return super().enqueue(task)
            qs = self.get_connection()
            if binding.queued_task_id and qs.filter(pk=binding.queued_task_id, key=self.list_key).exists():
                return binding.queued_task_id
            pk = super().enqueue(task)
            binding.queued_task_id = pk
            binding.save(update_fields=["queued_task_id"])
            return pk
