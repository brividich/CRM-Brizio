from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security"

    def ready(self):
        # Barra di stato e badge del menu: cache di 60 s, svuotata appena cambia
        # un alert, un ticket o un incidente (chiuso un alert, il numero scende subito).
        from django.db.models.signals import post_delete, post_save

        from .models import SecurityAlert, SecurityIncident, SecurityRemediationTicket
        from .services.live_status import invalida

        for modello in (SecurityAlert, SecurityRemediationTicket, SecurityIncident):
            post_save.connect(invalida, sender=modello, dispatch_uid=f"soc_live_status_save_{modello.__name__}")
            post_delete.connect(invalida, sender=modello, dispatch_uid=f"soc_live_status_del_{modello.__name__}")
        # Impostazioni del SOC lette da una copia in memoria (configuration._impostazioni): un salvataggio la svuota.
        from .models import SecurityCenterSetting
        from .services.configuration import invalida_impostazioni

        post_save.connect(invalida_impostazioni, sender=SecurityCenterSetting, dispatch_uid="soc_impostazioni_save")
        post_delete.connect(invalida_impostazioni, sender=SecurityCenterSetting, dispatch_uid="soc_impostazioni_del")
