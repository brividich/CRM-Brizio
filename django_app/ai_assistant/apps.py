from django.apps import AppConfig


class AiAssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_assistant"
    verbose_name = "Assistente AI"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_ai_assistant_acl_endpoints

            bootstrap_ai_assistant_acl_endpoints()
        except Exception:  # pragma: no cover - il boot non deve mai fallire per l'ACL
            pass
