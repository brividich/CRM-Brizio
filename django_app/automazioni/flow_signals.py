from django.db import transaction


def rule_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    # Runtime updates must not continually reset schedules.
    fields = kwargs.get("update_fields")
    if fields is not None and not {"is_active", "is_draft"}.intersection(fields):
        return
    from .models import ManagedFlow
    from .managed_flows import synchronize_schedule
    binding = ManagedFlow.objects.select_related("rule").filter(rule_id=instance.pk).first()
    if binding:
        transaction.on_commit(lambda: synchronize_schedule(binding))


def control_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    from .models import ManagedFlow, AutomationRule
    binding = ManagedFlow.objects.filter(code=instance.name, kind="schedule").first()
    if binding:
        fields = {"is_active": instance.enabled}
        if instance.enabled:
            fields["is_draft"] = False
        AutomationRule.objects.filter(pk=binding.rule_id).update(**fields)
