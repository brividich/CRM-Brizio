from django.apps import AppConfig


class GestioneCarichiMacchinaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gestione_carichi_macchina"
    verbose_name = "Gestione Carichi Macchina"

    # NOTA: il bootstrap ACL v2 + voce di menu (NavigationItem/NavigationRoleAccess)
    # verra' aggiunto al PASSO 6 tramite un modulo acl_bootstrap.py richiamato qui in
    # ready(), come fanno automazioni/timbri. Per ora l'app espone solo il modello dati.
