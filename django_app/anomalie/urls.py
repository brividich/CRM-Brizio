from django.urls import path

from . import views


urlpatterns = [
    path("gestione-anomalie", views.gestione_anomalie_page, name="gestione_anomalie_page"),
    path("gestione-anomalie/nuova-segnalazione", views.apertura_segnalazione_page, name="apertura_segnalazione"),
    path("gestione-anomalie/configurazione", views.anomalie_configurazione_page, name="anomalie_configurazione_page"),
    path("gestione-anomalie/apertura", views.legacy_apertura_redirect, name="legacy_gestione_anomalie_apertura"),
    path(
        "gestione-anomalie/apertura/anomalie",
        views.legacy_apertura_anomalie_redirect,
        name="legacy_gestione_anomalie_apertura_anomalie",
    ),
    path("api/anomalie/db/ordini", views.api_db_ordini, name="api_anomalie_db_ordini"),
    path("api/anomalie/db/ordini/crea", views.api_db_ordini_crea, name="api_anomalie_db_ordini_crea"),
    path("api/anomalie/config/liste", views.api_anomalie_config_liste, name="api_anomalie_config_liste"),
    path("api/anomalie/db/anomalie", views.api_db_anomalie, name="api_anomalie_db_anomalie"),
    path("api/anomalie/ordini", views.api_ordini, name="api_anomalie_ordini"),
    path("api/anomalie/anomalie", views.api_anomalie, name="api_anomalie_anomalie"),
    path("api/anomalie/allegati", views.api_anomalie_allegati, name="api_anomalie_allegati"),
    path("api/anomalie/allegati/upload", views.api_anomalie_allegati_upload, name="api_anomalie_allegati_upload"),
    path("api/anomalie/allegati/delete", views.api_anomalie_allegati_delete, name="api_anomalie_allegati_delete"),
    path("api/anomalie/allegati/file", views.api_anomalie_allegati_file, name="api_anomalie_allegati_file"),
    path("api/anomalie/campi", views.api_campi, name="api_anomalie_campi"),
    path("api/anomalie/salva", views.api_salva, name="api_anomalie_salva"),
    path("api/anomalie/sync", views.api_sync, name="api_anomalie_sync"),
    path("export-csv", views.export_anomalie_csv, name="anomalie_export_csv"),
]
