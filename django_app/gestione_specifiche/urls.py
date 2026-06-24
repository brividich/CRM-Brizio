from django.urls import path

from . import views

app_name = "gestione_specifiche"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("allegato/<int:pk>/", views.allegato_download, name="allegato_download"),
]
