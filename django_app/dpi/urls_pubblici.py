"""Link pubblici del modulo DPI, montati sotto /approval-actions/dpi/ (prefisso gia'
esente da login e pubblicato via Entra Application Proxy)."""
from django.urls import path

from . import views_conferma

app_name = "dpi_pubblico"

urlpatterns = [
    path("<str:token>/<str:decisione>/", views_conferma.conferma_ricevuta, name="conferma_ricevuta"),
]
