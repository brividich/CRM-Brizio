import configparser
import logging.handlers  # noqa: F401 — registra il handler per LOGGING dict
import os
import socket
import tempfile
from pathlib import Path

# mssql-django 1.6 non riconosce ancora SQL Server major version 17.
# Trattiamo v17 come compatibile con il profilo 2022 per evitare blocchi in startup.
try:
    from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper

    MSSQLDatabaseWrapper._sql_server_versions.setdefault(17, 2022)
except Exception:
    pass


PROJECT_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_DIR


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(key)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def default_dev_allowed_hosts() -> list[str]:
    hosts = {"127.0.0.1", "::1", "localhost", "testserver"}

    for candidate in {socket.gethostname(), socket.getfqdn()}:
        candidate = (candidate or "").strip()
        if candidate:
            hosts.add(candidate)

    try:
        for _family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        ):
            host = str(sockaddr[0]).strip()
            if host:
                hosts.add(host)
    except OSError:
        pass

    return sorted(hosts)


_load_dotenv(PROJECT_DIR / ".env")


def _load_config_ini(config_path: Path):
    parser = configparser.ConfigParser()
    try:
        if config_path.exists():
            parser.read(config_path, encoding="utf-8")
    except Exception:
        return configparser.ConfigParser()
    return parser


_CONFIG_INI = _load_config_ini(PROJECT_DIR.parent / "config.ini")


def ini_get(section: str, option: str, default: str = "") -> str:
    try:
        if _CONFIG_INI.has_section(section):
            return _CONFIG_INI.get(section, option, fallback=default)
    except Exception:
        pass
    return default


def ini_bool(section: str, option: str, default: bool = False) -> bool:
    try:
        if _CONFIG_INI.has_section(section):
            return _CONFIG_INI.getboolean(section, option, fallback=default)
    except Exception:
        pass
    return default


SECRET_KEY = env("DJANGO_SECRET_KEY", "change-me-in-dev")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"])
APP_VERSION = env("APP_VERSION", "0.6.40-dev")


def build_module_versions(default_version: str) -> dict[str, str]:
    module_env_keys = {
        "core": "APP_VERSION_CORE",
        "dashboard": "APP_VERSION_DASHBOARD",
        "assenze": "APP_VERSION_ASSENZE",
        "anomalie": "APP_VERSION_ANOMALIE",
        "assets": "APP_VERSION_ASSETS",
        "tasks": "APP_VERSION_TASKS",
        "admin_portale": "APP_VERSION_ADMIN_PORTALE",
        "notizie": "APP_VERSION_NOTIZIE",
        "anagrafica": "APP_VERSION_ANAGRAFICA",
        "tickets":    "APP_VERSION_TICKETS",
    }
    versions: dict[str, str] = {}
    for code, env_key in module_env_keys.items():
        versions[code] = env(env_key, default_version).strip() or default_version
    return versions


MODULE_VERSIONS = build_module_versions(APP_VERSION)
LEGACY_AUTH_ENABLED = env_bool("LEGACY_AUTH_ENABLED", True)
NAVIGATION_REGISTRY_ENABLED = env_bool("NAVIGATION_REGISTRY_ENABLED", True)
NAVIGATION_LEGACY_FALLBACK_ENABLED = env_bool("NAVIGATION_LEGACY_FALLBACK_ENABLED", True)
# Layer di presentazione per il branding moduli.
# Precedenza runtime:
# 1. SiteConfig: module_branding.<module_key>.<field>
# 2. settings.MODULE_BRANDING
# 3. default dichiarati nel module registry
# Esempio:
# MODULE_BRANDING = {
#     "assets": {
#         "display_label": "Novicrom Assets",
#         "menu_label": "Novicrom Assets",
#     }
# }
MODULE_BRANDING = {}
LDAP_ENABLED = env_bool("LDAP_ENABLED", ini_bool("ACTIVE_DIRECTORY", "enabled", False))
LDAP_SERVER = env("LDAP_SERVER", ini_get("ACTIVE_DIRECTORY", "server", ""))
LDAP_DOMAIN = env("LDAP_DOMAIN", ini_get("ACTIVE_DIRECTORY", "domain", ""))
LDAP_UPN_SUFFIX = env("LDAP_UPN_SUFFIX", ini_get("ACTIVE_DIRECTORY", "upn_suffix", ""))
LDAP_TIMEOUT = int(env("LDAP_TIMEOUT", ini_get("ACTIVE_DIRECTORY", "timeout", "5")) or "5")
LDAP_SERVICE_USER = env("LDAP_SERVICE_USER", ini_get("ACTIVE_DIRECTORY", "service_user", ""))
LDAP_SERVICE_PASSWORD = env("LDAP_SERVICE_PASSWORD", ini_get("ACTIVE_DIRECTORY", "service_password", ""))
LDAP_BASE_DN = env("LDAP_BASE_DN", ini_get("ACTIVE_DIRECTORY", "base_dn", ""))
LDAP_USER_FILTER = env(
    "LDAP_USER_FILTER",
    ini_get("ACTIVE_DIRECTORY", "user_filter", "(&(objectCategory=person)(objectClass=user))"),
)
LDAP_GROUP_ALLOWLIST = env_list("LDAP_GROUP_ALLOWLIST", [])
LDAP_SYNC_PAGE_SIZE = int(env("LDAP_SYNC_PAGE_SIZE", "500") or "500")
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", ini_get("SMTP", "host", ""))
EMAIL_PORT = int(env("EMAIL_PORT", ini_get("SMTP", "port", "587")) or "587")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", ini_get("SMTP", "user", ""))
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", ini_get("SMTP", "password", ""))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", ini_bool("SMTP", "use_tls", True))
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", ini_bool("SMTP", "use_ssl", False))
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", ini_get("SMTP", "timeout", "10")) or "10")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", ini_get("SMTP", "default_from_email", ""))
SESSION_IDLE_TIMEOUT_SECONDS = int(env("SESSION_IDLE_TIMEOUT_SECONDS", "3600") or "3600")
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", True)
LEGACY_ACL_CACHE_TTL = int(env("LEGACY_ACL_CACHE_TTL", "120") or "120")
LEGACY_NAV_CACHE_TTL = int(env("LEGACY_NAV_CACHE_TTL", "120") or "120")
ASSENZE_SP_PULL_INTERVAL_SECONDS = int(env("ASSENZE_SP_PULL_INTERVAL_SECONDS", "300") or "300")
ASSENZE_SYNC_ON_PAGE_LOAD = env_bool("ASSENZE_SYNC_ON_PAGE_LOAD", False)
ASSENZE_CALENDAR_MAX_EVENTS = int(env("ASSENZE_CALENDAR_MAX_EVENTS", "1500") or "1500")
ANOMALIE_SP_FOLDER_URL = env("ANOMALIE_SP_FOLDER_URL", ini_get("ANOMALIE", "sp_folder_url", "#"))
SQL_LOG_ENABLED = env_bool("SQL_LOG_ENABLED", False)
SQL_LOG_LEVEL = env("SQL_LOG_LEVEL", "DEBUG").strip().upper() or "DEBUG"
SQL_LOG_FORCE_DEBUG_CURSOR = env_bool("SQL_LOG_FORCE_DEBUG_CURSOR", SQL_LOG_ENABLED)
SQL_LOG_MAX_BYTES = int(env("SQL_LOG_MAX_BYTES", str(10 * 1024 * 1024)) or str(10 * 1024 * 1024))
SQL_LOG_BACKUP_COUNT = int(env("SQL_LOG_BACKUP_COUNT", "10") or "10")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "dashboard.apps.DashboardConfig",
    "assenze.apps.AssenzeConfig",
    "anomalie.apps.AnomalieConfig",
    "assets.apps.AssetsConfig",
    "tasks.apps.TasksConfig",
    "automazioni.apps.AutomazioniConfig",
    "admin_portale.apps.AdminPortaleConfig",
    "notizie.apps.NotizieConfig",
    "anagrafica.apps.AnagraficaConfig",
    "timbri.apps.TimbriConfig",
    "planimetria.apps.PlanimetriaConfig",
    "tickets.apps.TicketsConfig",
    "django_extensions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.AdaptiveSecureCookieMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "core.csrf_cookie_middleware.EnsureCSRFCookieMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.ImpersonationMiddleware",
    "core.session_middleware.SessionIdleTimeoutMiddleware",
    "core.middleware.ACLMiddleware",
    "notizie.mandatory_middleware.NotizieMandatoryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.legacy_nav",
                "core.context_processors.app_meta",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def build_sqlite_database() -> dict:
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


def build_sqlserver_database() -> dict:
    driver = env("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    db_user = env("DB_USER", "")
    db_password = env("DB_PASSWORD", "")
    # TrustServerCertificate: default True solo in dev (DB_TRUST_CERT=1).
    # In produzione lasciare non impostato o DB_TRUST_CERT=0 per verificare il certificato SSL.
    trust_cert = env_bool("DB_TRUST_CERT", False)
    extra_params = f"TrustServerCertificate={'yes' if trust_cert else 'no'};"
    if not db_user:
        extra_params += "Trusted_Connection=yes;"

    return {
        "ENGINE": "mssql",
        "NAME": env("DB_NAME", ""),
        "HOST": env("DB_HOST", ""),
        "USER": db_user,
        "PASSWORD": db_password,
        "OPTIONS": {
            "driver": driver,
            "extra_params": extra_params,
        },
    }


def build_database_from_env(default_engine: str = "sqlite") -> dict:
    engine = env("DB_ENGINE", default_engine).strip().lower()
    if engine == "sqlserver":
        return build_sqlserver_database()
    return build_sqlite_database()


DATABASES = {"default": build_database_from_env("sqlite")}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "it-it"
TIME_ZONE = env("TIME_ZONE", "Europe/Rome")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CSRF_FAILURE_VIEW = "core.views.csrf_failure"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard_home"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_AGE = max(300, SESSION_IDLE_TIMEOUT_SECONDS) if SESSION_IDLE_TIMEOUT_SECONDS > 0 else 1209600

# IP dei reverse proxy fidati. Solo se REMOTE_ADDR è in questo set, X-Forwarded-For viene accettato.
# Esempio: TRUSTED_PROXY_IPS = {"127.0.0.1", "192.0.2.10"}
TRUSTED_PROXY_IPS: set[str] = set(env_list("TRUSTED_PROXY_IPS", []))

# Prefissi URL esenti da autenticazione e timeout di sessione (usati da entrambi i middleware).
MIDDLEWARE_EXEMPT_PREFIXES = (
    "/health",
    "/version",
    "/login",
    "/logout",
    "/cambia-password",
    "/static/",
    "/media/",
    "/admin/",
    "/favicon",
)

AUTHENTICATION_BACKENDS = [
    "core.accounts.backends.SQLServerLegacyBackend",
    "core.accounts.backends.LDAPBackend",
    "django.contrib.auth.backends.ModelBackend",
]


_default_log_dir = Path(tempfile.gettempdir()) / "portale_novicrom_logs"
LOG_DIR = Path(os.environ.get("DJANGO_LOG_DIR", str(_default_log_dir)))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "file": {
            "class": "core.logging_handlers.SafeTimedRotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "formatter": "standard",
            "encoding": "utf-8",
            "when": "midnight",
            "backupCount": 5,
        },
        "sql_file": {
            "class": "core.logging_handlers.SafeTimedRotatingFileHandler",
            "filename": str(LOG_DIR / "sql.log"),
            "formatter": "standard",
            "encoding": "utf-8",
            "when": "midnight",
            "backupCount": SQL_LOG_BACKUP_COUNT,
        },
    },
    "loggers": {
        "django.db.backends": {
            "handlers": ["sql_file"],
            "level": SQL_LOG_LEVEL if SQL_LOG_ENABLED else "WARNING",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
}
