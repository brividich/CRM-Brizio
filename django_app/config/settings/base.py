import logging.handlers  # noqa: F401 — registra il handler per LOGGING dict
import os
import socket
import tempfile
from pathlib import Path

from config.app_version import (
    DEFAULT_APP_VERSION,
    MODULE_ENV_KEYS_BY_CODE,
    load_app_version,
)
from config.env_config import iter_runtime_env_paths, load_dotenv_into_environ

# mssql-django 1.6 non riconosce ancora SQL Server major version 17.
# Trattiamo v17 come compatibile con il profilo 2022 per evitare blocchi in startup.
try:
    from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper

    MSSQLDatabaseWrapper._sql_server_versions.setdefault(17, 2022)
except Exception:
    pass


PROJECT_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_DIR


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


for _dotenv_path in iter_runtime_env_paths(PROJECT_DIR):
    load_dotenv_into_environ(_dotenv_path)


SECRET_KEY = env("DJANGO_SECRET_KEY", "change-me-in-dev")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"])
APP_VERSION = env("APP_VERSION", load_app_version(DEFAULT_APP_VERSION))
SETUP_WIZARD_REQUIRED = env_bool("SETUP_WIZARD_REQUIRED", True)

# ── Branding istanza ──────────────────────────────────────────────────────────
# INSTANCE_NAME: nome visualizzato nell'interfaccia (es. "NOVICROM HUB").
# Puoi personalizzarlo per singola installazione senza cambiare il brand documentale.
INSTANCE_NAME = env("INSTANCE_NAME", "NOVICROM HUB")
BRANDING_LOGO = env("BRANDING_LOGO", "")    # percorso relativo a STATICFILES (es. core/img/branding_logo.png)
BRANDING_FAVICON = env("BRANDING_FAVICON", "")  # percorso relativo a STATICFILES


def build_module_versions(default_version: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for code, env_key in MODULE_ENV_KEYS_BY_CODE.items():
        versions[code] = env(env_key, default_version).strip() or default_version
    return versions


MODULE_VERSIONS = build_module_versions(APP_VERSION)
LEGACY_AUTH_ENABLED = env_bool("LEGACY_AUTH_ENABLED", True)
NAVIGATION_REGISTRY_ENABLED = env_bool("NAVIGATION_REGISTRY_ENABLED", True)
NAVIGATION_LEGACY_FALLBACK_ENABLED = env_bool("NAVIGATION_LEGACY_FALLBACK_ENABLED", False)
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
LDAP_ENABLED = env_bool("LDAP_ENABLED", False)
LDAP_SERVER = env("LDAP_SERVER", "")
LDAP_DOMAIN = env("LDAP_DOMAIN", "")
LDAP_UPN_SUFFIX = env("LDAP_UPN_SUFFIX", "")
LDAP_TIMEOUT = int(env("LDAP_TIMEOUT", "5") or "5")
LDAP_SERVICE_USER = env("LDAP_SERVICE_USER", "")
LDAP_SERVICE_PASSWORD = env("LDAP_SERVICE_PASSWORD", "")
LDAP_BASE_DN = env("LDAP_BASE_DN", "")
LDAP_USER_FILTER = env("LDAP_USER_FILTER", "(&(objectCategory=person)(objectClass=user))")
LDAP_GROUP_ALLOWLIST = env_list("LDAP_GROUP_ALLOWLIST", [])
LDAP_SYNC_PAGE_SIZE = int(env("LDAP_SYNC_PAGE_SIZE", "500") or "500")
WINDOWS_SSO_HOSTNAME = env("WINDOWS_SSO_HOSTNAME", "").strip()
WINDOWS_SSO_SERVICE = env("WINDOWS_SSO_SERVICE", "HTTP").strip() or "HTTP"
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587") or "587")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "10") or "10")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "")
SITE_URL = env("SITE_URL", "")
SESSION_IDLE_TIMEOUT_SECONDS = int(env("SESSION_IDLE_TIMEOUT_SECONDS", "3600") or "3600")
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", True)
LEGACY_ACL_CACHE_TTL = int(env("LEGACY_ACL_CACHE_TTL", "120") or "120")
LEGACY_NAV_CACHE_TTL = int(env("LEGACY_NAV_CACHE_TTL", "120") or "120")
# ACL v2 — governance migrazione legacy → canonico.
# ACL_STRICT_CANONICAL=True nega l'accesso quando il resolver cadrebbe nel
# fallback legacy (no RoutePermissionBinding per il path). Abilitare in
# staging/UAT per scovare le route ancora non coperte da binding canonico
# prima di attivarlo in prod. Default False per compat durante la migrazione.
ACL_STRICT_CANONICAL = env_bool("ACL_STRICT_CANONICAL", False)
# ACL_LOG_LEGACY_FALLBACK=True emette un warning throttled (5m) per ogni
# route che risolve via fallback legacy, anche quando l'accesso è consentito.
# Permette di misurare l'uso effettivo del fallback e decidere quando
# attivare ACL_STRICT_CANONICAL in prod. Default True in ambiente test/UAT.
ACL_LOG_LEGACY_FALLBACK = env_bool("ACL_LOG_LEGACY_FALLBACK", True)
ASSENZE_SP_PULL_INTERVAL_SECONDS = int(env("ASSENZE_SP_PULL_INTERVAL_SECONDS", "300") or "300")
ASSENZE_SYNC_ON_PAGE_LOAD = env_bool("ASSENZE_SYNC_ON_PAGE_LOAD", False)
ASSENZE_CALENDAR_MAX_EVENTS = int(env("ASSENZE_CALENDAR_MAX_EVENTS", "1500") or "1500")
ANOMALIE_SP_FOLDER_URL = env("ANOMALIE_SP_FOLDER_URL", "#")
SQL_LOG_ENABLED = env_bool("SQL_LOG_ENABLED", False)
SQL_LOG_LEVEL = env("SQL_LOG_LEVEL", "DEBUG").strip().upper() or "DEBUG"
SQL_LOG_FORCE_DEBUG_CURSOR = env_bool("SQL_LOG_FORCE_DEBUG_CURSOR", SQL_LOG_ENABLED)
SQL_LOG_MAX_BYTES = int(env("SQL_LOG_MAX_BYTES", str(10 * 1024 * 1024)) or str(10 * 1024 * 1024))
SQL_LOG_BACKUP_COUNT = int(env("SQL_LOG_BACKUP_COUNT", "10") or "10")
MONITORING_ENABLED = env_bool("MONITORING_ENABLED", True)
MONITORING_CAPTURE_403 = env_bool("MONITORING_CAPTURE_403", True)
MONITORING_CAPTURE_404 = env_bool("MONITORING_CAPTURE_404", False)
MONITORING_SLOW_REQUEST_THRESHOLD_MS = int(env("MONITORING_SLOW_REQUEST_THRESHOLD_MS", "3000") or "3000")
MONITORING_NOTIFY_CRITICAL_BY_EMAIL = env_bool("MONITORING_NOTIFY_CRITICAL_BY_EMAIL", True)
MONITORING_ENVIRONMENT = env(
    "MONITORING_ENVIRONMENT",
    env("DJANGO_ENV", "development" if DEBUG else "production"),
).strip()
MONITORING_ADMIN_EMAILS = env_list("MONITORING_ADMIN_EMAILS", [])
MONITORING_EMAIL_RATE_LIMIT_SECONDS = int(env("MONITORING_EMAIL_RATE_LIMIT_SECONDS", "1800") or "1800")
MONITORING_WATCHDOG_CRITICAL_UNASSIGNED_MINUTES = int(
    env("MONITORING_WATCHDOG_CRITICAL_UNASSIGNED_MINUTES", "120") or "120"
)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "setup_wizard.apps.SetupWizardConfig",
    "hub_tools.apps.HubToolsConfig",
    "core.apps.CoreConfig",
    "dashboard.apps.DashboardConfig",
    "assenze.apps.AssenzeConfig",
    "anomalie.apps.AnomalieConfig",
    "assets.apps.AssetsConfig",
    "tasks.apps.TasksConfig",
    "automazioni.apps.AutomazioniConfig",
    "monitoring.apps.MonitoringConfig",
    "admin_portale.apps.AdminPortaleConfig",
    "notizie.apps.NotizieConfig",
    "anagrafica.apps.AnagraficaConfig",
    "timbri.apps.TimbriConfig",
    "planimetria.apps.PlanimetriaConfig",
    "tickets.apps.TicketsConfig",
    "rentri.apps.RentriConfig",
    "diario_preposto.apps.DiarioPrepostoConfig",
    "rilevazione_incidenti.apps.RilevazioneIncidentiConfig",
    "dpi.apps.DpiConfig",
    "procedure_refresh.apps.ProcedureRefreshConfig",
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
    "axes.middleware.AxesMiddleware",
    "core.middleware.ImpersonationMiddleware",
    "monitoring.middleware.IssueCaptureMiddleware",
    "core.session_middleware.SessionIdleTimeoutMiddleware",
    "setup_wizard.middleware.SetupRequiredMiddleware",   # ← prima di ACL/notizie
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
                "core.context_processors.ui_prefs_context",
                "monitoring.context_processors.monitoring_ui",
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
    if engine in ("sqlserver", "mssql"):
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
STATIC_ROOT = Path(env("STATIC_ROOT", str(BASE_DIR / "staticfiles")))

MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
MEDIA_URL = "/media/"

# ── Backup automatico ────────────────────────────────────────────────────────
# BACKUP_DIR: directory radice dove vengono salvati i backup automatici.
# In produzione il wizard imposta: C:\PortaleNovicrom\shared\backups\<env>
# In dev il default è accanto a django_app/ → ../backups
BACKUP_DIR = Path(env("BACKUP_DIR", str(BASE_DIR.parent / "backups")))
# BACKUP_RETENTION: quanti backup mantenere (i più vecchi vengono eliminati)
BACKUP_RETENTION = int(env("BACKUP_RETENTION", "10") or "10")

# Immagini timbri/firme: cartella privata, MAI servita dal web server.
# Il web server (IIS/nginx) non deve avere accesso a questa directory.
TIMBRI_PRIVATE_ROOT = BASE_DIR / "media_private"
# Allegati ticket: storage privato con fallback compatibile sui file legacy in MEDIA_ROOT.
TICKETS_PRIVATE_ROOT = Path(env("TICKETS_PRIVATE_ROOT", str(BASE_DIR / "media_private")))

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
    "/check",
    "/login",
    "/logout",
    "/cambia-password",
    "/static/",
    "/media/",
    "/admin/",
    "/favicon",
    "/setup/",
    "/admin-portale/hub/",
    "/monitoring/report-problem/",
    "/admin-portale/automazioni/approvazione/",
    "/automazioni/approvazione/",  # token-based, no login required
    "/approval-actions/",          # token-based, Entra Application Proxy frontend
)

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "core.accounts.backends.SQLServerLegacyBackend",
    "core.accounts.backends.LDAPBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "core/pages/lockout.html"


_default_log_dir = Path(tempfile.gettempdir()) / "briziohub_logs"
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
