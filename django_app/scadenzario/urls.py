from django.urls import path

from . import views

app_name = "scadenzario"

urlpatterns = [
    path("gestione/", views.gestione, name="gestione"),
    path("gestione/voce/", views.gestione_voce, name="gestione_voce"),
    path("gestione/regola/", views.gestione_regola_aggiungi, name="gestione_regola_aggiungi"),
    path("gestione/regola/<int:regola_id>/togli/", views.gestione_regola_togli, name="gestione_regola_togli"),
    path("generiche/", views.elenco, name="elenco"),
    path("generiche/nuova/", views.scadenza_nuova, name="scadenza_nuova"),
    path("generiche/<int:pk>/", views.scadenza_dettaglio, name="scadenza_dettaglio"),
    path("generiche/<int:pk>/modifica/", views.scadenza_modifica, name="scadenza_modifica"),
    path("generiche/<int:pk>/rinnovo/", views.scadenza_rinnovo, name="scadenza_rinnovo"),
    path("generiche/rinnovi/<int:pk>/allegato/", views.rinnovo_allegato, name="rinnovo_allegato"),
    path("generiche/categorie/", views.categorie, name="categorie"),
    path("generiche/categorie/<int:pk>/", views.categoria_modifica, name="categoria_modifica"),
    path("generiche/avvisi/", views.avvisi, name="avvisi"),
]
