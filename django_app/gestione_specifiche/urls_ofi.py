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
    path("<int:pk>/", views_ofi.dettaglio, name="dettaglio"),
    path("<int:pk>/modifica/", views_ofi.modifica, name="modifica"),
]
