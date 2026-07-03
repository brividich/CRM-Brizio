from django.urls import path

from . import views

app_name = "gestione_carichi_macchina"

urlpatterns = [
    path("", views.vista_excel, name="excel"),
    path("gantt/", views.vista_gantt, name="gantt"),
    path("impostazioni/", views.impostazioni_macchine, name="impostazioni"),
    path("registro/", views.registro_azioni, name="registro"),
    path("macchina/config/", views.macchina_config, name="macchina_config"),
    path("cella/", views.cella_edit, name="cella_edit"),
    path("cella/suggerimento/", views.cella_suggerimento, name="cella_suggerimento"),
    path("reschedule/", views.reschedule, name="reschedule"),
    path("reschedule/undo/", views.reschedule_undo, name="reschedule_undo"),
    path("pianificazione/<int:pk>/duplica/", views.pianificazione_duplica, name="pianificazione_duplica"),
    path("api/pianificazioni/", views.api_pianificazioni, name="api_pianificazioni"),
    path("api/pianificazione/<int:pk>/", views.api_pianificazione_dettaglio, name="api_pianificazione_dettaglio"),
    path("api/suggerimento-macchina/", views.api_suggerimento_macchina, name="api_suggerimento_macchina"),
    path("api/spiega-macchina/", views.api_spiega_macchina, name="api_spiega_macchina"),
    path("api/sovrapposizione/", views.api_sovrapposizione, name="api_sovrapposizione"),
]
