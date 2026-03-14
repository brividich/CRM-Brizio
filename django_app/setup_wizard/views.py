"""
Views del Setup Wizard BrizioHUB.

Endpoints:
  GET  /setup/              → wizard_home  (renderizza il wizard)
  POST /setup/api/test-db/  → test connessione SQL Server via pyodbc
  POST /setup/api/test-ldap/ → test connessione LDAP/AD
  POST /setup/api/test-smtp/ → test connessione SMTP
  POST /setup/api/save/     → salva .env e config.ini, marca setup completato
"""
import base64
import json
import secrets
import smtplib
import socket
import string
from pathlib import Path

from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

# Percorsi assoluti calcolati relativamente a questo file
# setup_wizard/views.py → django_app/ → progetto root
_APP_DIR = Path(__file__).resolve().parent.parent       # django_app/
_PROJECT_DIR = _APP_DIR.parent                          # root repo
_ENV_PATH = _APP_DIR / ".env"
_CONFIG_INI_PATH = _PROJECT_DIR / "config.ini"
_BRANDING_DIR = _APP_DIR / "core" / "static" / "core" / "img"


def _setup_needed() -> bool:
    if not _ENV_PATH.exists():
        return True
    for raw in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("SETUP_COMPLETED="):
            val = line.split("=", 1)[1].strip().strip("'\"")
            return val not in ("1", "true", "yes")
    return True


# ── Pagina wizard ─────────────────────────────────────────────────────────────

@require_GET
def wizard_home(request):
    if not _setup_needed():
        return redirect("/")
    return render(request, "setup_wizard/wizard.html")


# ── Helper JSON ───────────────────────────────────────────────────────────────

def _parse_json(request):
    try:
        return json.loads(request.body), None
    except Exception:
        return None, {"ok": False, "error": "JSON non valido"}


# ── Test connessione DB ────────────────────────────────────────────────────────

@require_POST
def api_test_db(request):
    data, err = _parse_json(request)
    if err:
        return _json(err)

    engine = (data.get("engine") or "sqlserver").strip().lower()
    if engine != "sqlserver":
        return _json({"ok": True, "message": "SQLite non richiede test di connessione."})

    host = (data.get("host") or "").strip()
    db_name = (data.get("name") or "").strip()
    user = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()
    driver = (data.get("driver") or "ODBC Driver 18 for SQL Server").strip()
    trust_cert = bool(data.get("trust_cert"))

    if not host:
        return _json({"ok": False, "error": "Host non specificato"})

    try:
        import pyodbc
    except ImportError:
        return _json({"ok": False, "error": "pyodbc non installato sul server"})

    try:
        trust = "yes" if trust_cert else "no"
        if user:
            conn_str = (
                f"DRIVER={{{driver}}};SERVER={host};DATABASE={db_name};"
                f"UID={user};PWD={password};TrustServerCertificate={trust};"
            )
        else:
            conn_str = (
                f"DRIVER={{{driver}}};SERVER={host};DATABASE={db_name};"
                f"Trusted_Connection=yes;TrustServerCertificate={trust};"
            )
        conn = pyodbc.connect(conn_str, timeout=6)
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = (cursor.fetchone()[0] or "").split("\n")[0][:80]
        conn.close()
        return _json({"ok": True, "message": f"Connessione riuscita.\n{version}"})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


# ── Test connessione LDAP ─────────────────────────────────────────────────────

@require_POST
def api_test_ldap(request):
    data, err = _parse_json(request)
    if err:
        return _json(err)

    server = (data.get("server") or "").strip()
    service_user = (data.get("service_user") or "").strip()
    service_password = (data.get("service_password") or "").strip()
    timeout = int(data.get("timeout") or 5)

    if not server:
        return _json({"ok": False, "error": "Server LDAP non specificato"})

    # Prova con ldap3 (libreria preferita)
    try:
        import ldap3
        srv = ldap3.Server(server, connect_timeout=timeout, get_info=ldap3.NONE)
        kwargs = {"auto_bind": True}
        if service_user:
            kwargs["user"] = service_user
            kwargs["password"] = service_password
        conn = ldap3.Connection(srv, **kwargs)
        conn.unbind()
        return _json({"ok": True, "message": f"Connessione LDAP riuscita a {server}"})
    except ImportError:
        pass
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})

    # Fallback: test porta TCP
    try:
        host = server.replace("ldaps://", "").replace("ldap://", "").split(":")[0]
        port = 636 if "ldaps://" in server else 389
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return _json({
            "ok": True,
            "message": f"Porta {port} raggiungibile su {host} (ldap3 non installato — bind non testato)"
        })
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


# ── Test connessione SMTP ─────────────────────────────────────────────────────

@require_POST
def api_test_smtp(request):
    data, err = _parse_json(request)
    if err:
        return _json(err)

    host = (data.get("host") or "").strip()
    port = int(data.get("port") or 587)
    user = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()
    use_tls = bool(data.get("use_tls", True))

    if not host:
        return _json({"ok": False, "error": "Host SMTP non specificato"})

    try:
        smtp = smtplib.SMTP(host, port, timeout=8)
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.quit()
        return _json({"ok": True, "message": f"Connessione SMTP riuscita a {host}:{port}"})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


# ── Salvataggio configurazione ────────────────────────────────────────────────

@require_POST
def api_save(request):
    if not _setup_needed():
        return _json({"ok": False, "error": "Setup già completato. Riavvia il server per riconfigurare."})

    data, err = _parse_json(request)
    if err:
        return _json(err)

    errors = []

    # ── Salva logo aziendale ──────────────────────────────────────────────────
    branding_logo_path = ""
    logo_b64 = (data.get("logo_b64") or "").strip()
    logo_ext = (data.get("logo_ext") or "png").strip().lower().lstrip(".")
    if logo_b64:
        try:
            _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
            logo_bytes = base64.b64decode(logo_b64)
            logo_file = _BRANDING_DIR / f"branding_logo.{logo_ext}"
            logo_file.write_bytes(logo_bytes)
            branding_logo_path = f"core/img/branding_logo.{logo_ext}"
        except Exception as exc:
            errors.append(f"Logo: {exc}")

    # ── Salva favicon ─────────────────────────────────────────────────────────
    branding_favicon_path = ""
    favicon_b64 = (data.get("favicon_b64") or "").strip()
    favicon_ext = (data.get("favicon_ext") or "ico").strip().lower().lstrip(".")
    if favicon_b64:
        try:
            _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
            fav_bytes = base64.b64decode(favicon_b64)
            fav_file = _BRANDING_DIR / f"branding_favicon.{favicon_ext}"
            fav_file.write_bytes(fav_bytes)
            branding_favicon_path = f"core/img/branding_favicon.{favicon_ext}"
        except Exception as exc:
            errors.append(f"Favicon: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def b(key, default=False):
        return "1" if data.get(key, default) else "0"

    def s(key, default=""):
        return str(data.get(key) or default).strip()

    # Genera SECRET_KEY se mancante o CHANGE_ME
    secret_key = s("secret_key")
    if not secret_key or secret_key.upper() in ("CHANGE_ME", "CHANGE_ME_FROM_ENV"):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*(-_=+)"
        secret_key = "".join(secrets.choice(alphabet) for _ in range(50))

    instance_name = s("instance_name", "BrizioHUB")
    ldap_enabled_ini = "true" if data.get("ldap_enabled") else "false"

    # ── Costruisce .env ───────────────────────────────────────────────────────
    env_lines = f"""\
# ── BrizioHUB — Configurazione generata dal Setup Wizard ──────────────────────
INSTANCE_NAME={instance_name}
DJANGO_SECRET_KEY={secret_key}
APP_VERSION={s('app_version', '0.6.40')}
DJANGO_DEBUG={b('debug')}
DJANGO_ALLOWED_HOSTS={s('allowed_hosts')}
SETUP_COMPLETED=1

# Branding
BRANDING_LOGO={branding_logo_path}
BRANDING_FAVICON={branding_favicon_path}

# Sicurezza HTTPS (impostare a 1 solo se il server usa HTTPS con certificato valido)
SECURE_SSL_REDIRECT={b('secure_ssl')}
CSRF_COOKIE_SECURE={b('csrf_secure')}
SESSION_COOKIE_SECURE={b('session_secure')}

# Database
DB_ENGINE={s('db_engine', 'sqlserver')}
DB_HOST={s('db_host')}
DB_NAME={s('db_name')}
DB_USER={s('db_user')}
DB_PASSWORD={s('db_password')}
DB_DRIVER={s('db_driver', 'ODBC Driver 18 for SQL Server')}
DB_TRUST_CERT={b('db_trust_cert')}

# Autenticazione e navigazione
LEGACY_AUTH_ENABLED={b('legacy_auth', True)}
NAVIGATION_REGISTRY_ENABLED={b('nav_registry', True)}
NAVIGATION_LEGACY_FALLBACK_ENABLED={b('nav_legacy_fallback')}
ASSENZE_SYNC_ON_PAGE_LOAD={b('assenze_sync')}
SESSION_IDLE_TIMEOUT_SECONDS={s('session_timeout', '3600')}
SESSION_EXPIRE_AT_BROWSER_CLOSE={b('session_expire', True)}
LEGACY_ACL_CACHE_TTL={s('acl_cache_ttl', '120')}
LEGACY_NAV_CACHE_TTL={s('nav_cache_ttl', '120')}

# Active Directory / LDAP
LDAP_ENABLED={b('ldap_enabled')}
LDAP_SERVER={s('ldap_server')}
LDAP_DOMAIN={s('ldap_domain')}
LDAP_UPN_SUFFIX={s('ldap_upn')}
LDAP_TIMEOUT={s('ldap_timeout', '5')}
LDAP_SERVICE_USER={s('ldap_service_user')}
LDAP_SERVICE_PASSWORD={s('ldap_service_password')}
LDAP_BASE_DN={s('ldap_base_dn')}
LDAP_USER_FILTER={s('ldap_user_filter', '(&(objectCategory=person)(objectClass=user))')}
LDAP_GROUP_ALLOWLIST={s('ldap_group_allowlist')}
LDAP_SYNC_PAGE_SIZE={s('ldap_sync_page_size', '500')}

# Microsoft Graph / SharePoint
GRAPH_TENANT_ID={s('graph_tenant_id')}
GRAPH_CLIENT_ID={s('graph_client_id')}
GRAPH_CLIENT_SECRET={s('graph_client_secret')}
GRAPH_SITE_ID={s('graph_site_id')}
GRAPH_LIST_ID_ASSENZE={s('graph_list_assenze')}
GRAPH_LIST_ID_DIPENDENTI={s('graph_list_dipendenti')}
GRAPH_LIST_ID_CAPOREPARTO={s('graph_list_caporeparto')}
GRAPH_LIST_ID_ANOMALIE_DB={s('graph_list_anomalie_db')}

# Assenze
ASSENZE_SP_PULL_INTERVAL_SECONDS={s('assenze_interval', '300')}
ASSENZE_CALENDAR_MAX_EVENTS={s('assenze_max_events', '1500')}
ASSENZE_CALENDAR_COLORS_CACHE_TTL={s('assenze_colors_ttl', '300')}

# SQL logging (disabilitare in produzione)
SQL_LOG_ENABLED=0
SQL_LOG_LEVEL=DEBUG
SQL_LOG_FORCE_DEBUG_CURSOR=0
SQL_LOG_MAX_BYTES=10485760
SQL_LOG_BACKUP_COUNT=10

# SMTP
EMAIL_HOST={s('email_host')}
EMAIL_PORT={s('email_port', '587')}
EMAIL_HOST_USER={s('email_user')}
EMAIL_HOST_PASSWORD={s('email_password')}
EMAIL_USE_TLS={b('email_tls', True)}
DEFAULT_FROM_EMAIL={s('email_from')}
"""

    # ── Costruisce config.ini ─────────────────────────────────────────────────
    ini_lines = f"""\
; BrizioHUB — Configurazione generata dal Setup Wizard

[APP]
debug = False
secret_key = LOADED_FROM_ENV

[ADMIN]
email = admin@example.local
password = CHANGE_ME
nome = Amministratore

[DATABASE]
path = {s('legacy_db_path', 'utenti.db')}

[SQLSERVER]
server = {s('db_host')}
database = {s('db_name')}
driver = {s('db_driver', 'ODBC Driver 18 for SQL Server')}
username = {s('db_user')}
password = {s('db_password')}
encrypt = yes
trust_server_certificate = {'yes' if data.get('db_trust_cert') else 'no'}
login_timeout = 5

[CACHE]
foto_ttl = 600
assenze_ttl = {s('assenze_interval', '300')}
capi_ttl = 600

[ANOMALIE]
draft_temp_dir = temp\\anomalie_drafts
pending_files_dir = temp\\anomalie_pending_sync

[AZIENDA]
tenant_id = {s('graph_tenant_id')}
client_id = {s('graph_client_id')}
client_secret = {s('graph_client_secret')}
site_id = {s('graph_site_id')}
list_id_assenze = {s('graph_list_assenze')}
list_id_dipendenti = {s('graph_list_dipendenti')}
list_id_caporeparto = {s('graph_list_caporeparto')}
list_id_anagrafica =
list_id_anomalie_op =
list_id_anomalie_db = {s('graph_list_anomalie_db')}

[ACTIVE_DIRECTORY]
enabled = {ldap_enabled_ini}
server = {s('ldap_server')}
domain = {s('ldap_domain')}
upn_suffix = {s('ldap_upn')}
timeout = {s('ldap_timeout', '5')}
service_user = {s('ldap_service_user')}
service_password = {s('ldap_service_password')}
base_dn = {s('ldap_base_dn')}
user_filter = {s('ldap_user_filter', '(&(objectCategory=person)(objectClass=user))')}
group_allowlist = {s('ldap_group_allowlist')}

[DEFAULT]
default_password = CHANGE_ME
"""

    try:
        _ENV_PATH.write_text(env_lines, encoding="utf-8")
        _CONFIG_INI_PATH.write_text(ini_lines, encoding="utf-8")
    except PermissionError as exc:
        return _json({"ok": False, "error": f"Permessi insufficienti: {exc}"})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})

    msg = "Configurazione salvata con successo."
    if errors:
        msg += " Avvisi: " + "; ".join(errors)

    return _json({"ok": True, "message": msg, "warnings": errors})


# ── Helper ────────────────────────────────────────────────────────────────────

from django.http import JsonResponse  # noqa: E402 (import at bottom for clarity)


def _json(data: dict) -> JsonResponse:
    return JsonResponse(data)


# ── Esegui migrazioni ─────────────────────────────────────────────────────────

@require_POST
def api_run_migrations(request):
    """Esegue `manage.py migrate` come sottoprocesso dopo il salvataggio del .env."""
    import subprocess
    import sys

    manage_py = _APP_DIR / "manage.py"
    if not manage_py.exists():
        return _json({"ok": False, "error": "manage.py non trovato"})

    # Determina il settings module: se .env ha DB_ENGINE=sqlserver usa prod, altrimenti dev
    settings_module = "config.settings.prod"
    try:
        content = _ENV_PATH.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.strip().startswith("DB_ENGINE=") and "sqlite" in line.lower():
                settings_module = "config.settings.dev"
                break
    except Exception:
        pass

    try:
        result = subprocess.run(
            [sys.executable, str(manage_py), "migrate",
             f"--settings={settings_module}", "--no-input"],
            capture_output=True, text=True, timeout=180, cwd=str(_APP_DIR),
        )
        output = (result.stdout + result.stderr)[-800:]
        if result.returncode == 0:
            return _json({"ok": True, "message": output or "Migrazioni completate."})
        return _json({"ok": False, "error": output or f"Exit code {result.returncode}"})
    except subprocess.TimeoutExpired:
        return _json({"ok": False, "error": "Timeout (180s) — le migrazioni impiegano troppo tempo."})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


# ── Crea utente admin ─────────────────────────────────────────────────────────

@require_POST
def api_create_admin(request):
    """Crea un superuser Django. Richiede che le migrazioni siano già state eseguite."""
    data, err = _parse_json(request)
    if err:
        return _json(err)

    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    email = (data.get("email") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    if not username or not password:
        return _json({"ok": False, "error": "Username e password sono obbligatori"})

    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if User.objects.filter(username=username).exists():
            return _json({
                "ok": True,
                "warning": True,
                "message": f"L'utente '{username}' esiste già — skip creazione."
            })

        User.objects.create_superuser(
            username=username,
            password=password,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        return _json({"ok": True, "message": f"Superuser '{username}' creato con successo."})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


# ── Imposta moduli attivi (SiteConfig) ────────────────────────────────────────

@require_POST
def api_set_modules(request):
    """Scrive le preferenze di visibilità moduli in SiteConfig (DB)."""
    data, err = _parse_json(request)
    if err:
        return _json(err)

    selected = set(data.get("modules") or [])
    all_optional = [
        "assenze", "anomalie", "assets", "tasks", "tickets",
        "notizie", "anagrafica", "automazioni", "timbri", "planimetria",
    ]

    try:
        from core.models import SiteConfig
        for key in all_optional:
            SiteConfig.objects.update_or_create(
                key=f"module_visible_{key}",
                defaults={"value": "1" if key in selected else "0"},
            )
        return _json({"ok": True, "message": f"{len(selected)} moduli attivati."})
    except Exception as exc:
        # Non bloccante: SiteConfig potrebbe non esistere ancora se le migrazioni fallirono
        return _json({"ok": False, "error": str(exc)})
