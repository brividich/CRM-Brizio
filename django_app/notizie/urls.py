from __future__ import annotations

from django.urls import path

from . import views

# Queste URL sono montate su /notizie/ in config/urls.py.
# Le route relative non hanno il prefisso /notizie/.
urlpatterns = [
    path("", views.lista, name="notizie_lista"),
    path("dashboard/", views.dashboard, name="notizie_dashboard"),
    path("dashboard/nuova/", views.dashboard_create, name="notizie_dashboard_create"),
    path("dashboard/<int:notizia_id>/modifica/", views.dashboard_edit, name="notizie_dashboard_edit"),
    path("dashboard/<int:notizia_id>/pubblica/", views.dashboard_publish, name="notizie_dashboard_publish"),
    path("dashboard/<int:notizia_id>/archivia/", views.dashboard_archive, name="notizie_dashboard_archive"),
    path("gestione/", views.gestione_admin, name="notizie_gestione_admin"),
    path("obbligatorie/", views.obbligatorie, name="notizie_obbligatorie"),
    path("report/", views.report, name="notizie_report"),
    path("report/export-csv/", views.report_csv, name="notizie_report_csv"),
    path("<int:notizia_id>/", views.dettaglio, name="notizie_dettaglio"),
    path("<int:notizia_id>/conferma/", views.conferma, name="notizie_conferma"),
]
