from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403,F401
from .base import SECRET_KEY, build_database_from_env, env, env_bool, env_list

# ── Guard chiave segreta ───────────────────────────────────────────────────────
# Blocca l'avvio se SECRET_KEY non è stata impostata nel file .env.
# "change-me-in-dev" è il valore di default dichiarato in base.py.
if SECRET_KEY == "change-me-in-dev":
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY non impostata. "
        "Generare una chiave sicura (es. 'python -c \"from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())\"') "
        "e aggiungerla al file .env come DJANGO_SECRET_KEY=..."
    )

DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", [])
SETUP_WIZARD_REQUIRED = env_bool("SETUP_WIZARD_REQUIRED", True)

# Necessario da Django 4.0+. In prod deve includere il dominio/IP del server.
# Override via variabile DJANGO_CSRF_TRUSTED_ORIGINS="https://app.example.local"
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    ["https://app.example.local"],
)
DATABASES = {"default": build_database_from_env("sqlserver")}

# ── Cache condivisa tra worker ─────────────────────────────────────────────────
# Con 2+ worker IIS, LocMemCache (default Django) è per-processo: bump_legacy_cache_version()
# non si propaga agli altri worker. DatabaseCache usa SQL Server come backend condiviso,
# rende cache.incr() atomico e garantisce invalidazione ACL immediata su tutti i worker.
# Setup una-tantum: python manage.py createcachetable
_CACHE_TABLE = env("DJANGO_CACHE_TABLE", "django_cache")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": _CACHE_TABLE,
        "OPTIONS": {
            "MAX_ENTRIES": 5000,
        },
    }
}

# Cache-busting automatico: appende hash contenuto al nome file (es. theme.abc123.css).
# Quando un file statico cambia, l'URL cambia → il browser scarica sempre la versione aggiornata.
# Richiede che i template usino {% static %} (già fatto in base.html).
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Forzare HTTPS e HSTS. Commentare se il reverse proxy gestisce già il redirect.
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = 31536000          # 1 anno
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Cookie sicuri
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", SECURE_SSL_REDIRECT)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"
