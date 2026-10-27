from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tickets"
    verbose_name = "Ticket"

    def ready(self):
        from .sharepoint_man import collega_segnali

        collega_segnali()
        try:
            from .acl_bootstrap import bootstrap_tickets_acl_endpoints

            bootstrap_tickets_acl_endpoints()
        except Exception:
            return
