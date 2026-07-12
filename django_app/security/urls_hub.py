"""URLconf MINIMO per la fase B1 dell'innesto nell'HUB (area SOC IT - CN).

Monta SOLO la dashboard. Le altre pagine (alerts/tickets/pipeline/...) e le API DRF
NON sono incluse in B1: qui restano come stub che rimandano alla dashboard, così i
`{% url 'security:...' %}` nei template esistenti risolvono senza NoReverseMatch.
Il wiring completo (con ACL, nav e pagine reali) arriva in B2. NON si include
`security/urls.py` (accoppiato a DRF/AI/API).
"""
from django.shortcuts import redirect
from django.urls import path

from . import views

app_name = "security"


def _in_arrivo_b2(request, *args, **kwargs):
    """Placeholder per le rotte non ancora montate in B1 (arrivano in B2)."""
    return redirect("security:dashboard")


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("panoramica/", views.dashboard, name="security_dashboard"),
    # stub B1 -> B2 (evitano NoReverseMatch nei template esistenti)
    path("alerts/", _in_arrivo_b2, name="alerts_list"),
    path("alerts/<int:pk>/", _in_arrivo_b2, name="alert_detail"),
    path("tickets/", _in_arrivo_b2, name="tickets_list"),
    path("pipeline/", _in_arrivo_b2, name="pipeline"),
]
