from django.urls import path

from . import views, views_import, views_presenti, views_richieste, views_ricerca

app_name = "reception"

urlpatterns = [
    path("", views.cruscotto, name="cruscotto"),
    path("registra/", views.registra, name="registra"),
    path("importa/", views_import.importa, name="importa"),
    path("importa/modello/", views_import.importa_modello, name="importa_modello"),
    path("preregistrazioni/<int:pk>/gruppo/", views_import.invito_gruppo, name="invito_gruppo"),
    path("gruppo/<int:pk>/togli/", views_import.partecipante_togli, name="partecipante_togli"),
    path("storico/", views.storico, name="storico"),
    path("visite/<int:visita_id>/", views.visita_scheda, name="visita_scheda"),
    path("visite/<int:visita_id>/uscita/", views.visita_uscita, name="visita_uscita"),
    path("visite/<int:visita_id>/allegati/", views_import.visita_allegati, name="visita_allegati"),
    path("visite/<int:visita_id>/allegati/<int:allegato_id>/", views_import.visita_allegato, name="visita_allegato"),
    path("preregistrazioni/", views.preregistrazioni, name="preregistrazioni"),
    path("preregistrazioni/<int:pk>/azione/", views.preregistrazione_azione, name="preregistrazione_azione"),
    path("referenti/", views.referenti, name="referenti"),
    path("ditte/", views.ditte, name="ditte"),
    path("cartellini/", views.cartellini, name="cartellini"),
    path("sale/", views.sale_config, name="sale"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("richieste/", views_richieste.richieste, name="richieste"),
    # Da «Presenti in azienda» (reception.pannello.manage, binding in reception 0010)
    path("presenti/registra/", views_presenti.presenti_registra, name="presenti_registra"),
    path("presenti/<int:visita_id>/fornitore/", views_presenti.presenti_come_fornitore, name="presenti_come_fornitore"),
    # Ricerche live (JSON): gate in core/middleware.py API_ACL_GATE_PATHS
    path("api/sale/", views_richieste.sale_disponibilita, name="api_sale"),
    path("api/ospiti/", views_ricerca.ospiti, name="api_ospiti"),
    path("api/dipendenti/", views_ricerca.dipendenti, name="api_dipendenti"),
    path("richieste/<int:pk>/azione/", views_richieste.richiesta_azione, name="richiesta_azione"),
    # Pagina personale di ogni dipendente (permesso reception.annuncia.view)
    path("annuncia/", views_richieste.annuncia, name="annuncia"),
    path("annuncia/richieste/<int:pk>/", views_richieste.annuncia_decidi, name="annuncia_decidi"),
    path("annuncia/<str:cosa>/<int:pk>/collega/", views_richieste.annuncia_collega, name="annuncia_collega"),
]
