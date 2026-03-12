from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tasks"
    verbose_name = "Task"

    def ready(self):
        try:
            from .acl_bootstrap import bootstrap_tasks_acl_endpoints

            bootstrap_tasks_acl_endpoints()
        except Exception:
            return
