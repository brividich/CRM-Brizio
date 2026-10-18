from .views import (
    api_acl_v2_role_grant_toggle,
    api_permessi_bulk,
    api_permessi_toggle,
    api_pulsanti_create,
    api_pulsanti_delete,
    api_pulsanti_update,
)

# Re-export: ``admin_portale.urls`` monta queste view come ``api.<nome>``.
__all__ = [
    "api_acl_v2_role_grant_toggle",
    "api_permessi_bulk",
    "api_permessi_toggle",
    "api_pulsanti_create",
    "api_pulsanti_delete",
    "api_pulsanti_update",
]
