from django.urls import path
from django.views.generic import RedirectView

from . import htmx_views, views


urlpatterns = [
    path("assenze/calendario/partial/", htmx_views.calendario_month_partial, name="assenze_calendario_partial"),
    path("assenze/", views.menu, name="assenze_menu"),
    path("assenze/richiesta_assenze", views.richiesta_assenze, name="assenze_richiesta"),
    path("assenze/impostazioni/", views.gestione_assenze, name="assenze_gestione"),
    path("assenze/gestione_assenze", RedirectView.as_view(pattern_name="assenze_gestione", permanent=False)),
    path("assenze/calendario", views.calendario, name="assenze_calendario"),
    path("assenze/api/eventi", views.api_eventi, name="assenze_api_eventi"),
    path("assenze/api/eventi/colors", views.api_eventi_colors, name="assenze_api_eventi_colors"),
    path("assenze/api/eventi/update", views.api_evento_update, name="assenze_api_evento_update_static"),
    path("assenze/api/eventi/delete", views.api_evento_delete, name="assenze_api_evento_delete_static"),
    path("assenze/api/eventi/<int:item_id>/update", views.api_evento_update, name="assenze_api_evento_update"),
    path("assenze/api/eventi/<int:item_id>/delete", views.api_evento_delete, name="assenze_api_evento_delete"),
    path("assenze/api/check-corsi", views.api_check_corsi, name="assenze_api_check_corsi"),
    path("assenze/api/dipendente-capo", views.api_dipendente_default_capo, name="assenze_api_dipendente_capo"),
    path("assenze/api/sync/push", views.api_sync_push, name="assenze_api_sync_push"),
    path("assenze/api/sync/pull", views.api_sync_pull, name="assenze_api_sync_pull"),
    path("assenze/invio", views.invio_placeholder, name="assenze_invio"),
    path("assenze/aggiorna_consenso/<int:item_id>", views.aggiorna_consenso_placeholder, name="assenze_aggiorna_consenso"),
    path("assenze/car/dashboard", views.car_dashboard, name="assenze_car_dashboard"),
    path("assenze/api/car/consenso/<int:item_id>", views.api_car_aggiorna_consenso, name="assenze_api_car_consenso"),
    path("assenze/api/mia/<int:item_id>/update", views.api_mia_assenza_update, name="assenze_api_mia_update"),
    path("assenze/car/export-csv", views.export_assenze_car_csv, name="assenze_car_export_csv"),
    path("assenze/export-csv", views.export_gestione_assenze_csv, name="assenze_export_csv"),
    path("assenze/gestione-admin/", views.gestione_admin, name="assenze_gestione_admin"),
    path("assenze/certificazione-presenza/", views.certificazione_presenza, name="assenze_certifica_presenza"),
]
