from django.urls import path

from . import views

app_name = "suggestion_corner"

urlpatterns = [
    path("", views.home, name="home"),
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
    # Azioni FSM (sessione 3b) — POST
    path("<int:pk>/classifica/", views.azione_classifica, name="classifica"),
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
]
