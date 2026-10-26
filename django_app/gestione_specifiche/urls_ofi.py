"""URL del modulo OFI standalone (namespace ``registro_ofi``, montato a /ofi-registro/).

Separato da ``gestione_specifiche.urls`` perché il registro OFI è uno strumento
trasversale del portale, non una sotto-rotta delle specifiche. Le viste vivono in
``gestione_specifiche.views_ofi``; i binding ACL sono in ``acl_bootstrap``.
"""
from django.urls import path

from . import views_ofi

app_name = "registro_ofi"

urlpatterns = [
    path("", views_ofi.lista, name="lista"),
    path("nuovo/", views_ofi.nuovo, name="nuovo"),
    path("guida/", views_ofi.guida, name="guida"),
    path("<int:pk>/", views_ofi.dettaglio, name="dettaglio"),
    path("<int:pk>/modifica/", views_ofi.modifica, name="modifica"),
    path("cruscotto/", views_ofi.cruscotto, name="cruscotto"),
    path("<int:pk>/avanza/", views_ofi.avanza, name="avanza"),
    path("<int:pk>/riapri/", views_ofi.riapri, name="riapri"),
    path("<int:pk>/allegati/", views_ofi.allegato_carica, name="allegato_carica"),
    path("<int:pk>/allegati/<int:allegato_id>/", views_ofi.allegato_scarica, name="allegato_scarica"),
]
