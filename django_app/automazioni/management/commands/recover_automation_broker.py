"""Reconcile known recurring invocations; never purge an entire broker."""
import uuid
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import OrmQ
from django_q.signing import SignedPackage

from automazioni.managed_flows import catalog
from automazioni.models import ManagedFlow, BrokerRecoveryEntry


class Command(BaseCommand):
    help = "Anteprima/recupero broker: archivia e accorpa solo ricorrenze note, worker fermi."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--workers-stopped", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        apply = options["apply"]
        if apply and not options["workers_stopped"]:
            raise CommandError("Arrestare tutti i worker del cluster e indicare --workers-stopped.")
        specs = catalog()
        bindings = {b.code: b for b in ManagedFlow.objects.filter(kind="schedule")}
        groups = defaultdict(list)
        preserved = 0
        qs = OrmQ.objects.filter(key=Conf.CLUSTER_NAME).order_by("id")
        if apply:
            qs = qs.select_for_update()
        locked = set()
        for row in qs:
            try:
                package = SignedPackage.loads(row.payload)
                code = package.get("group")
                spec = specs.get(code, {})
                native = (package.get("func") == spec.get("func") and not package.get("args")
                          and (package.get("kwargs") or {}) == spec.get("kwargs", {}))
                managed = (package.get("func") == "automazioni.managed_flows.run_managed_flow"
                           and tuple(package.get("args", ())) == (code,) and not package.get("kwargs"))
                if spec.get("kind") != "schedule" or code not in bindings or package.get("hook") or not (native or managed):
                    preserved += 1
                    continue
                if row.lock > timezone.now():
                    locked.add(code)
                groups[code].append((row, package))
            except Exception:
                preserved += 1
        batch = uuid.uuid4()
        coalesced = converted = 0
        for code, rows in groups.items():
            if code in locked:
                preserved += len(rows)
                continue
            coalesced += len(rows) - 1
            converted += 1
            if not apply:
                continue
            # Every changed/deleted packet is retained in the same transaction.
            for row, package in rows:
                BrokerRecoveryEntry.objects.create(batch=batch, original_id=row.pk, key=row.key,
                    signed_payload=row.payload, original_lock=row.lock, flow_code=code)
            keeper, package = rows[-1]
            package.update(func="automazioni.managed_flows.run_managed_flow", args=(code,), kwargs={})
            keeper.payload = SignedPackage.dumps(package)
            keeper.save(update_fields=["payload"])
            OrmQ.objects.filter(pk__in=[r.pk for r, p in rows[:-1]]).delete()
            ManagedFlow.objects.filter(pk=bindings[code].pk).update(queued_task_id=keeper.pk,
                                                                  running_until=None, lease_token=None)
        self.stdout.write(f"{'APPLICATO' if apply else 'ANTEPRIMA'}: ricorrenze={converted}, "
                          f"copie_accorpabili={coalesced}, preservati={preserved}, batch={batch if apply else '-'}")
