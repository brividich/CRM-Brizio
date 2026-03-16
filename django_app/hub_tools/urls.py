from django.urls import path

from . import views

urlpatterns = [
    # Moduli
    path("moduli/", views.moduli, name="hub_moduli"),
    path("moduli/toggle/", views.api_toggle_module, name="hub_moduli_toggle"),
    path("moduli/login-redirect/", views.api_set_login_redirect, name="hub_moduli_login_redirect"),
    # Database
    path("database/", views.database, name="hub_database"),
    path("database/api/stats/", views.api_db_stats, name="hub_db_stats"),
    path("database/api/backup/", views.api_db_backup, name="hub_db_backup"),
    path("database/api/cleanup/", views.api_db_cleanup, name="hub_db_cleanup"),
    path("database/api/optimize/", views.api_db_optimize, name="hub_db_optimize"),
    path("database/api/restore/", views.api_db_restore, name="hub_db_restore"),
    # Homepage Builder
    path("homepage-builder/", views.homepage_builder, name="hub_homepage_builder"),
    path("homepage-builder/tool/", views.homepage_builder_tool, name="hub_homepage_builder_tool"),
    # Setup Wizard (riconfigura)
    path("setup-wizard/", views.setup_wizard_hub, name="hub_setup_wizard"),
    path("setup-wizard/api/reconfigure/", views.api_reconfigure, name="hub_api_reconfigure"),
    # Guide e Manuali
    path("guide/", views.guide_list, name="hub_guide_list"),
    path("guide/serve/<str:filename>", views.guide_serve, name="hub_guide_serve"),
    path("guide/<slug:slug>/", views.guide_view, name="hub_guide_view"),
]
