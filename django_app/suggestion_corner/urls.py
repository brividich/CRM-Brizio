from django.urls import path

from . import views

app_name = "suggestion_corner"

urlpatterns = [
    path("", views.home, name="home"),
    path("gestione/", views.gestione, name="gestione"),  # console admin del modulo (SMS_TEAM)
    path("gestione/team/aggiungi/", views.gestione_team_add, name="gestione_team_add"),
    path("gestione/team/rimuovi/", views.gestione_team_remove, name="gestione_team_remove"),
    path("nuova/", views.nuova, name="nuova"),  # form pubblico (no login, esente ACL)
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
    path("<int:pk>/modifica/", views.modifica, name="modifica"),  # gestione (SMS_TEAM)
    # Azioni FSM (sessione 3b) — POST
    path("<int:pk>/classifica/", views.azione_classifica, name="classifica"),
    path("<int:pk>/comunica-cliente/", views.azione_comunica_cliente, name="comunica_cliente"),
    path("<int:pk>/plan/", views.azione_definisci_plan, name="definisci_plan"),
    path("<int:pk>/avvia-do/", views.azione_avvia_do, name="avvia_do"),
    path("<int:pk>/completa-do/", views.azione_completa_do, name="completa_do"),
    path("<int:pk>/avvia-check/", views.azione_avvia_check, name="avvia_check"),
    path("<int:pk>/do-da-rifare/", views.azione_do_da_rifare, name="do_da_rifare"),
    path("<int:pk>/check-positivo/", views.azione_check_positivo, name="check_positivo"),
    path("<int:pk>/check-negativo/", views.azione_check_negativo, name="check_negativo"),
    path("<int:pk>/check-rinviato/", views.azione_check_rinviato, name="check_rinviato"),
    path("<int:pk>/inserisci-act/", views.azione_inserisci_act, name="inserisci_act"),
    path("<int:pk>/chiudi/", views.azione_chiudi, name="chiudi"),
    # Copilota AI (sessione 9) — endpoint JSON AJAX (gated SMS_TEAM, 403 JSON)
    path("<int:pk>/ai/classifica/", views.ai_classifica, name="ai_classifica"),
    path("<int:pk>/ai/bozza-plan/", views.ai_bozza_plan, name="ai_bozza_plan"),
    path("<int:pk>/ai/simili/", views.ai_simili, name="ai_simili"),
]
