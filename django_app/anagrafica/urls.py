from django.urls import path

from . import views
from . import views_mpq
from . import views_recruiting

app_name = "anagrafica"

urlpatterns = [
    # Dashboard
    path("", views.index, name="index"),

    # Export tabellari (PDF/Excel) — endpoint unico parametrico
    path("esporta/<str:key>/", views.export_view, name="export"),

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
    # Stampa scheda dipendente completa (anagrafica civile + aziendale + dati bancari)
    path("dipendenti/<int:legacy_id>/stampa/", views.dipendente_print, name="dipendente_print"),
    # Libretto formativo stampabile (storico corsi + obblighi correnti); ?formato=pdf per il PDF
    path("dipendenti/<int:legacy_id>/libretto-formativo/", views.dipendente_libretto_formativo, name="dipendente_libretto_formativo"),
    # Salva (manualmente) il libretto formativo PDF nel box documenti del dipendente
    path("dipendenti/<int:legacy_id>/libretto-formativo/salva-box", views.libretto_salva_box, name="libretto_salva_box"),
    # Attestato di formazione autogenerato per singolo completamento (corso/qualifica/altro)
    path("formazione/attestato/<int:record_id>/", views.attestato_formazione, name="attestato_formazione"),
    # Salva (manualmente) l'attestato PDF nel box documenti del dipendente
    path("formazione/attestato/<int:record_id>/salva-box", views.attestato_salva_box, name="attestato_salva_box"),
    # Impostazioni template attestato (testi/firme/logo/privacy) + gestione archivio — da Impostazioni HR
    path("formazione/attestato-impostazioni/", views.attestato_impostazioni, name="attestato_impostazioni"),
    # Export CSV dell'archivio attestati salvati
    path("formazione/attestato-report-export/", views.attestato_report_export, name="attestato_report_export"),
    # Genera e archivia in blocco gli attestati di tutti i completati di una sessione
    path("formazione/sessioni/<int:sessione_id>/attestati/", views.formazione_sessione_attestati, name="formazione_sessione_attestati"),
    # Pannello semaforo conformità (HTMX lazy-load nella scheda dipendente)
    path("dipendenti/<int:legacy_id>/conformita/", views.dipendente_conformita_panel, name="dipendente_conformita_panel"),
    path("dipendenti/<int:legacy_id>/esposizione-rischio/add/", views.dipendente_esposizione_rischio_add, name="dipendente_esposizione_rischio_add"),
    path("dipendenti/<int:legacy_id>/esposizione-rischio/<int:esp_id>/remove/", views.dipendente_esposizione_rischio_remove, name="dipendente_esposizione_rischio_remove"),
    path("dipendenti/<int:legacy_id>/verbale-dpi/", views.dipendente_verbale_dpi, name="dipendente_verbale_dpi"),
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
    # Offboarding: apertura pratica task + chiusura rapporto legacy/account
    path(
        "dipendenti/<int:legacy_id>/offboarding/licenziamento",
        views.dipendente_offboarding_licenziamento,
        name="dipendente_offboarding_licenziamento",
    ),
    path(
        "dipendenti/<int:legacy_id>/offboarding/<int:pratica_id>/task/<int:task_id>/",
        views.dipendente_offboarding_task_update,
        name="dipendente_offboarding_task_update",
    ),
    path(
        "dipendenti/<int:legacy_id>/offboarding/<int:pratica_id>/chiudi",
        views.dipendente_offboarding_chiudi,
        name="dipendente_offboarding_chiudi",
    ),
    path(
        "dipendenti/<int:legacy_id>/rimetti-in-forza",
        views.dipendente_rimetti_in_forza,
        name="dipendente_rimetti_in_forza",
    ),

    # Qualifiche dipendente
    path("dipendenti/<int:legacy_id>/qualifiche/add", views.dipendente_qualifica_add, name="dipendente_qualifica_add"),
    path("dipendenti/<int:legacy_id>/qualifiche/<int:q_id>/delete", views.dipendente_qualifica_delete, name="dipendente_qualifica_delete"),
    path("dipendenti/<int:legacy_id>/qualifiche/<int:q_id>/evidenza", views.dipendente_qualifica_evidenza, name="dipendente_qualifica_evidenza"),
    path("dipendenti/<int:legacy_id>/qualifiche/<int:q_id>/storico/<int:storico_id>/evidenza", views.dipendente_qualifica_storico_evidenza, name="dipendente_qualifica_storico_evidenza"),
    path("dipendenti/<int:legacy_id>/qualifiche/<int:q_id>/verifica", views.dipendente_qualifica_verifica, name="dipendente_qualifica_verifica"),

    # Dashboard globale visite mediche
    path("visite-mediche/", views.visite_mediche_dashboard, name="visite_mediche_dashboard"),
    path("visite-mediche/nuova-sessione/", views.visite_mediche_nuova_sessione, name="visite_mediche_nuova_sessione"),
    path("visite-mediche/export/scadenze.xlsx", views.visite_mediche_export_scadenze, name="visite_mediche_export_scadenze"),
    path("visite-mediche/export/copertura.xlsx", views.visite_mediche_export_copertura, name="visite_mediche_export_copertura"),
    path("visite-mediche/api/cerca-dipendente/", views.visite_mediche_api_cerca_dipendente, name="visite_mediche_api_cerca_dipendente"),
    path("visite-mediche/candidati/", views.visite_mediche_candidati, name="visite_mediche_candidati"),
    path("visite-mediche/sessioni/", views.visite_mediche_sessioni, name="visite_mediche_sessioni"),
    path("visite-mediche/sessioni/<int:sessione_id>/", views.visite_mediche_sessione_detail, name="visite_mediche_sessione_detail"),
    path("visite-mediche/sessioni/<int:sessione_id>/partecipante/aggiungi/", views.visite_mediche_sessione_partecipante_add, name="visite_mediche_sessione_partecipante_add"),
    path("visite-mediche/sessioni/<int:sessione_id>/elimina/", views.visite_mediche_sessione_delete, name="visite_mediche_sessione_delete"),

    # Visite mediche dipendente
    path("dipendenti/<int:legacy_id>/visite/add", views.dipendente_visita_add, name="dipendente_visita_add"),
    path("dipendenti/<int:legacy_id>/visite/<int:v_id>/edit", views.dipendente_visita_edit, name="dipendente_visita_edit"),
    path("dipendenti/<int:legacy_id>/visite/<int:v_id>/delete", views.dipendente_visita_delete, name="dipendente_visita_delete"),

    # Foto profilo dipendente (storage privato, servita da view protetta)
    path("dipendenti/<int:legacy_id>/foto", views.foto_dipendente, name="foto_dipendente"),

    # Documenti dipendente (storage privato)
    path("documenti/", views.documenti_list, name="documenti_list"),
    path("documenti/<int:doc_id>/download", views.documento_dipendente_download, name="documento_download"),
    path("documenti/<int:doc_id>/delete", views.documento_dipendente_delete, name="documento_delete"),
    path("documenti/<int:doc_id>/sposta", views.documento_sposta_cartella, name="documento_sposta"),
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
    path("mansioni/<int:mansione_id>/requisiti", views.mansione_requisiti, name="mansione_requisiti"),
    path("mansioni/<int:mansione_id>/elimina", views.mansione_delete, name="mansione_delete"),

    # Aree aziendali + Reparti (gerarchia a due livelli)
    path("aree/", views.aree_list, name="aree_list"),
    # Aree aziendali (livello padre)
    path("aree/area-aziendale/nuova", views.area_aziendale_create, name="area_aziendale_create"),
    path("aree/area-aziendale/<int:area_id>/modifica", views.area_aziendale_edit, name="area_aziendale_edit"),
    path("aree/area-aziendale/<int:area_id>/elimina", views.area_aziendale_delete, name="area_aziendale_delete"),
    # Reparti (livello figlio, URL legacy mantenute)
    path("aree/nuovo", views.area_create, name="area_create"),
    path("aree/<int:area_id>/modifica", views.area_edit, name="area_edit"),
    path("aree/<int:area_id>/elimina", views.area_delete, name="area_delete"),

    # Ruoli aziendali catalogo
    path("ruoli-aziendali/", views.ruoli_aziendali_list, name="ruoli_aziendali_list"),
    path("ruoli-aziendali/nuovo", views.ruolo_aziendale_create, name="ruolo_aziendale_create"),
    path("ruoli-aziendali/<int:ruolo_id>/modifica", views.ruolo_aziendale_edit, name="ruolo_aziendale_edit"),
    path("ruoli-aziendali/<int:ruolo_id>/elimina", views.ruolo_aziendale_delete, name="ruolo_aziendale_delete"),

    # Qualifiche & Certificazioni — cruscotto trasversale + scadenzario dedicato
    path("qualifiche/cruscotto/", views.qualifiche_dashboard, name="qualifiche_dashboard"),
    path("qualifiche/scadenzario/", views.qualifiche_scadenzario, name="qualifiche_scadenzario"),

    # Qualifiche catalogo + scadenze
    path("qualifiche/", views.qualifiche_list, name="qualifiche_list"),
    path("qualifiche/nuovo", views.tipo_qualifica_create, name="tipo_qualifica_create"),
    # Sessioni di rinnovo (rilascio/rinnovo collettivo "a sessioni")
    path("qualifiche/sessioni/", views.qualifica_sessioni_list, name="qualifica_sessioni_list"),
    path("qualifiche/sessioni/nuova", views.qualifica_sessione_create, name="qualifica_sessione_create"),
    path("qualifiche/sessioni/candidati", views.qualifica_sessione_candidati, name="qualifica_sessione_candidati"),
    path("qualifiche/sessioni/<int:sessione_id>/", views.qualifica_sessione_detail, name="qualifica_sessione_detail"),
    path("qualifiche/sessioni/<int:sessione_id>/report.csv", views.qualifica_sessione_report_csv, name="qualifica_sessione_report_csv"),
    path("qualifiche/sessioni/<int:sessione_id>/elimina", views.qualifica_sessione_delete, name="qualifica_sessione_delete"),
    path("qualifiche/sessioni/<int:sessione_id>/partecipante/aggiungi", views.qualifica_sessione_partecipante_add, name="qualifica_sessione_partecipante_add"),
    path("qualifiche/sessioni/<int:sessione_id>/partecipante/<int:q_id>/rimuovi", views.qualifica_sessione_partecipante_remove, name="qualifica_sessione_partecipante_remove"),
    path("qualifiche/<int:tipo_id>/", views.tipo_qualifica_detail, name="tipo_qualifica_detail"),
    path("qualifiche/<int:tipo_id>/modifica", views.tipo_qualifica_edit, name="tipo_qualifica_edit"),
    path("qualifiche/<int:tipo_id>/elimina", views.tipo_qualifica_delete, name="tipo_qualifica_delete"),

    # MOD.128 MPQ — Processi qualificati (cruscotto + vista/export + dettaglio).
    # Agganciato al gruppo esistente Competenze → Qualifiche (subnav 0077).
    path("mod128/", views_mpq.mpq_cruscotto, name="mpq_cruscotto"),
    path("mod128/vista/", views_mpq.mpq_vista, name="mpq_vista"),
    # Gestione (CRUD) — gated anagrafica.mpq.manage
    path("mod128/nuovo/", views_mpq.mpq_processo_create, name="mpq_processo_create"),
    path("mod128/clienti/", views_mpq.mpq_cliente_list, name="mpq_cliente_list"),
    path("mod128/clienti/nuovo/", views_mpq.mpq_cliente_create, name="mpq_cliente_create"),
    path("mod128/clienti/<int:cliente_id>/modifica/", views_mpq.mpq_cliente_edit, name="mpq_cliente_edit"),
    path("mod128/abilitazione/<int:ab_id>/modifica/", views_mpq.mpq_abilitazione_edit, name="mpq_abilitazione_edit"),
    path("mod128/abilitazione/<int:ab_id>/elimina/", views_mpq.mpq_abilitazione_delete, name="mpq_abilitazione_delete"),
    path("mod128/abilitazione/<int:ab_id>/certificazione/aggiungi/", views_mpq.mpq_certificazione_add, name="mpq_certificazione_add"),
    path("mod128/certificazione/<int:cert_id>/elimina/", views_mpq.mpq_certificazione_delete, name="mpq_certificazione_delete"),
    path("mod128/riferimento/<int:rif_id>/elimina/", views_mpq.mpq_riferimento_delete, name="mpq_riferimento_delete"),
    path("mod128/quick-add/corso/", views_mpq.mpq_quickadd_corso, name="mpq_quickadd_corso"),
    path("mod128/quick-add/visita/", views_mpq.mpq_quickadd_visita, name="mpq_quickadd_visita"),
    path("mod128/quick-add/dpi/", views_mpq.mpq_quickadd_dpi, name="mpq_quickadd_dpi"),
    path("mod128/<int:processo_id>/", views_mpq.mpq_processo_detail, name="mpq_processo_detail"),
    path("mod128/<int:processo_id>/modifica/", views_mpq.mpq_processo_edit, name="mpq_processo_edit"),
    path("mod128/<int:processo_id>/elimina/", views_mpq.mpq_processo_delete, name="mpq_processo_delete"),
    path("mod128/<int:processo_id>/abilitazione/aggiungi/", views_mpq.mpq_abilitazione_add, name="mpq_abilitazione_add"),
    path("mod128/<int:processo_id>/riferimento/aggiungi/", views_mpq.mpq_riferimento_add, name="mpq_riferimento_add"),

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

    # Scadenzario unificato qualifiche + visite + formazione + contratti
    path("scadenzario/", views.scadenzario, name="scadenzario"),

    # Organigramma visuale (aree → reparti → capi → dipendenti)
    path("organigramma/", views.organigramma, name="organigramma"),
    path("organigramma/albero/", views.organigramma_albero, name="organigramma_albero"),

    # Report conformità "idoneità alla mansione" (semaforo per dominio)
    path("conformita/", views.conformita_report, name="conformita_report"),
    path("sicurezza/", views.sicurezza_hub, name="sicurezza_hub"),
    path("sicurezza/ricerca/", views.sicurezza_ricerca, name="sicurezza_ricerca"),
    path("sicurezza/guida/", views.sicurezza_wizard, name="sicurezza_wizard"),
    path("sicurezza/matrice/", views.matrice_competenze, name="matrice_competenze"),

    # Skill Matrix MOD.187 — matrice macchina (F4) + validazione match (F2a UI) + refresh CAR (F6)
    path("skill-matrix/", views.skill_matrix_macchina, name="skill_matrix_macchina"),
    path("skill-matrix/match/", views.skm_match_validazione, name="skm_match_validazione"),
    path("skill-matrix/refresh/", views.skm_refresh, name="skm_refresh"),
    path("skill-matrix/scadenzario/", views.skm_scadenzario, name="skm_scadenzario"),
    path("skill-matrix/impostazioni/", views.skm_impostazioni, name="skm_impostazioni"),

    # Onboarding strutturato (pratica + checklist, speculare a offboarding)
    path("onboarding/", views.onboarding_list, name="onboarding_list"),
    path("onboarding/<int:pratica_id>/", views.onboarding_detail, name="onboarding_detail"),
    path("dipendenti/<int:legacy_id>/onboarding/avvia", views.onboarding_avvia, name="onboarding_avvia"),
    path("onboarding/<int:pratica_id>/task/<int:task_id>/update", views.onboarding_task_update, name="onboarding_task_update"),
    path("onboarding/<int:pratica_id>/chiudi", views.onboarding_chiudi, name="onboarding_chiudi"),
    path("onboarding/<int:pratica_id>/annulla", views.onboarding_annulla, name="onboarding_annulla"),

    # ── Recruiting MOD. 05-01 (selezione risorse, a monte dell'onboarding) ──
    path("recruiting/", views_recruiting.recruiting_list, name="recruiting_list"),
    path("recruiting/cruscotto/", views_recruiting.recruiting_dashboard, name="recruiting_dashboard"),
    path("recruiting/criteri/", views_recruiting.recruiting_criteri, name="recruiting_criteri"),
    path("recruiting/criteri/<int:criterio_id>/toggle/", views_recruiting.recruiting_criterio_toggle, name="recruiting_criterio_toggle"),
    path("recruiting/criteri/<int:criterio_id>/elimina/", views_recruiting.recruiting_criterio_delete, name="recruiting_criterio_delete"),
    path("recruiting/criteri/<int:criterio_id>/sposta/", views_recruiting.recruiting_criterio_move, name="recruiting_criterio_move"),
    path("recruiting/nuovo/", views_recruiting.recruiting_create, name="recruiting_create"),
    path("recruiting/<int:candidato_id>/", views_recruiting.recruiting_detail, name="recruiting_detail"),
    path("recruiting/<int:candidato_id>/modifica/", views_recruiting.recruiting_edit, name="recruiting_edit"),
    path("recruiting/<int:candidato_id>/secondo-colloquio/", views_recruiting.recruiting_step2, name="recruiting_step2"),
    path("recruiting/<int:candidato_id>/assumi/", views_recruiting.recruiting_assumi, name="recruiting_assumi"),
    path("recruiting/<int:candidato_id>/archivia/", views_recruiting.recruiting_archivia, name="recruiting_archivia"),
    path("recruiting/<int:candidato_id>/annulla/", views_recruiting.recruiting_annulla, name="recruiting_annulla"),
    path("recruiting/<int:candidato_id>/riapri/", views_recruiting.recruiting_riapri, name="recruiting_riapri"),

    # ── Formazione HR — Dashboard ──────────────────────────────────────────
    path("formazione/", views.formazione_dashboard, name="formazione_dashboard"),
    # Ricerca globale formazione (corsi, sessioni, piani, qualifiche, dipendenti, attestati)
    path("formazione/ricerca/", views.formazione_ricerca, name="formazione_ricerca"),
    # Quick-add inline (JSON) entità collegate dei form (piano/categoria/qualifica/docente)
    path("formazione/quick-add/piano", views.formazione_quickadd_piano, name="formazione_quickadd_piano"),
    path("formazione/quick-add/categoria", views.formazione_quickadd_categoria, name="formazione_quickadd_categoria"),
    path("formazione/quick-add/qualifica", views.formazione_quickadd_qualifica, name="formazione_quickadd_qualifica"),
    path("formazione/quick-add/docente", views.formazione_quickadd_docente, name="formazione_quickadd_docente"),
    # Assist form corso: codice suggerito univoco + durata qualifica (validità preimpostata)
    path("formazione/corsi/codice-suggerito", views.formazione_corso_codice_suggest, name="formazione_corso_codice_suggest"),
    path("formazione/qualifica-durata", views.formazione_qualifica_durata, name="formazione_qualifica_durata"),

    # ── Formazione HR — Piani formativi ────────────────────────────────────
    path("formazione/piani/", views.formazione_piani_list, name="formazione_piani_list"),
    path("formazione/piani/nuovo", views.formazione_piano_create, name="formazione_piano_create"),
    path("formazione/piani/<int:piano_id>/", views.formazione_piano_detail, name="formazione_piano_detail"),
    path("formazione/piani/<int:piano_id>/modifica", views.formazione_piano_edit, name="formazione_piano_edit"),
    path("formazione/piani/<int:piano_id>/elimina", views.formazione_piano_delete, name="formazione_piano_delete"),

    # ── Formazione HR — Corsi ──────────────────────────────────────────────
    path("formazione/corsi/", views.formazione_corsi_list, name="formazione_corsi_list"),
    path("formazione/corsi/nuovo/", views.formazione_corso_create, name="formazione_corso_create"),
    path("formazione/corsi/<int:corso_id>/", views.formazione_corso_detail, name="formazione_corso_detail"),
    path("formazione/corsi/<int:corso_id>/modifica", views.formazione_corso_edit, name="formazione_corso_edit"),
    path("formazione/corsi/<int:corso_id>/elimina", views.formazione_corso_delete, name="formazione_corso_delete"),
    # Report rapidi del corso
    path("formazione/corsi/<int:corso_id>/report/iscritti.csv", views.formazione_corso_report_iscritti_csv, name="formazione_corso_report_iscritti_csv"),
    path("formazione/corsi/<int:corso_id>/report/attestati.zip", views.formazione_corso_attestati_zip, name="formazione_corso_attestati_zip"),
    path("formazione/corsi/<int:corso_id>/report/fogli-firme.pdf", views.formazione_corso_registri_pdf, name="formazione_corso_registri_pdf"),
    # Prerequisiti
    path("formazione/corsi/<int:corso_id>/prerequisiti/add", views.formazione_corso_dep_add, name="formazione_corso_dep_add"),
    path("formazione/corsi/<int:corso_id>/prerequisiti/<int:dep_id>/rimuovi", views.formazione_corso_dep_delete, name="formazione_corso_dep_delete"),
    # Versioni
    path("formazione/corsi/<int:corso_id>/versioni/add", views.formazione_corso_version_add, name="formazione_corso_version_add"),
    path("formazione/corsi/<int:corso_id>/versioni/<int:ver_id>/rimuovi", views.formazione_corso_version_delete, name="formazione_corso_version_delete"),
    # Regola superamento
    path("formazione/corsi/<int:corso_id>/regola-superamento/salva", views.formazione_corso_completion_rule_save, name="formazione_corso_completion_rule_save"),
    # Regole obbligatorietà
    path("formazione/corsi/<int:corso_id>/regole-obbligo/add", views.formazione_corso_req_rule_add, name="formazione_corso_req_rule_add"),
    path("formazione/corsi/<int:corso_id>/regole-obbligo/<int:rule_id>/rimuovi", views.formazione_corso_req_rule_delete, name="formazione_corso_req_rule_delete"),
    # Assegnazione dipendenti al corso (TrainingAssignment) — primo anello corso→sessione
    path("formazione/corsi/<int:corso_id>/assegna", views.formazione_corso_assegna, name="formazione_corso_assegna"),

    # ── Formazione HR — E-learning (micro-corsi: slide + quiz) ─────────────
    # Hub di gestione (autori/HR)
    path("formazione/elearning/", views.formazione_elearning_hub, name="formazione_elearning_hub"),
    path("formazione/elearning/impostazioni/", views.formazione_elearning_settings, name="formazione_elearning_settings"),
    path("formazione/elearning/<int:corso_id>/gestione", views.formazione_elearning_manage, name="formazione_elearning_manage"),
    path("formazione/elearning/<int:corso_id>/pubblica", views.formazione_elearning_publish_toggle, name="formazione_elearning_publish_toggle"),
    path("formazione/elearning/<int:corso_id>/iscritti.csv", views.formazione_elearning_iscritti_csv, name="formazione_elearning_iscritti_csv"),
    path("formazione/elearning/<int:corso_id>/assegna", views.formazione_elearning_assign, name="formazione_elearning_assign"),
    path("formazione/elearning/<int:corso_id>/assegnazioni/<int:assignment_id>/rimuovi", views.formazione_elearning_unassign, name="formazione_elearning_unassign"),
    # Autore (gestione contenuti)
    path("formazione/corsi/<int:corso_id>/elearning/", views.formazione_corso_elearning, name="formazione_corso_elearning"),
    path("formazione/corsi/<int:corso_id>/elearning/slide/salva", views.formazione_slide_save, name="formazione_slide_save"),
    path("formazione/corsi/<int:corso_id>/elearning/slide/importa", views.formazione_slide_import, name="formazione_slide_import"),
    path("formazione/corsi/<int:corso_id>/elearning/slide/<int:slide_id>/elimina", views.formazione_slide_delete, name="formazione_slide_delete"),
    # Sotto il prefisso shared "corsi-online/" così il discente può caricarla inline
    # (il gating reale è dentro la view).
    path("formazione/corsi-online/slide/<int:slide_id>/immagine", views.formazione_slide_image, name="formazione_slide_image"),
    path("formazione/corsi/<int:corso_id>/elearning/domande/salva", views.formazione_question_save, name="formazione_question_save"),
    path("formazione/corsi/<int:corso_id>/elearning/domande/<int:question_id>/elimina", views.formazione_question_delete, name="formazione_question_delete"),
    path("formazione/corsi/<int:corso_id>/elearning/domande/<int:question_id>/opzioni/salva", views.formazione_option_save, name="formazione_option_save"),
    path("formazione/corsi/<int:corso_id>/elearning/opzioni/<int:option_id>/elimina", views.formazione_option_delete, name="formazione_option_delete"),
    # Discente (fruizione)
    path("formazione/corsi-online/", views.formazione_online_catalog, name="formazione_online_catalog"),
    path("formazione/corsi-online/<int:corso_id>/", views.formazione_online_player, name="formazione_online_player"),
    path("formazione/corsi-online/<int:corso_id>/slide/<int:ordine>", views.formazione_online_slide, name="formazione_online_slide"),
    path("formazione/corsi-online/<int:corso_id>/quiz", views.formazione_online_quiz, name="formazione_online_quiz"),

    # ── Formazione HR — Istruttori ─────────────────────────────────────────
    path("formazione/istruttori/", views.formazione_istruttori_list, name="formazione_istruttori_list"),
    path("formazione/istruttori/nuovo", views.formazione_istruttore_create, name="formazione_istruttore_create"),
    path("formazione/istruttori/<int:istruttore_id>/modifica", views.formazione_istruttore_edit, name="formazione_istruttore_edit"),
    path("formazione/istruttori/<int:istruttore_id>/elimina", views.formazione_istruttore_delete, name="formazione_istruttore_delete"),

    # ── Formazione HR — Sessioni ────────────────────────────────────────────
    path("formazione/sessioni/", views.formazione_sessioni_list, name="formazione_sessioni_list"),
    path("formazione/sessioni/nuova/", views.formazione_sessione_create, name="formazione_sessione_create"),
    path("formazione/sessioni/<int:sessione_id>/", views.formazione_sessione_detail, name="formazione_sessione_detail"),
    path("formazione/sessioni/<int:sessione_id>/modifica", views.formazione_sessione_edit, name="formazione_sessione_edit"),
    path("formazione/sessioni/<int:sessione_id>/elimina", views.formazione_sessione_delete, name="formazione_sessione_delete"),
    # Lezioni inline nella sessione
    path("formazione/sessioni/<int:sessione_id>/lezioni/add", views.formazione_lezione_add, name="formazione_lezione_add"),
    path("formazione/sessioni/<int:sessione_id>/lezioni/<int:lezione_id>/modifica", views.formazione_lezione_edit, name="formazione_lezione_edit"),
    path("formazione/sessioni/<int:sessione_id>/lezioni/<int:lezione_id>/elimina", views.formazione_lezione_delete, name="formazione_lezione_delete"),
    # Presenze per lezione
    path("formazione/sessioni/<int:sessione_id>/lezioni/<int:lezione_id>/presenze/", views.formazione_lezione_presenze, name="formazione_lezione_presenze"),
    path("formazione/sessioni/<int:sessione_id>/lezioni/<int:lezione_id>/presenze/set", views.formazione_presenza_set, name="formazione_presenza_set"),
    # Autocompila presenze dal registro firme firmato (firme ingresso/uscita -> DB)
    path("formazione/sessioni/<int:sessione_id>/lezioni/<int:lezione_id>/presenze/da-registro", views.formazione_registro_autocompila, name="formazione_registro_autocompila"),
    # Registro presenze lezione — foglio firme stampabile A4
    path("formazione/sessioni/<int:sessione_id>/lezioni/<int:lezione_id>/registro/", views.formazione_lezione_registro, name="formazione_lezione_registro"),
    # Allegati formazione (registro firme firmato / materiale): livello sessione o lezione
    path("formazione/sessioni/<int:sessione_id>/allegati/upload", views.formazione_allegato_upload, name="formazione_allegato_upload"),
    path("formazione/allegati/<int:attachment_id>/elimina", views.formazione_allegato_delete, name="formazione_allegato_delete"),
    path("formazione/allegati/<int:attachment_id>/download", views.formazione_allegato_download, name="formazione_allegato_download"),

    # ── Formazione HR — Iscritti ────────────────────────────────────────────
    path("formazione/sessioni/<int:sessione_id>/iscritti/", views.formazione_sessione_iscritti, name="formazione_sessione_iscritti"),
    path("formazione/sessioni/<int:sessione_id>/iscritti/add", views.formazione_iscrizione_add, name="formazione_iscrizione_add"),
    path("formazione/sessioni/<int:sessione_id>/iscritti/rinnovo-bulk", views.formazione_iscrizione_bulk, name="formazione_iscrizione_bulk"),
    path("formazione/sessioni/<int:sessione_id>/iscritti/<int:iscrizione_id>/modifica", views.formazione_iscrizione_edit, name="formazione_iscrizione_edit"),
    path("formazione/sessioni/<int:sessione_id>/iscritti/<int:iscrizione_id>/turni", views.formazione_iscrizione_turni, name="formazione_iscrizione_turni"),
    # Carica attestato organizzatore esterno e chiudi il corso (completamento+archiviazione)
    path("formazione/sessioni/<int:sessione_id>/iscritti/<int:iscrizione_id>/attestato", views.formazione_iscrizione_attestato_upload, name="formazione_iscrizione_attestato_upload"),
    path("formazione/sessioni/<int:sessione_id>/iscritti/<int:iscrizione_id>/elimina", views.formazione_iscrizione_delete, name="formazione_iscrizione_delete"),
    # Fascicolo formativo dell'edizione (progettazione+programma+esiti+relazione) in PDF
    path("formazione/sessioni/<int:sessione_id>/fascicolo.pdf", views.formazione_sessione_fascicolo, name="formazione_sessione_fascicolo"),

    # ── Formazione HR — Scadenzario ─────────────────────────────────────────
    path("formazione/scadenzario/", views.formazione_scadenzario, name="formazione_scadenzario"),
    path("formazione/rinnovo-da-scadenzario/", views.formazione_rinnovo_da_scadenzario, name="formazione_rinnovo_da_scadenzario"),
    # Copertura / gap formativo (chi manca quali corsi obbligatori, per reparto/mansione)
    path("formazione/copertura/", views.formazione_copertura, name="formazione_copertura"),

    # ── Formazione HR — Plan (calendario eventi mese per mese) ──────────────
    path("formazione/plan/", views.formazione_plan, name="formazione_plan"),
    path("formazione/plan/dipendente/<int:legacy_id>/", views.formazione_plan, name="formazione_plan_dipendente"),

    # ── Safety / Rischi (PATCH-RISK-02) — catalogo fattori, categorie, esposizioni
    path("formazione/rischi/fattori/", views.fattori_rischio_list, name="fattori_rischio_list"),
    path("formazione/rischi/fattori/crea", views.fattore_rischio_create, name="fattore_rischio_create"),
    path("formazione/rischi/fattori/<int:pk>/modifica", views.fattore_rischio_edit, name="fattore_rischio_edit"),
    path("formazione/rischi/fattori/<int:pk>/elimina", views.fattore_rischio_delete, name="fattore_rischio_delete"),
    path("formazione/rischi/categorie/", views.categorie_corso_list, name="categorie_corso_list"),
    path("formazione/rischi/categorie/crea", views.categoria_corso_create, name="categoria_corso_create"),
    path("formazione/rischi/categorie/<int:pk>/modifica", views.categoria_corso_edit, name="categoria_corso_edit"),
    path("formazione/rischi/categorie/<int:pk>/elimina", views.categoria_corso_delete, name="categoria_corso_delete"),
    path("formazione/rischi/esposizioni/", views.esposizioni_rischio_list, name="esposizioni_rischio_list"),
    path("formazione/rischi/esposizioni/crea", views.esposizione_rischio_create, name="esposizione_rischio_create"),
    path("formazione/rischi/esposizioni/<int:pk>/modifica", views.esposizione_rischio_edit, name="esposizione_rischio_edit"),
    path("formazione/rischi/esposizioni/<int:pk>/elimina", views.esposizione_rischio_delete, name="esposizione_rischio_delete"),

    # Cedolini — importazione XLSX via interfaccia web
    path("cedolini/", views.cedolini_import, name="cedolini_import"),

    # Ratei ferie/ROL/ex-festività — lista aggregata + export
    path("ratei/", views.ratei_list, name="ratei_list"),
    path("ratei/export/", views.ratei_export, name="ratei_export"),

    # Pannello impostazioni — catalogo cataloghi e permessi del modulo anagrafica
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("impostazioni/permessi/salva", views.impostazioni_permessi_save, name="impostazioni_permessi_save"),
    path("impostazioni/workflow/campi/nuovo", views.workflow_campo_create, name="workflow_campo_create"),
    path("impostazioni/workflow/campi/<int:campo_id>/salva", views.workflow_campo_update, name="workflow_campo_update"),
    path("impostazioni/workflow/campi/<int:campo_id>/elimina", views.workflow_campo_delete, name="workflow_campo_delete"),

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
