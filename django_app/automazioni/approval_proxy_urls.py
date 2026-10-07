"""
URL patterns per gli endpoint di approvazione ottimizzati per Entra Application Proxy.

Pubblicare SOLO il prefisso /approval-actions/* nell'Application Proxy Entra.
Non esporre l'intero /automazioni/ all'esterno.

Pattern:
  GET  /approval-actions/r/<segreto>/<approva|rifiuta>/  -> conferma (link personale email)
  POST /approval-actions/r/<segreto>/<approva|rifiuta>/  -> decisione come destinatario del link
  GET  /approval-actions/approve/<uuid:token>/  -> conferma (richiede login da approvatore)
  POST /approval-actions/approve/<uuid:token>/  -> commit decisione (richiede login)
  GET  /approval-actions/reject/<uuid:token>/   -> conferma (richiede login da approvatore)
  POST /approval-actions/reject/<uuid:token>/   -> commit decisione (richiede login)
"""
from django.urls import path

from . import views

urlpatterns = [
    path("r/<str:token>/<str:decision>/", views.approval_link_page, name="approval_link"),
    path("approve/<uuid:token>/", views.approval_proxy_approve, name="approval_proxy_approve"),
    path("reject/<uuid:token>/", views.approval_proxy_reject, name="approval_proxy_reject"),
]
