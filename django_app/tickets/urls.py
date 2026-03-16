from django.urls import path
from . import views

urlpatterns = [
    path("",                          views.ticket_dashboard,        name="dashboard"),
    path("nuovo/",                    views.ticket_nuovo,            name="nuovo"),
    path("<int:pk>/pdf/",             views.ticket_pdf,              name="pdf"),
    path("<int:pk>/",                 views.ticket_detail,           name="detail"),
    path("gestione/",                 views.ticket_gestione_list,    name="gestione_list"),
    path("gestione/<int:pk>/",        views.ticket_gestione_detail,  name="gestione_detail"),
    path("impostazioni/",             views.ticket_impostazioni,     name="impostazioni"),
    # API
    path("api/commento/",             views.api_commento,            name="api_commento"),
    path("api/allegato/",             views.api_allegato,            name="api_allegato"),
    path("api/stato/",                views.api_stato,               name="api_stato"),
    path("api/assegna/",              views.api_assegna,             name="api_assegna"),
    path("api/asset/",                views.api_asset,               name="api_asset"),
    path("api/impostazioni/",         views.api_impostazioni,        name="api_impostazioni"),
    path("api/cerca-utenti/",         views.api_cerca_utenti,        name="api_cerca_utenti"),
    path("api/assets-autocomplete/", views.api_assets_autocomplete, name="api_assets_autocomplete"),
    path("api/test-sp/",              views.api_test_sp,             name="api_test_sp"),
    path("api/import-csv/",          views.api_import_csv,          name="api_import_csv"),
    path("api/bulk/",                views.api_bulk,                name="api_bulk"),
]
