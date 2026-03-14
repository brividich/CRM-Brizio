from django.urls import path

from . import views

urlpatterns = [
    path("", views.wizard_home, name="setup_wizard_home"),
    path("api/test-db/", views.api_test_db, name="setup_api_test_db"),
    path("api/test-ldap/", views.api_test_ldap, name="setup_api_test_ldap"),
    path("api/test-smtp/", views.api_test_smtp, name="setup_api_test_smtp"),
    path("api/save/", views.api_save, name="setup_api_save"),
    path("api/run-migrations/", views.api_run_migrations, name="setup_api_run_migrations"),
    path("api/create-admin/", views.api_create_admin, name="setup_api_create_admin"),
    path("api/set-modules/", views.api_set_modules, name="setup_api_set_modules"),
]
