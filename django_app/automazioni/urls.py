from django.urls import path

from . import views


urlpatterns = [
    path("sorgenti/", views.sorgenti_page, name="automazioni_sorgenti"),
    path("contenuti/", views.contenuti_page, name="automazioni_contenuti"),
    path("regole/", views.rule_list_page, name="automazioni_rule_list"),
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
]
