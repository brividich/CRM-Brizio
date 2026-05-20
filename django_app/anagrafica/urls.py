from django.urls import path

from . import views

app_name = "anagrafica"

urlpatterns = [
    # Dashboard
    path("", views.index, name="index"),

    # Dipendenti (sola lettura)
    path("dipendenti/", views.dipendenti_list, name="dipendenti_list"),

    # NOTE: i fornitori sono ora gestiti dal modulo dedicato `fornitori`
    # (URL prefix /fornitori/). Vedere `fornitori/urls.py`.

    # Crea nuovo dipendente
    path("dipendenti/nuovo/", views.dipendente_create, name="dipendente_create"),

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
    # Reparto dipendente (aggiorna campo legacy)
    path("dipendenti/<int:legacy_id>/reparto/set", views.dipendente_reparto_set, name="dipendente_reparto_set"),

    # Qualifiche dipendente
    path("dipendenti/<int:legacy_id>/qualifiche/add", views.dipendente_qualifica_add, name="dipendente_qualifica_add"),
    path("dipendenti/<int:legacy_id>/qualifiche/<int:q_id>/delete", views.dipendente_qualifica_delete, name="dipendente_qualifica_delete"),

    # Anagrafica civile e aziendale
    path("dipendenti/<int:legacy_id>/anagrafica-civile/salva/", views.dipendente_anagrafica_civile_save, name="dipendente_civile_save"),
    path("dipendenti/<int:legacy_id>/anagrafica-aziendale/salva/", views.dipendente_anagrafica_aziendale_save, name="dipendente_aziendale_save"),

    # Report dipendenti
    path("dipendenti/report/", views.dipendenti_report, name="dipendenti_report"),

    # Mansioni catalogo
    path("mansioni/", views.mansioni_list, name="mansioni_list"),
    path("mansioni/nuovo", views.mansione_create, name="mansione_create"),
    path("mansioni/<int:mansione_id>/modifica", views.mansione_edit, name="mansione_edit"),
    path("mansioni/<int:mansione_id>/elimina", views.mansione_delete, name="mansione_delete"),

    # Aree aziendali catalogo
    path("aree/", views.aree_list, name="aree_list"),
    path("aree/nuovo", views.area_create, name="area_create"),
    path("aree/<int:area_id>/modifica", views.area_edit, name="area_edit"),
    path("aree/<int:area_id>/elimina", views.area_delete, name="area_delete"),

    # Ruoli aziendali catalogo
    path("ruoli-aziendali/", views.ruoli_aziendali_list, name="ruoli_aziendali_list"),
    path("ruoli-aziendali/nuovo", views.ruolo_aziendale_create, name="ruolo_aziendale_create"),
    path("ruoli-aziendali/<int:ruolo_id>/modifica", views.ruolo_aziendale_edit, name="ruolo_aziendale_edit"),
    path("ruoli-aziendali/<int:ruolo_id>/elimina", views.ruolo_aziendale_delete, name="ruolo_aziendale_delete"),

    # Qualifiche catalogo + scadenze
    path("qualifiche/", views.qualifiche_list, name="qualifiche_list"),
    path("qualifiche/nuovo", views.tipo_qualifica_create, name="tipo_qualifica_create"),
    path("qualifiche/<int:tipo_id>/modifica", views.tipo_qualifica_edit, name="tipo_qualifica_edit"),
    path("qualifiche/<int:tipo_id>/elimina", views.tipo_qualifica_delete, name="tipo_qualifica_delete"),

    # Voci retributive — importazione CSV e storico dipendente
    path("retribuzioni/", views.retribuzioni_import, name="retribuzioni_import"),
    path("dipendenti/<int:legacy_id>/retribuzioni/", views.dipendente_retribuzioni, name="dipendente_retribuzioni"),
    # Voci retributive — data-entry manuale (HR/admin)
    path("dipendenti/<int:legacy_id>/retribuzioni/voci/add",
         views.dipendente_retribuzione_voce_add, name="dipendente_retribuzione_voce_add"),
    path("dipendenti/<int:legacy_id>/retribuzioni/voci/<int:voce_id>/edit",
         views.dipendente_retribuzione_voce_edit, name="dipendente_retribuzione_voce_edit"),
    path("dipendenti/<int:legacy_id>/retribuzioni/voci/<int:voce_id>/delete",
         views.dipendente_retribuzione_voce_delete, name="dipendente_retribuzione_voce_delete"),

    # Storico contrattuale — importazione CSV e CRUD manuale
    path("contratti/", views.contratti_import, name="contratti_import"),
    path("dipendenti/<int:legacy_id>/contratti/add", views.dipendente_contratto_add, name="dipendente_contratto_add"),
    path("dipendenti/<int:legacy_id>/contratti/<int:contratto_id>/edit", views.dipendente_contratto_edit, name="dipendente_contratto_edit"),
    path("dipendenti/<int:legacy_id>/contratti/<int:contratto_id>/delete", views.dipendente_contratto_delete, name="dipendente_contratto_delete"),

    # Pannello impostazioni — catalogo cataloghi e permessi del modulo anagrafica
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("impostazioni/permessi/salva", views.impostazioni_permessi_save, name="impostazioni_permessi_save"),

    # Livelli contrattuali — catalogo
    path("livelli/nuovo", views.livello_contrattuale_create, name="livello_contrattuale_create"),
    path("livelli/<int:livello_id>/modifica", views.livello_contrattuale_edit, name="livello_contrattuale_edit"),
    path("livelli/<int:livello_id>/elimina", views.livello_contrattuale_delete, name="livello_contrattuale_delete"),

    # Tipologie contratto — catalogo
    path("tipologie-contratto/nuovo", views.tipologia_contratto_create, name="tipologia_contratto_create"),
    path("tipologie-contratto/<int:tipologia_id>/modifica", views.tipologia_contratto_edit, name="tipologia_contratto_edit"),
    path("tipologie-contratto/<int:tipologia_id>/elimina", views.tipologia_contratto_delete, name="tipologia_contratto_delete"),
]
