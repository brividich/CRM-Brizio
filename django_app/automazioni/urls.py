from django.urls import path

from . import htmx_views, views


urlpatterns = [
    path("impostazioni/", views.settings_page, name="automazioni_settings"),
    # ── HTMX partials designer ────────────────────────────────────────────────
    path("regole/<int:rule_id>/azioni/aggiungi/", htmx_views.add_azione_partial, name="automazioni_htmx_add_azione"),
    path("regole/<int:rule_id>/azioni/rimuovi/", htmx_views.remove_azione_partial, name="automazioni_htmx_remove_azione"),
    path("trigger-generator/", views.trigger_generator_page, name="automazioni_trigger_generator"),
    path("sorgenti/", views.sorgenti_page, name="automazioni_sorgenti"),
    path("contenuti/", views.contenuti_page, name="automazioni_contenuti"),
    path("pianificati/", views.pianificati_page, name="automazioni_pianificati"),
    path("pianificati/azione/", views.pianificati_action, name="automazioni_pianificati_action"),
    path("pianificati/<str:name>/mail/", views.pianificati_mail_config_page, name="automazioni_pianificati_mail"),
    path("pianificati/<str:name>/mail/salva/", views.pianificati_mail_config_save, name="automazioni_pianificati_mail_save"),
    path("regole/", views.rule_list_page, name="automazioni_rule_list"),
    path(
        "regole/converti-power-automate/",
        views.rule_power_automate_convert_page,
        name="automazioni_rule_power_automate_convert",
    ),
    path(
        "regole/converti-power-automate/package.json",
        views.rule_power_automate_package_download,
        name="automazioni_rule_power_automate_package_download",
    ),
    path("regole/importa-package/", views.rule_package_import_page, name="automazioni_rule_import_package"),
    path(
        "regole/importa-package/risultato/",
        views.rule_package_import_result_page,
        name="automazioni_rule_import_result",
    ),
    path("regole/nuova/", views.rule_create_page, name="automazioni_rule_create"),
    path("regole/nuova/designer/", views.rule_designer_create_page, name="automazioni_rule_designer_create"),
    path("regole/<int:rule_id>/", views.rule_detail_page, name="automazioni_rule_detail"),
    path("regole/<int:rule_id>/designer/", views.rule_designer_page, name="automazioni_rule_designer"),
    path("regole/<int:rule_id>/modifica/", views.rule_edit_page, name="automazioni_rule_edit"),
    path(
        "regole/<int:rule_id>/designer/reorder-condizioni/",
        views.rule_condition_reorder_view,
        name="automazioni_rule_condition_reorder",
    ),
    path(
        "regole/<int:rule_id>/designer/reorder-azioni/",
        views.rule_action_reorder_view,
        name="automazioni_rule_action_reorder",
    ),
    path("regole/<int:rule_id>/toggle/", views.rule_toggle_view, name="automazioni_rule_toggle"),
    path("regole/<int:rule_id>/elimina/", views.rule_delete_view, name="automazioni_rule_delete"),
    path("regole/<int:rule_id>/test/", views.rule_test_page, name="automazioni_rule_test"),
    path("queue/", views.queue_list_page, name="automazioni_queue_list"),
    path("queue/<int:queue_id>/", views.queue_detail_page, name="automazioni_queue_detail"),
    path("queue/<int:queue_id>/reset/", views.queue_reset_view, name="automazioni_queue_reset"),
    path("queue/<int:queue_id>/retry/", views.queue_retry_view, name="automazioni_queue_retry"),
    path("queue/<int:queue_id>/stop/", views.queue_stop_view, name="automazioni_queue_stop"),
    path("queue/<int:queue_id>/delete/", views.queue_delete_view, name="automazioni_queue_delete"),
    path("run-log/", views.run_log_list_page, name="automazioni_run_log_list"),
    path("run-log/<int:run_log_id>/", views.run_log_detail_page, name="automazioni_run_log_detail"),
    path("api/table-configs/", views.api_table_config_list, name="automazioni_api_table_config_list"),
    path("api/table-configs/save/", views.api_table_config_save, name="automazioni_api_table_config_save"),
    path("api/table-configs/<int:config_id>/delete/", views.api_table_config_delete, name="automazioni_api_table_config_delete"),
    path("api/sorgenti/<str:source_code>/record-recenti/", views.api_recent_records, name="automazioni_api_recent_records"),
    path(
        "api/sorgenti/<str:source_code>/campi/<str:field_name>/valori/",
        views.api_source_field_values,
        name="automazioni_api_source_field_values",
    ),
    path("api/sorgenti/<str:source_code>/record/<str:record_id>/payload/", views.api_record_payload, name="automazioni_api_record_payload"),
    path("api/regole/<int:rule_id>/test-ajax/", views.api_test_rule_ajax, name="automazioni_api_test_rule_ajax"),
    # Canali Teams (preset webhook riutilizzabili)
    path("canali-teams/", views.teams_presets_page, name="automazioni_teams_presets"),
    path("canali-teams/crea/", views.teams_preset_create, name="automazioni_teams_preset_create"),
    path("canali-teams/<int:pk>/modifica/", views.teams_preset_edit, name="automazioni_teams_preset_edit"),
    path("canali-teams/<int:pk>/elimina/", views.teams_preset_delete, name="automazioni_teams_preset_delete"),
    path("canali-teams/flow-endpoint/crea/", views.teams_flow_endpoint_create, name="automazioni_teams_flow_endpoint_create"),
    path(
        "canali-teams/flow-endpoint/<int:pk>/modifica/",
        views.teams_flow_endpoint_edit,
        name="automazioni_teams_flow_endpoint_edit",
    ),
    path(
        "canali-teams/flow-endpoint/<int:pk>/elimina/",
        views.teams_flow_endpoint_delete,
        name="automazioni_teams_flow_endpoint_delete",
    ),
    # Approval decision (no login required, token-based)
    path("approvazione/<uuid:token>/", views.approval_status_page, name="automazioni_approval_status"),
    path("approvazione/<uuid:token>/<str:decision>/", views.approval_decision_page, name="automazioni_approval_decision"),
    # Log diagnostica mailbox approvazioni
    path("mailbox-log/", views.approval_mailbox_log_page, name="automazioni_mailbox_log"),
    # Template Email Approvazioni
    path("template-approvazioni/", views.approval_templates_list_page, name="automazioni_approval_templates"),
    path("template-approvazioni/crea/", views.approval_template_create_page, name="automazioni_approval_template_create"),
    path("template-approvazioni/<int:pk>/modifica/", views.approval_template_edit_page, name="automazioni_approval_template_edit"),
    path("template-approvazioni/<int:pk>/elimina/", views.approval_template_delete_page, name="automazioni_approval_template_delete"),
    path("template-approvazioni/<int:pk>/clona/", views.approval_template_clone_page, name="automazioni_approval_template_clone"),
    path("template-approvazioni/<int:pk>/preview/", views.approval_template_preview_page, name="automazioni_approval_template_preview"),
]
