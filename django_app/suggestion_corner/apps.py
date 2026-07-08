from django.apps import AppConfig


class SuggestionCornerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "suggestion_corner"
    verbose_name = "Suggestion Corner"

    def ready(self):
        """Collega il signal post_transition (audit FSM) importando il
        modulo state_machine. Fail-safe."""
        try:
            from . import state_machine  # noqa: F401  (registra il signal audit)
        except Exception:
            pass
