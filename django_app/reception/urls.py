from django.urls import path

from . import views

app_name = "reception"

urlpatterns = [
    path("", views.cruscotto, name="cruscotto"),
    path("registra/", views.registra, name="registra"),
    path("storico/", views.storico, name="storico"),
    path("visite/<int:visita_id>/", views.visita_scheda, name="visita_scheda"),
    path("visite/<int:visita_id>/uscita/", views.visita_uscita, name="visita_uscita"),
    path("preregistrazioni/", views.preregistrazioni, name="preregistrazioni"),
    path("preregistrazioni/<int:pk>/azione/", views.preregistrazione_azione, name="preregistrazione_azione"),
    path("referenti/", views.referenti, name="referenti"),
    path("ditte/", views.ditte, name="ditte"),
    path("cartellini/", views.cartellini, name="cartellini"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
]
