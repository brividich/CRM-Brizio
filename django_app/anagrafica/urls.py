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

    # Scheda dettaglio dipendente
    path("dipendenti/<int:legacy_id>/", views.dipendente_detail, name="dipendente_detail"),
    path("dipendenti/<int:legacy_id>/ruoli/assegna", views.dipendente_ruolo_assegna, name="dipendente_ruolo_assegna"),
    path("dipendenti/<int:legacy_id>/ruoli/<int:assegnazione_id>/rimuovi", views.dipendente_ruolo_rimuovi, name="dipendente_ruolo_rimuovi"),

    # API widget layout
    path("api/widget-layout/", views.api_dipendente_widget_layout, name="api_dipendente_widget_layout"),

    # Ruoli operativi catalogo
    path("ruoli-operativi/", views.ruoli_operativi_list, name="ruoli_operativi_list"),
    path("ruoli-operativi/nuovo", views.ruolo_operativo_create, name="ruolo_operativo_create"),
    path("ruoli-operativi/<int:ruolo_id>/modifica", views.ruolo_operativo_edit, name="ruolo_operativo_edit"),
    path("ruoli-operativi/<int:ruolo_id>/elimina", views.ruolo_operativo_delete, name="ruolo_operativo_delete"),

    # Impostazioni permessi widget
    path("impostazioni-widget/", views.widget_permissions, name="widget_permissions"),

    # Mansione dipendente (aggiorna campo legacy)
    path("dipendenti/<int:legacy_id>/mansione/set", views.dipendente_mansione_set, name="dipendente_mansione_set"),

    # Qualifiche dipendente
    path("dipendenti/<int:legacy_id>/qualifiche/add", views.dipendente_qualifica_add, name="dipendente_qualifica_add"),
    path("dipendenti/<int:legacy_id>/qualifiche/<int:q_id>/delete", views.dipendente_qualifica_delete, name="dipendente_qualifica_delete"),

    # Mansioni catalogo
    path("mansioni/", views.mansioni_list, name="mansioni_list"),
    path("mansioni/nuovo", views.mansione_create, name="mansione_create"),
    path("mansioni/<int:mansione_id>/modifica", views.mansione_edit, name="mansione_edit"),
    path("mansioni/<int:mansione_id>/elimina", views.mansione_delete, name="mansione_delete"),

    # Qualifiche catalogo + scadenze
    path("qualifiche/", views.qualifiche_list, name="qualifiche_list"),
    path("qualifiche/nuovo", views.tipo_qualifica_create, name="tipo_qualifica_create"),
    path("qualifiche/<int:tipo_id>/modifica", views.tipo_qualifica_edit, name="tipo_qualifica_edit"),
    path("qualifiche/<int:tipo_id>/elimina", views.tipo_qualifica_delete, name="tipo_qualifica_delete"),
]
