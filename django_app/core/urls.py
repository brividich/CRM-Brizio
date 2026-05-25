from django.urls import path

from . import legacy_flask_views
from . import views
from .accounts.views import LegacyLoginView, cambia_password, logout_view
from .accounts.windows_sso import windows_sso_view


urlpatterns = [
    path("check", legacy_flask_views.legacy_flask_check, name="legacy_flask_check"),
    path("admin", legacy_flask_views.legacy_admin_entry, name="legacy_admin_entry"),
    path("admin/<path:legacy_path>", legacy_flask_views.legacy_admin_dispatch, name="legacy_admin_dispatch"),
    path(
        "modifica_capo",
        legacy_flask_views.legacy_root_removed,
        {"endpoint": "modifica_capo"},
        name="legacy_modifica_capo",
    ),
    path(
        "modifica_info_completa",
        legacy_flask_views.legacy_root_removed,
        {"endpoint": "modifica_info_completa"},
        name="legacy_modifica_info_completa",
    ),
    path(
        "gestione_utenti/modifica/<int:user_id>",
        legacy_flask_views.legacy_root_removed,
        {"endpoint": "gestione_utenti/modifica/<id>"},
        name="legacy_gestione_utenti_modifica",
    ),
    path("health", views.health, name="health"),
    path("version", views.version, name="version"),
    path("", views.root_redirect_to_dashboard, name="root"),
    path("assenze/", views.coming_assenze, name="coming_assenze"),
    path("anomalie/", views.coming_anomalie, name="coming_anomalie"),
    path("coming/admin-portale/", views.coming_admin, name="coming_admin"),
    path("login/", LegacyLoginView.as_view(), name="login"),
    path("login/windows/", windows_sso_view, name="windows_sso"),
    path("logout", logout_view, name="logout_legacy_noslash"),
    path("logout/", logout_view, name="logout"),
    path("impersonation/stop/", views.stop_impersonation, name="stop_impersonation"),
    path("cambia-password", cambia_password, name="cambia_password_legacy_noslash"),
    path("cambia-password/", cambia_password, name="cambia_password"),
    path("profilo/", views.profilo, name="profilo"),
    path("gestione-reparto/", views.gestione_reparto, name="gestione_reparto"),
    path("rubrica/", views.rubrica, name="rubrica"),
    path("organigramma/", views.organigramma, name="organigramma"),
    path("notifiche/", views.notifiche, name="notifiche"),
    path("api/notifiche/<int:notifica_id>/leggi", views.api_notifica_leggi, name="api_notifica_leggi"),
    path("api/notifiche/panel/", views.api_notifiche_panel, name="api_notifiche_panel"),
    path("api/notifiche/mark-all-read/", views.api_notifiche_mark_all_read, name="api_notifiche_mark_all_read"),
    path("api/notifiche/popup-ack/", views.api_notifiche_popup_ack, name="api_notifiche_popup_ack"),
    path(
        "api/gestione-reparto/<int:user_id>/assegna",
        views.api_gestione_reparto_assegna,
        name="api_gestione_reparto_assegna",
    ),
    path("preferenze/", views.ui_prefs_page, name="ui_prefs_page"),
    path("preferenze/api/ui/", views.api_ui_prefs_save, name="ui_prefs_api_save"),
    path("preferenze/api/sidebar/", views.sidebar_toggle_save, name="ui_sidebar_save"),
    path("onboarding/", views.onboarding_wizard, name="onboarding_wizard"),
    path("api/onboarding/email/", views.api_onboarding_email_save, name="api_onboarding_email_save"),
    path("api/onboarding/<int:user_id>/reset", views.api_onboarding_reset, name="api_onboarding_reset"),
    path("api/search/", views.api_global_search, name="api_global_search"),
    path("api/table-prefs/<str:table_id>/", views.api_table_prefs, name="api_table_prefs"),
]
