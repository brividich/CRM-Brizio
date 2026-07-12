"""URLconf per l'innesto nell'HUB (area SOC IT - CN).

Fase B1: sola dashboard. Fase B2: aggiunte le pagine Alert/Ticket/KPI (viste reali).
NON si include `security/urls.py` (accoppiato a DRF/AI/API): le rotte API/admin/
pipeline/inbox/diagnostica restano fuori (arrivano in B3). Le rotte non ancora
montate hanno uno stub che rimanda alla dashboard, così i `{% url 'security:...' %}`
nei template esistenti risolvono senza NoReverseMatch.
"""
from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = "security"


def _in_arrivo(request, *args, **kwargs):
    """Placeholder per le rotte non ancora montate (pipeline/admin/... → B3)."""
    return redirect("security:dashboard")


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("panoramica/", views.dashboard, name="security_dashboard"),
    # B2 — Alert / Ticket / KPI (viste reali)
    path("alerts/", views.alerts_list, name="alerts_list"),
    path("alerts/<int:pk>/", views.alert_detail, name="alert_detail"),
    path("alerts/<int:pk>/actions/<slug:action>/", views.alert_action, name="alert_action"),
    path("tickets/", views.tickets_list, name="tickets_list"),
    path("kpis/", views.kpis_page, name="kpis"),
    # stub → B3 (pipeline/ingestione)
    path("pipeline/", _in_arrivo, name="pipeline"),
]
