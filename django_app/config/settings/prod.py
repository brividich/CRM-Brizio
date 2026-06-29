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

# ── Guard CSRF_TRUSTED_ORIGINS ─────────────────────────────────────────────────
# Blocca l'avvio se CSRF_TRUSTED_ORIGINS è vuoto o contiene ancora il valore
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

# ── Guard chiave di cifratura documenti ────────────────────────────────────────
# Gli storage privati (referti medici, contratti, consegne DPI, allegati riservati)
# cifrano at-rest SOLO se DOCUMENT_ENCRYPTION_KEY è impostata: core.encrypted_storage
# è fail-open (senza chiave scrive i file IN CHIARO, senza errori). In produzione la
# chiave DEVE esistere ed essere una chiave Fernet valida, altrimenti i documenti
# sensibili verrebbero salvati in chiaro silenziosamente. Generazione:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
from .base import DOCUMENT_ENCRYPTION_KEY  # noqa: E402
_doc_key = str(DOCUMENT_ENCRYPTION_KEY or "").strip()
if not _doc_key:
    raise ImproperlyConfigured(
        "DOCUMENT_ENCRYPTION_KEY non impostata: i documenti sensibili verrebbero "
        "salvati in chiaro. Generare una chiave Fernet e aggiungerla al file .env "
        "come DOCUMENT_ENCRYPTION_KEY=..."
    )
try:
    from cryptography.fernet import Fernet as _Fernet
    _Fernet(_doc_key.encode())
except ImproperlyConfigured:
    raise
except Exception as _exc:
    raise ImproperlyConfigured(
        f"DOCUMENT_ENCRYPTION_KEY non è una chiave Fernet valida: {_exc}"
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

# Header di sicurezza HTTP aggiuntivi
# - nosniff: impedisce il MIME-sniffing del browser sugli allegati serviti dal portale
# - referrer-policy: evita di esporre URL interni a destinazioni esterne
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
