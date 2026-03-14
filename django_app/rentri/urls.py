from django.urls import path

from . import views

urlpatterns = [
    path("rentri/", views.menu, name="rentri_menu"),
    path("rentri/carico/", views.carico, name="rentri_carico"),
    path("rentri/scarico-originale/", views.scarico_originale, name="rentri_scarico_originale"),
    path("rentri/scarico-effettivo/", views.scarico_effettivo, name="rentri_scarico_effettivo"),
    path("rentri/rettifica-scarico/", views.rettifica_scarico, name="rentri_rettifica_scarico"),
    path("rentri/elenco/", views.elenco, name="rentri_elenco"),
    path("rentri/<int:pk>/modifica/", views.modifica, name="rentri_modifica"),
    path("rentri/<int:pk>/elimina/", views.elimina, name="rentri_elimina"),
    path("rentri/api/sync/pull", views.api_sync_pull, name="rentri_api_sync_pull"),
]
