from django.urls import path

from . import views

app_name = "gestione_carichi_macchina"

urlpatterns = [
    path("", views.vista_excel, name="excel"),
    path("gantt/", views.vista_gantt, name="gantt"),
    path("cella/", views.cella_edit, name="cella_edit"),
    path("cella/suggerimento/", views.cella_suggerimento, name="cella_suggerimento"),
    path("reschedule/", views.reschedule, name="reschedule"),
    path("reschedule/undo/", views.reschedule_undo, name="reschedule_undo"),
    path("api/pianificazioni/", views.api_pianificazioni, name="api_pianificazioni"),
    path("api/suggerimento-macchina/", views.api_suggerimento_macchina, name="api_suggerimento_macchina"),
    path("api/spiega-macchina/", views.api_spiega_macchina, name="api_spiega_macchina"),
]
