"""Link pubblici del modulo DPI, montati sotto /approval-actions/dpi/ (prefisso gia'
esente da login e pubblicato via Entra Application Proxy)."""
from django.urls import path

from . import views_conferma

app_name = "dpi_pubblico"

urlpatterns = [
    path("richiesta/<str:token>/<str:decisione>/", views_conferma.approva_da_mail, name="approva_da_mail"),
    path("<str:token>/<str:decisione>/", views_conferma.conferma_ricevuta, name="conferma_ricevuta"),
]
