from django.urls import path

from . import views


urlpatterns = [
    path("sorgenti/", views.sorgenti_page, name="automazioni_sorgenti"),
    path("contenuti/", views.contenuti_page, name="automazioni_contenuti"),
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
    path("regole/<int:rule_id>/test/", views.rule_test_page, name="automazioni_rule_test"),
    path("queue/", views.queue_list_page, name="automazioni_queue_list"),
    path("queue/<int:queue_id>/", views.queue_detail_page, name="automazioni_queue_detail"),
    path("queue/<int:queue_id>/reset/", views.queue_reset_view, name="automazioni_queue_reset"),
    path("queue/<int:queue_id>/retry/", views.queue_retry_view, name="automazioni_queue_retry"),
    path("run-log/", views.run_log_list_page, name="automazioni_run_log_list"),
    path("run-log/<int:run_log_id>/", views.run_log_detail_page, name="automazioni_run_log_detail"),
    path("api/table-configs/", views.api_table_config_list, name="automazioni_api_table_config_list"),
    path("api/table-configs/save/", views.api_table_config_save, name="automazioni_api_table_config_save"),
    path("api/table-configs/<int:config_id>/delete/", views.api_table_config_delete, name="automazioni_api_table_config_delete"),
    path("api/sorgenti/<str:source_code>/record-recenti/", views.api_recent_records, name="automazioni_api_recent_records"),
    path("api/sorgenti/<str:source_code>/record/<str:record_id>/payload/", views.api_record_payload, name="automazioni_api_record_payload"),
    path("api/regole/<int:rule_id>/test-ajax/", views.api_test_rule_ajax, name="automazioni_api_test_rule_ajax"),
    # Canali Teams (preset webhook riutilizzabili)
    path("canali-teams/", views.teams_presets_page, name="automazioni_teams_presets"),
    path("canali-teams/crea/", views.teams_preset_create, name="automazioni_teams_preset_create"),
    path("canali-teams/<int:pk>/modifica/", views.teams_preset_edit, name="automazioni_teams_preset_edit"),
    path("canali-teams/<int:pk>/elimina/", views.teams_preset_delete, name="automazioni_teams_preset_delete"),
    # Approval decision (no login required, token-based)
    path("approvazione/<uuid:token>/", views.approval_status_page, name="automazioni_approval_status"),
    path("approvazione/<uuid:token>/<str:decision>/", views.approval_decision_page, name="automazioni_approval_decision"),
]
