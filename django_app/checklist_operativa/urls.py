from __future__ import annotations

from django.urls import path

from . import views

app_name = "checklist_operativa"

urlpatterns = [
    path("", views.gestione_home, name="gestione"),
    path("conferma/<int:voce_id>/", views.gestione_conferma, name="conferma"),
    path("proponi/", views.gestione_proposta_nuova, name="proponi"),

    path("configurazione/", views.configurazione_home, name="configurazione"),
    path("configurazione/task/nuovo/", views.configurazione_task_edit, name="task_nuovo"),
    path("configurazione/task/<int:pk>/modifica/", views.configurazione_task_edit, name="task_modifica"),
    path("configurazione/task/<int:pk>/toggle/", views.configurazione_task_toggle, name="task_toggle"),

    path("configurazione/eventi/nuovo/", views.configurazione_evento_nuovo, name="evento_nuovo"),
    path("configurazione/eventi/<int:pk>/", views.configurazione_evento_detail, name="evento_detail"),
    path("configurazione/eventi/<int:pk>/chiudi/", views.configurazione_evento_chiudi, name="evento_chiudi"),
    path("configurazione/eventi/<int:evento_pk>/voce/nuova/", views.configurazione_voce_edit, name="voce_nuova"),
    path("configurazione/eventi/<int:evento_pk>/voce/<int:pk>/modifica/", views.configurazione_voce_edit, name="voce_modifica"),

    path("configurazione/proposte/", views.configurazione_proposte, name="proposte"),
    path("configurazione/proposte/<int:pk>/decidi/", views.configurazione_proposta_decidi, name="proposta_decidi"),

    path("riepilogo/", views.riepilogo_list, name="riepilogo"),
    path("riepilogo/<int:pk>/", views.riepilogo_detail, name="riepilogo_detail"),
]
