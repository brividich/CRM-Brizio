from django.urls import path
from dashboard import views_home_portale as views

app_name = "home_portale"

urlpatterns = [
    path("", views.home_portale, name="index"),
    path("guida/", views.home_guida, name="guida"),
    path("toggle-locked/", views.toggle_locked, name="toggle_locked"),
    path("activity/recent/", views.activity_recent, name="activity_recent"),
    path("mie-attivita/", views.mie_attivita_blocco, name="mie_attivita_blocco"),
]
