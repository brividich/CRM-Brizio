from django.urls import path

from . import views

app_name = "produzione"

urlpatterns = [
    path("", views.elenco, name="elenco"),
    path("op/nuovo/", views.op_nuovo, name="op_nuovo"),
    path("op/<int:pk>/", views.scheda, name="scheda"),
    path("op/<int:pk>/documento/", views.documento, name="documento"),
    path("op/<int:pk>/documento/<int:doc_id>/elimina/", views.documento_elimina, name="documento_elimina"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("guida/", views.guida, name="guida"),
]
