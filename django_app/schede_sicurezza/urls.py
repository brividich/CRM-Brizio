from __future__ import annotations

from django.urls import path

from . import views

app_name = "schede_sicurezza"

urlpatterns = [
    path("", views.prodotto_list, name="prodotto_list"),
    path("nuovo/", views.prodotto_form, name="prodotto_nuovo"),
    path("report/", views.report_compliance, name="report_compliance"),
    path("<int:pk>/", views.prodotto_detail, name="prodotto_detail"),
    path("<int:pk>/modifica/", views.prodotto_form, name="prodotto_modifica"),
    path("<int:pk>/qr/", views.prodotto_qr, name="prodotto_qr"),
    path("s/<uuid:uuid>/", views.scheda_mobile, name="scheda_mobile"),
    path("scheda/<int:pk>/download/", views.scheda_download, name="scheda_download"),
    path("scheda/<int:scheda_pk>/presa-visione/", views.presa_visione_conferma, name="presa_visione_conferma"),
    path("scheda/<int:scheda_pk>/presa-visione/elenco/", views.presa_visione_list, name="presa_visione_list"),
]
