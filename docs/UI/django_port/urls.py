"""
home_portale/urls.py
Wire-up suggerito in `django_app/urls.py`:

    path("hub/home/", include(("home_portale.urls", "home_portale"))),
"""
from django.urls import path
from .views import home_portale

app_name = "home_portale"

urlpatterns = [
    path("",                              home_portale.home_portale,        name="index"),
    path("toggle-locked/",                home_portale.toggle_locked,       name="toggle_locked"),
    path("activity/recent/",              home_portale.activity_recent,     name="activity_recent"),
    path("approve/<str:kind>/<int:pk>/<str:action>/",
         home_portale.approval_decide,    name="approval_decide"),
]
