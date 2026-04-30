from __future__ import annotations

from django.urls import path

from . import views

app_name = "attrezzature"

urlpatterns = [
    path("attrezzature/", views.attrezzatura_list, name="list"),
    path("attrezzature/nuova/", views.attrezzatura_create, name="create"),
    path("attrezzature/<int:pk>/", views.attrezzatura_detail, name="detail"),
    path("attrezzature/<int:pk>/modifica/", views.attrezzatura_edit, name="edit"),
    path("attrezzature/<int:pk>/elimina/", views.attrezzatura_delete, name="delete"),
    path("attrezzature/elimina-multipla/", views.attrezzatura_bulk_delete, name="bulk_delete"),
    path("attrezzature/import/", views.import_page, name="import"),
    path("attrezzature/import/preview/", views.import_preview, name="import_preview"),
    path("attrezzature/import/confirm/", views.import_confirm, name="import_confirm"),
    path("attrezzature/tasks/", views.task_list, name="task_list"),
    path("attrezzature/tasks/nuova/", views.task_create, name="task_create"),
    path("attrezzature/tasks/<int:pk>/", views.task_detail, name="task_detail"),
    path("attrezzature/tasks/<int:pk>/complete/", views.task_complete, name="task_complete"),
    path("attrezzature/tasks/<int:pk>/block/", views.task_block, name="task_block"),
    path("attrezzature/<int:pk>/aggiorna-avanzamento/", views.update_progress, name="update_progress"),
    path("attrezzature/<int:pk>/conferma-pronta-produzione/", views.confirm_ready, name="confirm_ready"),
    path("attrezzature/embedded-preview/", views.embedded_preview, name="embedded_preview"),
]
