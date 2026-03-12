from django.urls import path

from . import views


app_name = "timbri"

urlpatterns = [
    path("timbri/", views.index, name="index"),
    path("timbri/operatori/nuovo/", views.operatore_create, name="operatore_create"),
    path("timbri/operatori/<int:operatore_id>/elimina/", views.operatore_delete, name="operatore_delete"),
    path("timbri/operatori/<int:operatore_id>/", views.operatore_detail, name="operatore_detail"),
    path("timbri/anagrafica/<int:legacy_id>/", views.operatore_detail_by_legacy, name="operatore_detail_by_legacy"),
    path("timbri/operatori/<int:operatore_id>/nuovo/", views.registro_create, name="registro_create"),
    path("timbri/anagrafica/<int:legacy_id>/nuovo/", views.registro_create_by_legacy, name="registro_create_by_legacy"),
    path("timbri/record/<int:record_id>/modifica/", views.registro_edit, name="registro_edit"),
    path("timbri/configurazione/", views.configurazione_page, name="configurazione"),
    path("timbri/export-csv", views.export_csv, name="export_csv"),
]
