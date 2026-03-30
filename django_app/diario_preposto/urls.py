from django.urls import path

from . import views

app_name = "diario_preposto"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuovo/", views.nuovo, name="nuovo"),
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
    path("<int:pk>/modifica/", views.modifica, name="modifica"),
    path("<int:pk>/elimina/", views.elimina, name="elimina"),
    path("<int:pk>/export-pdf/", views.export_pdf, name="export_pdf"),
    path("api/allegato/upload/", views.api_allegato_upload, name="api_allegato_upload"),
    path("api/allegato/delete/", views.api_allegato_delete, name="api_allegato_delete"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
]
