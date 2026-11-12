from django.urls import path

from . import views_chiosco

app_name = "chiosco"

urlpatterns = [
    path("", views_chiosco.pagina, name="pagina"),
    path("logo/", views_chiosco.logo, name="logo"),
    path("foto/<int:pk>/", views_chiosco.foto_referente, name="foto_referente"),
    path("api/<slug:azione>/", views_chiosco.api, name="api"),
]
