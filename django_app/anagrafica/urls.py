from django.urls import path

from . import views

app_name = "anagrafica"

urlpatterns = [
    # Dashboard
    path("", views.index, name="index"),

    # Dipendenti (sola lettura)
    path("dipendenti/", views.dipendenti_list, name="dipendenti_list"),

    # Fornitori
    path("fornitori/", views.fornitori_list, name="fornitori_list"),
    path("fornitori/nuovo/", views.fornitore_create, name="fornitore_create"),
    path("fornitori/<int:fornitore_id>/", views.fornitore_detail, name="fornitore_detail"),
    path("fornitori/<int:fornitore_id>/modifica/", views.fornitore_edit, name="fornitore_edit"),
    path("fornitori/<int:fornitore_id>/toggle-active", views.fornitore_toggle_active, name="fornitore_toggle_active"),

    # Documenti
    path("fornitori/<int:fornitore_id>/documenti/add", views.fornitore_documento_add, name="fornitore_documento_add"),
    path("fornitori/<int:fornitore_id>/documenti/<int:doc_id>/delete", views.fornitore_documento_delete, name="fornitore_documento_delete"),

    # Ordini
    path("fornitori/<int:fornitore_id>/ordini/add", views.fornitore_ordine_add, name="fornitore_ordine_add"),
    path("fornitori/<int:fornitore_id>/ordini/<int:ordine_id>/stato", views.fornitore_ordine_stato, name="fornitore_ordine_stato"),

    # Valutazioni
    path("fornitori/<int:fornitore_id>/valutazioni/add", views.fornitore_valutazione_add, name="fornitore_valutazione_add"),
    path("fornitori/<int:fornitore_id>/valutazioni/<int:val_id>/delete", views.fornitore_valutazione_delete, name="fornitore_valutazione_delete"),

    # Asset assegnati
    path("fornitori/<int:fornitore_id>/asset/add", views.fornitore_asset_add, name="fornitore_asset_add"),
    path("fornitori/<int:fornitore_id>/asset/<int:fa_id>/remove", views.fornitore_asset_remove, name="fornitore_asset_remove"),
]
