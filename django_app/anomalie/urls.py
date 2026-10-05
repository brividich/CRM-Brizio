from django.urls import path

from . import views
from . import mail_action_views
from . import nc_views


urlpatterns = [
    path("gestione-anomalie/mail-action/<str:token>/", mail_action_views.mail_action_view, name="anomalie_mail_action"),
    path("gestione-anomalie/mail-action/<str:token>/fatto/", mail_action_views.mail_action_done_view, name="anomalie_mail_action_done"),
    path("gestione-anomalie", views.gestione_anomalie_page, name="gestione_anomalie_page"),
    path("gestione-anomalie/nuova-segnalazione", views.apertura_segnalazione_page, name="apertura_segnalazione"),
    path("gestione-anomalie/configurazione", views.anomalie_configurazione_page, name="anomalie_configurazione_page"),
    # Non conformita' per OP (ISO 9001 §10.2): sotto /gestione-anomalie per ereditare il gate ACL.
    path("gestione-anomalie/nc/", nc_views.nc_lista, name="anomalie_nc_lista"),
    path("gestione-anomalie/nc/<int:pk>/", nc_views.nc_dettaglio, name="anomalie_nc_dettaglio"),
    path("gestione-anomalie/nc/<int:pk>/copilota/", nc_views.nc_copilota, name="anomalie_nc_copilota"),
    path("gestione-anomalie/nc/<int:pk>/pdf/", nc_views.nc_pdf, name="anomalie_nc_pdf"),
    path("gestione-anomalie/nc/<int:pk>/allegati/<int:allegato_id>/", nc_views.nc_allegato, name="anomalie_nc_allegato"),
    path("gestione-anomalie/apertura", views.legacy_apertura_redirect, name="legacy_gestione_anomalie_apertura"),
    path(
        "gestione-anomalie/apertura/anomalie",
        views.legacy_apertura_anomalie_redirect,
        name="legacy_gestione_anomalie_apertura_anomalie",
    ),
    path("api/anomalie/db/ordini", views.api_db_ordini, name="api_anomalie_db_ordini"),
    path("api/anomalie/db/ordini/crea", views.api_db_ordini_crea, name="api_anomalie_db_ordini_crea"),
    path("api/anomalie/config/liste", views.api_anomalie_config_liste, name="api_anomalie_config_liste"),
    path("api/anomalie/config/logo", views.api_anomalie_config_logo, name="api_anomalie_config_logo"),
    path("api/anomalie/config/logo/reset", views.api_anomalie_config_logo_reset, name="api_anomalie_config_logo_reset"),
    path("api/anomalie/db/anomalie", views.api_db_anomalie, name="api_anomalie_db_anomalie"),
    path("api/anomalie/ordini", views.api_ordini, name="api_anomalie_ordini"),
    path("api/anomalie/anomalie", views.api_anomalie, name="api_anomalie_anomalie"),
    path("api/anomalie/allegati", views.api_anomalie_allegati, name="api_anomalie_allegati"),
    path("api/anomalie/allegati/upload", views.api_anomalie_allegati_upload, name="api_anomalie_allegati_upload"),
    path("api/anomalie/descrizione-allegati/upload", views.api_anomalie_descrizione_allegati_upload, name="api_anomalie_descrizione_allegati_upload"),
    path("api/anomalie/allegati/delete", views.api_anomalie_allegati_delete, name="api_anomalie_allegati_delete"),
    path("api/anomalie/allegati/file", views.api_anomalie_allegati_file, name="api_anomalie_allegati_file"),
    path("api/anomalie/campi", views.api_campi, name="api_anomalie_campi"),
    path("api/anomalie/salva", views.api_salva, name="api_anomalie_salva"),
    path("api/anomalie/notifica-op", views.api_notifica_op, name="api_anomalie_notifica_op"),
    path("api/anomalie/seriali-op", views.api_seriali_op, name="api_anomalie_seriali_op"),
    path("api/anomalie/timeline", views.api_anomalie_timeline, name="api_anomalie_timeline"),
    path("api/anomalie/sync", views.api_sync, name="api_anomalie_sync"),
    path("api/anomalie/copilota", views.api_copilota_anomalia, name="api_anomalie_copilota"),
    path("api/anomalie/qualita", views.api_anomalie_qualita, name="api_anomalie_qualita"),
    path("api/anomalie/qualita/copilota", views.api_anomalie_qualita_copilota, name="api_anomalie_qualita_copilota"),
    path("export-csv", views.export_anomalie_csv, name="anomalie_export_csv"),
    # Statistiche e estrazioni
    path("gestione-anomalie/statistiche", views.anomalie_statistiche_page, name="anomalie_statistiche_page"),
    path("api/anomalie/statistiche", views.api_anomalie_statistiche, name="api_anomalie_statistiche"),
    path("api/anomalie/ricerca", views.api_anomalie_ricerca, name="api_anomalie_ricerca"),
    path("api/anomalie/export-csv-filtrato", views.export_anomalie_csv_filtrato, name="anomalie_export_csv_filtrato"),
    # Report riepilogativo OP
    path("api/anomalie/report", views.report_segnalazione_html, name="anomalie_report_segnalazione"),
    # Config template report
    path("api/anomalie/config/report-template", views.api_anomalie_config_report_template, name="api_anomalie_config_report_template"),
]
