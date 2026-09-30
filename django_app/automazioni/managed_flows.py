"""Bridge between native application processes and the editable rule designer.

Only registered processes may be invoked. Native arguments remain in memory;
they are never copied into automation payloads or run logs.
"""
from contextvars import ContextVar
from datetime import timedelta
from functools import wraps
import uuid

from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import AutomationAction, AutomationRule, ManagedFlow

_invocation = ContextVar("automation_native_invocation", default=None)


def catalog():
    from .event_notifications import EVENT_NOTIFICATIONS
    from .schedules import SCHEDULES, schedule_descriptions
    descriptions = schedule_descriptions()
    entries = {s["name"]: {**s, "kind": "schedule", "label": s["name"].replace("_", " "),
                           "description": descriptions.get(s["name"], ""),
                           "module": s["func"].split(".")[0]} for s in SCHEDULES}
    for e in EVENT_NOTIFICATIONS:
        entries[e["code"]] = {**e, "kind": "event", "name": e["code"],
                               "description": e["trigger"], "module": e["source"].split("/")[0]}
    return entries


@transaction.atomic
def install_flows():
    """Explicit idempotent installation; never overwrite edited actions or state."""
    from monitoring.models import ScheduleControl
    from django_q.models import Schedule
    controls = dict(ScheduleControl.objects.values_list("name", "enabled"))
    live = {s.name: s for s in Schedule.objects.all()}
    created = 0
    for code, spec in catalog().items():
        if ManagedFlow.objects.filter(code=code).exists():
            continue
        rule, new_rule = AutomationRule.objects.get_or_create(
            code="managed-" + code,
            defaults=dict(name=spec["label"], description=spec["description"],
                          source_code="managed_flows", operation_type="manual",
                          trigger_scope="all_inserts", is_active=controls.get(code, True),
                          is_draft=False, stop_on_first_failure=True),
        )
        if not new_rule:
            raise ValueError(f"Codice riservato già presente: managed-{code}")
        s = live.get(code)
        ManagedFlow.objects.create(
            code=code, rule=rule, kind=spec["kind"],
            schedule_type=getattr(s, "schedule_type", None) or spec.get("schedule_type", "I"),
            minutes=getattr(s, "minutes", None) or spec.get("minutes") or 1,
            cron=getattr(s, "cron", None) or spec.get("cron", ""),
        )
        AutomationAction.objects.create(rule=rule, order=1, action_type="native_process",
                                        config_json={}, description=spec["description"])
        created += 1
    return created


def invoke_native(action, run_log):
    binding = ManagedFlow.objects.filter(rule_id=getattr(run_log, "rule_id", None)).first()
    if not binding or binding.code not in catalog():
        raise ValueError("L'azione di modulo richiede un flusso registrato.")
    if run_log.is_test:
        return {"preview": True}
    ctx = _invocation.get()
    if not ctx or ctx["code"] != binding.code or ctx["used"]:
        raise ValueError("Contesto di esecuzione assente o azione di modulo già eseguita.")
    ctx["used"] = True
    ctx["result"] = ctx["call"]()
    return ctx["result"]


def _execute(binding, callback, *, initiated_by=None, raise_on_error=True):
    from .services import run_rule
    if not binding.rule.is_active or binding.rule.is_draft:
        return {"skipped": True, "reason": "disabled"}, None
    now = timezone.localtime()
    ctx = {"code": binding.code, "call": callback, "used": False, "result": None}
    token = _invocation.set(ctx)
    try:
        run = run_rule(binding.rule, {"flow_code": binding.code,
                       "module": catalog()[binding.code]["module"],
                       "hour": now.hour, "weekday": now.isoweekday()}, initiated_by=initiated_by)
        if run.status == "error" and raise_on_error:
            raise RuntimeError(f"Automazione {binding.code}: esecuzione {run.pk} in errore.")
        return ctx["result"], run
    finally:
        _invocation.reset(token)


def run_managed_flow(code, *, queue_limit=None):
    """Scheduled entry point, with durable exclusion and explicit rule state."""
    spec = catalog().get(code)
    if not spec or spec["kind"] != "schedule":
        raise ValueError("Flusso pianificato sconosciuto.")
    native_kwargs = dict(spec.get("kwargs", {}))
    if queue_limit is not None:
        if code != "automation_queue":
            raise ValueError("Il limite eventi si applica solo al processore della coda.")
        native_kwargs["limit"] = max(int(queue_limit), 1)
    token = uuid.uuid4()
    with transaction.atomic():
        binding = ManagedFlow.objects.select_for_update().select_related("rule").get(code=code)
        if code == "automation_queue" and binding.rule.last_run_at and binding.rule.last_run_at > timezone.now() - timedelta(seconds=45):
            return {"skipped": True, "reason": "recently_completed"}
        if binding.running_until and binding.running_until > timezone.now():
            return {"skipped": True, "reason": "already_running"}
        binding.lease_token = token
        binding.running_until = timezone.now() + timedelta(minutes=10)
        binding.save(update_fields=["lease_token", "running_until"])
    try:
        result, run = _execute(binding, lambda: import_string(spec["func"])(**native_kwargs))
        return {"run_id": run.pk if run else None, "status": run.status if run else "skipped"}
    finally:
        ManagedFlow.objects.filter(pk=binding.pk, lease_token=token).update(running_until=None, lease_token=None)


def event_flow(code, *, skipped_result=None):
    """Decorate notification-only functions, never business state transitions."""
    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            # The native action re-enters this function in its original context.
            ctx = _invocation.get()
            if ctx and ctx["code"] == code and ctx["used"]:
                return func(*args, **kwargs)
            binding = ManagedFlow.objects.select_related("rule").filter(code=code, kind="event").first()
            if binding is None:
                # Backward-compatible only until the explicit installation.
                return func(*args, **kwargs)
            result, run = _execute(binding, lambda: func(*args, **kwargs), raise_on_error=False)
            return result if run and run.status == "success" else skipped_result
        return wrapped
    return decorate


def synchronize_schedule(binding):
    from .schedules import register_schedule, delete_schedule, spec_by_name
    from monitoring.models import ScheduleControl
    if binding.kind != "schedule":
        return
    enabled = binding.rule.is_active and not binding.rule.is_draft
    ScheduleControl.objects.update_or_create(name=binding.code, defaults={"enabled": enabled})
    if enabled:
        register_schedule(spec_by_name(binding.code))
    else:
        delete_schedule(binding.code)


def reconcile_expired_approvals():
    from .models import AutomationApproval, AutomationRunLog
    with transaction.atomic():
        qs = AutomationApproval.objects.select_for_update().filter(status="pending", expires_at__lt=timezone.now())
        ids = list(qs.values_list("run_log_id", flat=True))
        count = qs.update(status="expired")
        still_pending = AutomationApproval.objects.filter(run_log_id__in=ids, status="pending").values("run_log_id")
        AutomationRunLog.objects.filter(pk__in=ids, status="waiting_approval").exclude(pk__in=still_pending).update(
            status="skipped", result_message="Richiesta di approvazione scaduta; nessuna decisione applicata.",
            finished_at=timezone.now())
    return {"expired": count}
