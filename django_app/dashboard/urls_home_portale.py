from django.urls import path
from dashboard import views_home_portale as views

app_name = "home_portale"

urlpatterns = [
    path("", views.home_portale, name="index"),
    path("toggle-locked/", views.toggle_locked, name="toggle_locked"),
    path("activity/recent/", views.activity_recent, name="activity_recent"),
]
