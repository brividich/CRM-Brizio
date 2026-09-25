from __future__ import annotations

from django.urls import path

from . import views

app_name = "sistema_gestione"

urlpatterns = [
    path("", views.index, name="index"),
    path("soa/", views.soa, name="soa"),
    path("soa/nuova-revisione/", views.soa_nuova_revisione, name="soa_nuova_revisione"),
    path("soa/voce/<int:pk>/", views.soa_voce, name="soa_voce"),
    path("soa/rev/<int:numero>/", views.soa_revisione, name="soa_revisione"),
    path("soa/rev/<int:numero>/proponi/", views.soa_proponi, name="soa_proponi"),
    path("soa/rev/<int:numero>/riporta-in-bozza/", views.soa_riporta_in_bozza, name="soa_riporta_in_bozza"),
    path("soa/rev/<int:numero>/approva/", views.soa_approva, name="soa_approva"),
    path("soa/rev/<int:numero>/copia-firmata/", views.soa_copia_firmata, name="soa_copia_firmata"),
    path("soa/rev/<int:numero>/copia-firmata/carica/", views.soa_carica_firmata, name="soa_carica_firmata"),
    path("threat-intelligence/", views.threat_intelligence, name="threat_intelligence"),
    path("threat-intelligence/nuova/", views.threat_intelligence_nuova, name="threat_intelligence_nuova"),
]
