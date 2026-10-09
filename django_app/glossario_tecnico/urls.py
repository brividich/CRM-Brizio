from django.urls import path

from . import views

app_name = "glossario_tecnico"

urlpatterns = [
    path("", views.index, name="index"),
    path("guida/", views.guida, name="guida"),
    path("termini/nuovo/", views.termine_nuovo, name="termine_nuovo"),
    path("termini/<int:pk>/", views.termine, name="termine"),
    path("termini/<int:pk>/modifica/", views.termine_modifica, name="termine_modifica"),
    path("termini/<int:pk>/varianti/", views.variante_aggiungi, name="variante_aggiungi"),
    path("varianti/<int:pk>/elimina/", views.variante_elimina, name="variante_elimina"),
    path("revisione/", views.revisione, name="revisione"),
    path("revisione/proposte/<int:pk>/", views.proposta_decidi, name="proposta_decidi"),
    path("api/cerca/", views.api_cerca, name="api_cerca"),
    path("api/termini/<int:pk>/stato/", views.api_stato, name="api_stato"),
]
