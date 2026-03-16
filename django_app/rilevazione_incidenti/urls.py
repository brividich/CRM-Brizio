from django.urls import path

from . import views

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuovo/", views.nuovo, name="nuovo"),
    path("statistiche/", views.statistiche, name="statistiche"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("export-csv/", views.export_csv, name="export_csv"),
    path("<str:sp_id>/", views.dettaglio, name="dettaglio"),
    path("<str:sp_id>/modifica/", views.modifica, name="modifica"),
    path("<str:sp_id>/elimina/", views.elimina, name="elimina"),
]
