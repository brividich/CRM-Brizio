from django.urls import path

from . import views

app_name = "twofa"

urlpatterns = [
    path("verifica/", views.verify, name="verify"),
    path("setup/totp/", views.setup_totp, name="setup_totp"),
    path("resend-otp/", views.resend_otp, name="resend_otp"),
]
