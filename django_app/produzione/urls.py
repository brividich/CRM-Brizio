from django.urls import path

from . import views

app_name = "produzione"

urlpatterns = [
    path("", views.elenco, name="elenco"),
    path("pn/", views.pn_elenco, name="pn_elenco"),
    path("pn/scheda/", views.pn_scheda, name="pn_scheda"),
    path("pn/quote/", views.pn_quote, name="pn_quote"),
    path("api/quote/", views.api_quote, name="api_quote"),
    path("api/quote/candidati/", views.api_quote_candidati, name="api_quote_candidati"),
    path("api/quote/nota/", views.api_quote_nota, name="api_quote_nota"),
    path("api/quote/nota/<int:pk>/elimina/", views.api_quote_nota_elimina, name="api_quote_nota_elimina"),
    path("api/quote/alias/", views.api_quote_alias, name="api_quote_alias"),
    path("api/quote/alias/<int:pk>/elimina/", views.api_quote_alias_elimina, name="api_quote_alias_elimina"),
    path("quote/", views.quote_cruscotto, name="quote_cruscotto"),
    path("pn/quote/pdf/", views.quote_pdf, name="quote_pdf"),
    path("report-cmm/<int:pk>/escludi/", views.report_escludi, name="report_escludi"),
    path("pn/leggi-report/", views.pn_leggi_report, name="pn_leggi_report"),
    path("report-cmm/confronta/", views.report_confronta, name="report_confronta"),
    path("report-cmm/<int:pk>/", views.report_cmm, name="report_cmm"),
    path("report-cmm/<int:pk>/pdf/", views.report_cmm_pdf, name="report_cmm_pdf"),
    path("pn/sincronizza/", views.pn_sincronizza, name="pn_sincronizza"),
    path("pn/<path:pn>/anagrafica/", views.pn_anagrafica, name="pn_anagrafica"),
    path("pn/<path:pn>/", views.pn_scheda, name="pn"),
    path("op/nuovo/", views.op_nuovo, name="op_nuovo"),
    path("op/<int:pk>/", views.scheda, name="scheda"),
    path("op/<int:pk>/documento/", views.documento, name="documento"),
    path("op/<int:pk>/documento/<int:doc_id>/elimina/", views.documento_elimina, name="documento_elimina"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("guida/", views.guida, name="guida"),
]
