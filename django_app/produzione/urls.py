from django.urls import path

from . import views

app_name = "produzione"

urlpatterns = [
    path("", views.elenco, name="elenco"),
    path("pn/", views.pn_elenco, name="pn_elenco"),
    path("pn/scheda/", views.pn_scheda, name="pn_scheda"),
    path("pn/quote/", views.pn_quote, name="pn_quote"),
    path("api/quote/", views.api_quote, name="api_quote"),
    path("pn/leggi-report/", views.pn_leggi_report, name="pn_leggi_report"),
    path("report-cmm/<int:pk>/", views.report_cmm, name="report_cmm"),
    path("report-cmm/<int:pk>/pdf/", views.report_cmm_pdf, name="report_cmm_pdf"),
    path("op/nuovo/", views.op_nuovo, name="op_nuovo"),
    path("op/<int:pk>/", views.scheda, name="scheda"),
    path("op/<int:pk>/documento/", views.documento, name="documento"),
    path("op/<int:pk>/documento/<int:doc_id>/elimina/", views.documento_elimina, name="documento_elimina"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("guida/", views.guida, name="guida"),
]
