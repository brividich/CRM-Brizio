from django.apps import AppConfig


class AnagraficaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "anagrafica"
    verbose_name = "Anagrafica"

    def ready(self):
        # Scadenze HR ricalcolate a ogni modifica dei dati da cui dipendono.
        from .segnali_scadenze import collega

        collega()
        # Capo e team (regola unica): cache e copia nelle schede sempre allineate.
        from .segnali_capi import collega as collega_capi

        collega_capi()
        # Struttura della Qualità: «Responsabilità del reparto» generata dal reparto.
        from .segnali_struttura import collega as collega_struttura

        collega_struttura()
        try:
            from .acl_bootstrap import bootstrap_anagrafica_acl_endpoints

            bootstrap_anagrafica_acl_endpoints()
        except Exception:
            return
