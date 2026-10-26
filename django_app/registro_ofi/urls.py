"""URL del modulo Registro OFI / NC (namespace ``registro_ofi``, montato a /ofi-registro/).

La pagina iniziale è la dashboard; il registro MOD.174 è in ``elenco/``. Binding ACL
in ``registro_ofi/acl_bootstrap.py``.
"""
from django.urls import path

from . import views

app_name = "registro_ofi"

urlpatterns = [
    path("", views.home, name="home"),
    path("elenco/", views.lista, name="lista"),
    path("mie/", views.mie, name="mie"),
    path("nuovo/", views.nuovo, name="nuovo"),
    path("guida/", views.guida, name="guida"),
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
    path("<int:pk>/modifica/", views.modifica, name="modifica"),
    path("cruscotto/", views.cruscotto, name="cruscotto"),
    path("<int:pk>/avanza/", views.avanza, name="avanza"),
    path("<int:pk>/riapri/", views.riapri, name="riapri"),
    path("<int:pk>/allegati/", views.allegato_carica, name="allegato_carica"),
    path("<int:pk>/allegati/<int:allegato_id>/", views.allegato_scarica, name="allegato_scarica"),
]
