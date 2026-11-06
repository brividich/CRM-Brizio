from django.urls import path

from . import views_chiosco

app_name = "chiosco"

urlpatterns = [
    path("", views_chiosco.pagina, name="pagina"),
    path("api/<slug:azione>/", views_chiosco.api, name="api"),
]
