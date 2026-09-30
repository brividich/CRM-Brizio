from django.apps import AppConfig


class AutomazioniConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "automazioni"
    verbose_name = "Automazioni"

    def ready(self):
        from django.db.models.signals import post_save
        from .models import AutomationRule
        from .flow_signals import rule_saved, control_saved
        from monitoring.models import ScheduleControl
        post_save.connect(control_saved, sender=ScheduleControl, dispatch_uid="automazioni_managed_control_saved")
        post_save.connect(rule_saved, sender=AutomationRule, dispatch_uid="automazioni_managed_rule_saved")
        try:
            from .acl_bootstrap import bootstrap_automazioni_acl_endpoints

            bootstrap_automazioni_acl_endpoints()
        except Exception:
            return
