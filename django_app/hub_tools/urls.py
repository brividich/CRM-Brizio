from django.urls import path

from . import views

urlpatterns = [
    path("moduli/", views.moduli, name="hub_moduli"),
    path("moduli/toggle/", views.api_toggle_module, name="hub_moduli_toggle"),
    path("database/", views.database, name="hub_database"),
    path("database/api/stats/", views.api_db_stats, name="hub_db_stats"),
    path("database/api/backup/", views.api_db_backup, name="hub_db_backup"),
    path("database/api/cleanup/", views.api_db_cleanup, name="hub_db_cleanup"),
    path("database/api/optimize/", views.api_db_optimize, name="hub_db_optimize"),
    path("database/api/restore/", views.api_db_restore, name="hub_db_restore"),
]
