from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403,F401
from .base import SECRET_KEY, build_database_from_env, env, env_bool, env_list

# â”€â”€ Guard chiave segreta â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Blocca l'avvio se SECRET_KEY non Ã¨ stata impostata nel file .env.
# "change-me-in-dev" Ã¨ il valore di default dichiarato in base.py.
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

# â”€â”€ Guard CSRF_TRUSTED_ORIGINS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Blocca l'avvio se CSRF_TRUSTED_ORIGINS Ã¨ vuoto o contiene ancora il valore
# placeholder di default: in produzione le POST cross-origin dal dominio reale
# verrebbero rifiutate e il placeholder non rappresenta un origin attendibile.
_CSRF_PLACEHOLDER_HOSTS = ("app.example.local", "example.local")
if not CSRF_TRUSTED_ORIGINS or any(
    placeholder in str(origin).lower()
    for origin in CSRF_TRUSTED_ORIGINS
    for placeholder in _CSRF_PLACEHOLDER_HOSTS
):
    raise ImproperlyConfigured(
        "DJANGO_CSRF_TRUSTED_ORIGINS non impostata o ancora sul valore placeholder. "
        "Impostare il dominio reale del server, es. "
        'DJANGO_CSRF_TRUSTED_ORIGINS="https://cnhub-costruzioninovicrom.msappproxy.net" '
        "nel file .env."
    )
DATABASES = {"default": build_database_from_env("sqlserver")}

# â”€â”€ Cache condivisa tra worker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Con 2+ worker IIS, LocMemCache (default Django) Ã¨ per-processo: bump_legacy_cache_version()
# non si propaga agli altri worker. DatabaseCache usa SQL Server come backend condiviso,
# rende cache.incr() atomico e garantisce invalidazione ACL immediata su tutti i worker.
# Setup una-tantum: python manage.py createcachetable
_CACHE_TABLE = env("DJANGO_CACHE_TABLE", "django_cache")
# MAX_ENTRIES deve superare il numero di chunk indicizzati dal RAG: gli embeddings
# (uno per chunk, ~10k col corpus SGI) vivono qui. Se MAX_ENTRIES < #chunk il
# DatabaseCache li cullà di continuo -> ogni rebuild indice ricalcola TUTTI gli
# embedding via TEI (~140s di TTFT). Tienilo ampio (default 50k); env-configurabile.
_CACHE_MAX_ENTRIES = int(env("DJANGO_CACHE_MAX_ENTRIES", "50000") or "50000")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": _CACHE_TABLE,
        "OPTIONS": {
            "MAX_ENTRIES": _CACHE_MAX_ENTRIES,
        },
    }
}

# Cache-busting automatico: appende hash contenuto al nome file (es. theme.abc123.css).
# Quando un file statico cambia, l'URL cambia â†’ il browser scarica sempre la versione aggiornata.
# Richiede che i template usino {% static %} (giÃ  fatto in base.html).
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        # Manifest (cache-busting) ma tollerante ai sourcemap .map mancanti dei
        # vendor (vedi core/storage.py): evita ValueError in collectstatic.
        "BACKEND": "core.storage.ForgivingManifestStaticFilesStorage",
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Forzare HTTPS e HSTS. Commentare se il reverse proxy gestisce giÃ  il redirect.
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

# Header di sicurezza HTTP aggiuntivi
# - nosniff: impedisce il MIME-sniffing del browser sugli allegati serviti dal portale
# - referrer-policy: evita di esporre URL interni a destinazioni esterne
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
