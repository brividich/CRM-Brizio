from django.urls import path
from . import views

app_name = "contatori"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("riconciliazione/", views.riconciliazione, name="riconciliazione"),
    path("riconciliazione/<str:trimestre>/", views.riconciliazione, name="riconciliazione_trim"),
    path("macchina/<int:pk>/", views.macchina_detail, name="macchina"),
    path("lettura/nuova/", views.importa_lettura, name="importa_lettura"),
    path("leggi-snmp/", views.leggi_snmp, name="leggi_snmp"),
    path("macchine/", views.macchine_list, name="macchine"),
    path("macchine/nuova/", views.macchina_edit, name="macchina_nuova"),
    path("macchine/<int:pk>/", views.macchina_edit, name="macchina_edit"),
    path("macchine/<int:pk>/test-snmp/", views.macchina_test_snmp, name="macchina_test_snmp"),
    path("discovery/", views.discovery, name="discovery"),
    path("discovery/<int:pk>/applica-ip/", views.discovery_applica_ip, name="discovery_applica_ip"),
    path("macchina/<int:pk>/consumabili/", views.macchina_consumabili, name="macchina_consumabili"),
    path("consumabili/", views.consumabili_flotta, name="consumabili"),
    path("consumabili/<int:pk>/riepilogo/", views.macchina_consumabili_riepilogo, name="consumabili_riepilogo"),
    path("analisi/", views.analisi, name="analisi"),
    path("analisi/export.xlsx", views.export_analisi, name="export_analisi"),
    path("riconciliazione/<str:trimestre>/export.xlsx", views.export_riconciliazione, name="export_riconciliazione"),
]
