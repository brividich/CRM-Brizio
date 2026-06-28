from __future__ import annotations

from django.urls import path

from . import views

app_name = "dpi"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("nuova/", views.nuova_richiesta, name="nuova"),
    path("storico/", views.storico, name="storico"),
    path("report-conformita/", views.report_conformita, name="report_conformita"),
    path("<int:pk>/", views.richiesta_detail, name="detail"),
    path("<int:pk>/annulla/", views.annulla_richiesta, name="annulla"),
    path("gestione/", views.gestione_list, name="gestione_list"),
    path("gestione/<int:pk>/", views.gestione_detail, name="gestione_detail"),
    path("gestione/<int:pk>/approva/", views.approva_richiesta, name="approva"),
    path("gestione/<int:pk>/rifiuta/", views.rifiuta_richiesta, name="rifiuta"),
    path("gestione/<int:pk>/consegna/", views.consegna_richiesta, name="consegna"),
    path("gestione/<int:pk>/commento/", views.aggiungi_commento, name="commento"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("impostazioni/categorie/nuova/", views.categoria_edit, name="categoria_nuova"),
    path("impostazioni/categorie/<int:pk>/modifica/", views.categoria_edit, name="categoria_modifica"),
    path("impostazioni/categorie/<int:pk>/elimina/", views.categoria_elimina, name="categoria_elimina"),
    path("impostazioni/tipi/nuovo/", views.tipo_edit, name="tipo_nuovo"),
    path("impostazioni/tipi/<int:pk>/modifica/", views.tipo_edit, name="tipo_modifica"),
    path("impostazioni/modelli/nuovo/", views.modello_edit, name="modello_nuovo"),
    path("impostazioni/modelli/<int:pk>/modifica/", views.modello_edit, name="modello_modifica"),
    path("impostazioni/taglie/nuova/", views.taglia_edit, name="taglia_nuova"),
    path("impostazioni/taglie/<int:pk>/modifica/", views.taglia_edit, name="taglia_modifica"),
    path("api/categorie/", views.api_categorie, name="api_categorie"),
    path("api/copilota-dpi/", views.api_copilota_dpi, name="api_copilota_dpi"),
]
