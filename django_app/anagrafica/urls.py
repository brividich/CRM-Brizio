from django.urls import path

from . import views

app_name = "anagrafica"

urlpatterns = [
    # Dashboard
    path("", views.index, name="index"),

    # Dipendenti (sola lettura)
    path("dipendenti/", views.dipendenti_list, name="dipendenti_list"),

    # Ex dipendenti (rapporto cessato) — vista dedicata
    path("ex-dipendenti/", views.ex_dipendenti_list, name="ex_dipendenti_list"),

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
    # Username dipendente (aliasusername)
    path("dipendenti/<int:legacy_id>/username/set", views.dipendente_username_set, name="dipendente_username_set"),
    # Attiva/disattiva dipendente (campo attivo)
    path("dipendenti/<int:legacy_id>/toggle-active", views.dipendente_toggle_active, name="dipendente_toggle_active"),

    # Qualifiche dipendente
    path("dipendenti/<int:legacy_id>/qualifiche/add", views.dipendente_qualifica_add, name="dipendente_qualifica_add"),
    path("dipendenti/<int:legacy_id>/qualifiche/<int:q_id>/delete", views.dipendente_qualifica_delete, name="dipendente_qualifica_delete"),

    # Dashboard globale visite mediche
    path("visite-mediche/", views.visite_mediche_dashboard, name="visite_mediche_dashboard"),
    path("visite-mediche/nuova-sessione/", views.visite_mediche_nuova_sessione, name="visite_mediche_nuova_sessione"),
    path("visite-mediche/export/scadenze.xlsx", views.visite_mediche_export_scadenze, name="visite_mediche_export_scadenze"),
    path("visite-mediche/export/copertura.xlsx", views.visite_mediche_export_copertura, name="visite_mediche_export_copertura"),
    path("visite-mediche/api/cerca-dipendente/", views.visite_mediche_api_cerca_dipendente, name="visite_mediche_api_cerca_dipendente"),

    # Visite mediche dipendente
    path("dipendenti/<int:legacy_id>/visite/add", views.dipendente_visita_add, name="dipendente_visita_add"),
    path("dipendenti/<int:legacy_id>/visite/<int:v_id>/edit", views.dipendente_visita_edit, name="dipendente_visita_edit"),
    path("dipendenti/<int:legacy_id>/visite/<int:v_id>/delete", views.dipendente_visita_delete, name="dipendente_visita_delete"),

    # Documenti dipendente (storage privato)
    path("documenti/", views.documenti_list, name="documenti_list"),
    path("documenti/<int:doc_id>/download", views.documento_dipendente_download, name="documento_download"),
    path("documenti/<int:doc_id>/delete", views.documento_dipendente_delete, name="documento_delete"),
    path("dipendenti/<int:legacy_id>/documenti/upload", views.documento_dipendente_upload, name="documento_upload"),

    # Cartelle documenti — CRUD da impostazioni
    path("cartelle-documenti/nuovo", views.cartella_documento_create, name="cartella_documento_create"),
    path("cartelle-documenti/<int:cartella_id>/modifica", views.cartella_documento_edit, name="cartella_documento_edit"),
    path("cartelle-documenti/<int:cartella_id>/elimina", views.cartella_documento_delete, name="cartella_documento_delete"),

    # Subnav — categorie e link (CRUD da impostazioni)
    path("subnav/categoria/nuovo", views.subnav_categoria_create, name="subnav_categoria_create"),
    path("subnav/categoria/<int:cat_id>/modifica", views.subnav_categoria_edit, name="subnav_categoria_edit"),
    path("subnav/categoria/<int:cat_id>/elimina", views.subnav_categoria_delete, name="subnav_categoria_delete"),
    path("subnav/link/nuovo", views.subnav_link_create, name="subnav_link_create"),
    path("subnav/link/<int:link_id>/modifica", views.subnav_link_edit, name="subnav_link_edit"),
    path("subnav/link/<int:link_id>/elimina", views.subnav_link_delete, name="subnav_link_delete"),

    # HTMX: partial righe DPI iniziali al cambio ruolo nel form di creazione
    path("htmx/dpi-iniziali-righe/", views.dipendente_dpi_iniziali_proposti, name="htmx_dpi_iniziali"),

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
    # Voci retributive — vista globale pivot dipendente+mese × pay_item + export
    path("retribuzioni/globale/", views.retribuzioni_globale, name="retribuzioni_globale"),
    path("retribuzioni/globale/export.xlsx", views.retribuzioni_globale_export, name="retribuzioni_globale_export"),
    path("dipendenti/<int:legacy_id>/retribuzioni/", views.dipendente_retribuzioni, name="dipendente_retribuzioni"),
    path("dipendenti/<int:legacy_id>/retribuzioni/export.xlsx",
         views.dipendente_retribuzioni_export_xlsx, name="dipendente_retribuzioni_export_xlsx"),
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

    # Scadenzario unificato qualifiche + visite mediche
    path("scadenzario/", views.scadenzario, name="scadenzario"),

    # Ratei ferie/ROL/ex-festività — lista aggregata + export
    path("ratei/", views.ratei_list, name="ratei_list"),
    path("ratei/export/", views.ratei_export, name="ratei_export"),

    # Pannello impostazioni — catalogo cataloghi e permessi del modulo anagrafica
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("impostazioni/permessi/salva", views.impostazioni_permessi_save, name="impostazioni_permessi_save"),

    # Tipi visita medica — catalogo impostazioni
    path("tipo-visita-medica/nuovo", views.tipo_visita_medica_create, name="tipo_visita_medica_create"),
    path("tipo-visita-medica/<int:tipo_id>/modifica", views.tipo_visita_medica_edit, name="tipo_visita_medica_edit"),
    path("tipo-visita-medica/<int:tipo_id>/elimina", views.tipo_visita_medica_delete, name="tipo_visita_medica_delete"),

    # Livelli contrattuali — catalogo
    path("livelli/nuovo", views.livello_contrattuale_create, name="livello_contrattuale_create"),
    path("livelli/<int:livello_id>/modifica", views.livello_contrattuale_edit, name="livello_contrattuale_edit"),
    path("livelli/<int:livello_id>/elimina", views.livello_contrattuale_delete, name="livello_contrattuale_delete"),

    # Tipologie contratto — catalogo
    path("tipologie-contratto/nuovo", views.tipologia_contratto_create, name="tipologia_contratto_create"),
    path("tipologie-contratto/<int:tipologia_id>/modifica", views.tipologia_contratto_edit, name="tipologia_contratto_edit"),
    path("tipologie-contratto/<int:tipologia_id>/elimina", views.tipologia_contratto_delete, name="tipologia_contratto_delete"),

    # DPI catalogo — CRUD inline da anagrafica/impostazioni
    path("dpi/categoria/nuovo", views.dpi_categoria_create, name="dpi_categoria_create"),
    path("dpi/categoria/<int:pk>/modifica", views.dpi_categoria_edit, name="dpi_categoria_edit"),
    path("dpi/categoria/<int:pk>/elimina", views.dpi_categoria_delete, name="dpi_categoria_delete"),
    path("dpi/tipo/nuovo", views.dpi_tipo_create, name="dpi_tipo_create"),
    path("dpi/tipo/<int:pk>/modifica", views.dpi_tipo_edit, name="dpi_tipo_edit"),
    path("dpi/tipo/<int:pk>/elimina", views.dpi_tipo_delete, name="dpi_tipo_delete"),
    path("dpi/modello/nuovo", views.dpi_modello_create, name="dpi_modello_create"),
    path("dpi/modello/<int:pk>/modifica", views.dpi_modello_edit, name="dpi_modello_edit"),
    path("dpi/modello/<int:pk>/elimina", views.dpi_modello_delete, name="dpi_modello_delete"),
    path("dpi/taglia/nuovo", views.dpi_taglia_create, name="dpi_taglia_create"),
    path("dpi/taglia/<int:pk>/modifica", views.dpi_taglia_edit, name="dpi_taglia_edit"),
    path("dpi/taglia/<int:pk>/elimina", views.dpi_taglia_delete, name="dpi_taglia_delete"),
]
