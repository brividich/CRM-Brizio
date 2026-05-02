from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tasks"
    verbose_name = "KICK-OFF"

    def ready(self):
        from core.acl_bootstrap_base import should_skip_runtime_bootstrap

        if should_skip_runtime_bootstrap():
            return

        try:
            from .acl_bootstrap import bootstrap_tasks_acl_endpoints

            bootstrap_tasks_acl_endpoints()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Bootstrap ACL tasks saltato o fallito: %s",
                exc,
            )
