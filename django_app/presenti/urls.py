"""URL del modulo Presenti in azienda (namespace ``presenti``, montato a /presenti/).

Binding ACL in ``presenti/acl_bootstrap.py``.
"""
from django.urls import path

from . import views

app_name = "presenti"

urlpatterns = [
    path("", views.home, name="home"),
    path("lista/", views.lista_parziale, name="lista_parziale"),
    path("pdf/", views.pdf_presenti, name="pdf"),
    path("guida/", views.guida, name="guida"),
    path("appello/", views.appello, name="appello"),
    path("appello/avvia/", views.appello_avvia, name="appello_avvia"),
    path("appello/<int:pk>/lista/", views.appello_parziale, name="appello_parziale"),
    path("appello/<int:pk>/spunta/", views.appello_spunta, name="appello_spunta"),
    path("appello/<int:pk>/chiudi/", views.appello_chiudi, name="appello_chiudi"),
    path("appello/<int:pk>/stampa/", views.appello_stampa, name="appello_stampa"),
    path("appello/<int:pk>/verbale/", views.appello_verbale, name="appello_verbale"),
    path("appello/<int:pk>/verbale/pdf/", views.appello_verbale_pdf, name="appello_verbale_pdf"),
    path("appello/<int:pk>/elimina/", views.appello_elimina, name="appello_elimina"),
    path("uscite/", views.uscite_view, name="uscite"),
    path("impostazioni/", views.impostazioni_view, name="impostazioni"),
]
