from django.urls import path

from . import views

app_name = "gestione_specifiche"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuova/", views.nuova_specifica, name="nuova"),
    path("allegato/<int:pk>/", views.allegato_download, name="allegato_download"),
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
    path("<int:pk>/modifica/", views.modifica_specifica, name="modifica"),
    path("<int:pk>/avvia-flow-down/", views.avvia_flow_down_view, name="avvia_flow_down"),
    path("<int:pk>/claim/", views.claim, name="claim"),
    path("<int:pk>/mod133/", views.mod133_compila, name="mod133_compila"),
    path("<int:pk>/mod133/riga/", views.mod133_riga_add, name="mod133_riga_add"),
    path("<int:pk>/mod133/chiudi/", views.mod133_chiudi, name="mod133_chiudi"),
    path("<int:pk>/mod133/approva/", views.mod133_approva, name="mod133_approva"),
]
