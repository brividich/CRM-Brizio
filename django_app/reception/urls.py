from django.urls import path

from . import views, views_richieste, views_ricerca

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
    path("richieste/", views_richieste.richieste, name="richieste"),
    # Ricerche live (JSON): gate in core/middleware.py API_ACL_GATE_PATHS
    path("api/sale/", views_richieste.sale_disponibilita, name="api_sale"),
    path("api/ospiti/", views_ricerca.ospiti, name="api_ospiti"),
    path("api/dipendenti/", views_ricerca.dipendenti, name="api_dipendenti"),
    path("richieste/<int:pk>/azione/", views_richieste.richiesta_azione, name="richiesta_azione"),
    # Pagina personale di ogni dipendente (permesso reception.annuncia.view)
    path("annuncia/", views_richieste.annuncia, name="annuncia"),
    path("annuncia/richieste/<int:pk>/", views_richieste.annuncia_decidi, name="annuncia_decidi"),
]
