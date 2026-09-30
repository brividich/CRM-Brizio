from __future__ import annotations

from django.urls import path

from . import views

app_name = "report_conformita"

urlpatterns = [
    path("", views.index, name="index"),
    path("riesame/", views.riesame, name="riesame"),
    path("<slug:slug>/", views.report, name="report"),
]
