from .base import *  # noqa: F403,F401
from .base import build_database_from_env, default_dev_allowed_hosts, env, env_bool, env_list


DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default_dev_allowed_hosts())
DATABASES = {"default": build_database_from_env("sqlite")}
SETUP_WIZARD_REQUIRED = env_bool("SETUP_WIZARD_REQUIRED", False)

# In sviluppo le email vanno stampate a CONSOLE, non inviate via SMTP reale
# (override sempre possibile con EMAIL_BACKEND nel .env). Evita invii accidentali
# dallo sviluppo e rende visibili gli errori di composizione.
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEV_SERVE_STATIC_AND_MEDIA = env_bool("DJANGO_DEV_SERVE_STATIC_AND_MEDIA", True)

# Mai redirigere a HTTPS in sviluppo locale — evita che i browser cachino una 301
# verso HTTPS rendendo impossibile ricevere il cookie CSRF su HTTP.
SECURE_SSL_REDIRECT = False

# Disabilita header COOP su HTTP: inutile su origine non-sicura e genera warning in console.
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

# Permetti accesso CSRF da IP locali (necessario da Django 4.0+)
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    ["http://127.0.0.1:8000", "http://localhost:8000"],
)

Q_CLUSTER = {
    "name": "novicrom_hub_dev",
    "workers": 1,
    "timeout": 60,
    "retry": 90,
    "save_limit": 100,
    "max_attempts": 2,
    "orm": "default",
}
