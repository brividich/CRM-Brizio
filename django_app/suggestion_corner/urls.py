from django.urls import path

from . import views

app_name = "suggestion_corner"

urlpatterns = [
    path("", views.home, name="home"),
    path("<int:pk>/", views.dettaglio, name="dettaglio"),
]
