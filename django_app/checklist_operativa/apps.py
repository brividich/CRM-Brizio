from django.apps import AppConfig


class ChecklistOperativaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "checklist_operativa"
    verbose_name = "Checklist Operativa - Chiusure Aziendali"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_checklist_operativa_acl_endpoints

            bootstrap_checklist_operativa_acl_endpoints()
        except Exception:
            return
