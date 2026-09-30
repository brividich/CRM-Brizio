"""ORM broker: coalesce only registered recurring flows, preserve manual jobs."""
from django.db import transaction
from django_q.brokers.orm import ORM
from django_q.conf import Conf
from django_q.signing import SignedPackage


class FlowBroker(ORM):
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
