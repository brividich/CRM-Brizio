"""Modulo pubblico delle richieste di appuntamento (``/richiesta-visita/``, senza login). Vedi views_pubbliche."""
from django.urls import path

from . import views_pubbliche

app_name = "reception_pubblica"

urlpatterns = [
    path("", views_pubbliche.richiesta, name="richiesta"),
    path("conferma/<str:token>/", views_pubbliche.conferma, name="conferma"),
]
