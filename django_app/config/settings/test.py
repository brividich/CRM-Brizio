from .base import *  # noqa: F403,F401
from .base import BASE_DIR, default_dev_allowed_hosts


_TEST_DB_DIR = BASE_DIR / ".tmp_tests"
_TEST_DB_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = "test-key"

DEBUG = False
ALLOWED_HOSTS = default_dev_allowed_hosts()
SETUP_WIZARD_REQUIRED = False
SECURE_SSL_REDIRECT = False
SECURE_CROSS_ORIGIN_OPENER_POLICY = None
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# Il profilo test deve ignorare sempre DB_ENGINE del file .env:
# la suite locale/CI usa SQLite in modo esplicito e ripetibile.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _TEST_DB_DIR / "runtime.sqlite3",
        "TEST": {
            "NAME": _TEST_DB_DIR / "suite.sqlite3",
        },
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "novicrom-test-cache",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
