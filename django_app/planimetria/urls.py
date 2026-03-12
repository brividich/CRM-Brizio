from django.urls import path

from . import views

app_name = "planimetria"

urlpatterns = [
    path("planimetria/", views.mappa, name="mappa"),
    path("planimetria/editor/", views.editor, name="editor"),
]
