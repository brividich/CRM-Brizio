"""
URL patterns per gli endpoint di approvazione ottimizzati per Entra Application Proxy.

Pubblicare SOLO il prefisso /approval-actions/* nell'Application Proxy Entra.
Non esporre l'intero /automazioni/ all'esterno.

Pattern:
  GET  /approval-actions/approve/<uuid:token>/  -> conferma senza side effect
  POST /approval-actions/approve/<uuid:token>/  -> commit decisione
  GET  /approval-actions/reject/<uuid:token>/   -> conferma senza side effect
  POST /approval-actions/reject/<uuid:token>/   -> commit decisione
"""
from django.urls import path

from . import views

urlpatterns = [
    path("approve/<uuid:token>/", views.approval_proxy_approve, name="approval_proxy_approve"),
    path("reject/<uuid:token>/", views.approval_proxy_reject, name="approval_proxy_reject"),
]
