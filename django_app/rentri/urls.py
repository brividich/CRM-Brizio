from django.urls import path

from . import views

urlpatterns = [
    path("rentri/", views.menu, name="rentri_menu"),
    path("rentri/carico/", views.carico, name="rentri_carico"),
    path("rentri/scarico-originale/", views.scarico_originale, name="rentri_scarico_originale"),
    path("rentri/scarico-effettivo/", views.scarico_effettivo, name="rentri_scarico_effettivo"),
    path("rentri/rettifica-scarico/", views.rettifica_scarico, name="rentri_rettifica_scarico"),
    path("rentri/elenco/", views.elenco, name="rentri_elenco"),
    path("rentri/scadenzario/", views.scadenzario, name="rentri_scadenzario"),
    path("rentri/giacenze/", views.giacenze, name="rentri_giacenze"),
    path("rentri/verifica/", views.verifica, name="rentri_verifica"),
    path("rentri/scadenzario/consolida-bozze/", views.consolida_bozze_view, name="rentri_consolida_bozze"),
    path("rentri/import/preview/", views.import_preview, name="rentri_import_preview"),
    path("rentri/import/confirm/", views.import_confirm, name="rentri_import_confirm"),
    path("rentri/export/pdf/", views.export_pdf, name="rentri_export_pdf"),
    path("rentri/<int:pk>/", views.dettaglio, name="rentri_dettaglio"),
    path("rentri/<int:pk>/modifica/", views.modifica, name="rentri_modifica"),
    path("rentri/<int:pk>/consolida/", views.consolida_view, name="rentri_consolida"),
    path("rentri/<int:pk>/trasmesso/", views.trasmesso_view, name="rentri_trasmesso"),
    path("rentri/<int:pk>/annulla/", views.annulla_view, name="rentri_annulla"),
    path("rentri/<int:pk>/elimina/", views.elimina, name="rentri_elimina"),
    path("rentri/api/sync/pull", views.api_sync_pull, name="rentri_api_sync_pull"),
    path("rentri/api/codici/", views.api_codici_cer, name="rentri_api_codici"),
    path("rentri/api/candidati-rif-op/", views.api_candidati_rif_op, name="rentri_api_candidati_rif_op"),
    path("rentri/impostazioni/", views.impostazioni, name="rentri_impostazioni"),
]
