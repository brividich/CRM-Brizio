"""
Views del Setup Wizard NOVICROM HUB.

Endpoints:
  GET  /setup/              → wizard_home  (renderizza il wizard)
  POST /setup/api/test-db/  → test connessione SQL Server via pyodbc
  POST /setup/api/test-ldap/ → test connessione LDAP/AD
  POST /setup/api/test-smtp/ → test connessione SMTP
  POST /setup/api/save/     → salva .env, marca setup completato
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
from config.app_version import build_module_version_env_block, load_app_version
from config.env_config import update_env_file_values

# Percorsi assoluti calcolati relativamente a questo file
# setup_wizard/views.py → django_app/ → progetto root
_APP_DIR = Path(__file__).resolve().parent.parent       # django_app/
_ENV_PATH = _APP_DIR / ".env"
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


# Estensioni immagine ammesse per logo/favicon caricati dal wizard. Funge da
# allowlist anti path-traversal: qualunque valore con separatori di percorso o
# ".." non vi compare e ricade sul default sicuro.
_ALLOWED_BRANDING_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "svg", "ico", "gif"}


def _safe_branding_ext(value, default: str) -> str:
    ext = str(value or default).strip().lower().lstrip(".")
    return ext if ext in _ALLOWED_BRANDING_IMAGE_EXTS else default


def _reject_if_setup_completed():
    """Gli endpoint mutanti/di test del wizard sono attivi SOLO durante la finestra
    di setup. Il prefisso ``/setup/`` è esente da autenticazione e ACL (deve poter
    funzionare prima che esistano utenti e database): per evitare che restino
    raggiungibili da utenti NON autenticati a installazione completata, rispondono
    403 quando ``SETUP_COMPLETED=1``. Per riconfigurare impostare
    ``SETUP_COMPLETED=0`` nel .env e riavviare."""
    if not _setup_needed():
        return _json(
            {"ok": False, "error": "Setup già completato: endpoint non disponibile."},
            status=403,
        )
    return None


# ── Pagina wizard ─────────────────────────────────────────────────────────────

@require_GET
def wizard_home(request):
    if not _setup_needed():
        return redirect("/")
    return render(
        request,
        "setup_wizard/wizard.html",
        {"app_version": load_app_version()},
    )


# ── Helper JSON ───────────────────────────────────────────────────────────────

def _parse_json(request):
    try:
        return json.loads(request.body), None
    except Exception:
        return None, {"ok": False, "error": "JSON non valido"}


def _settings_module_from_env() -> str:
    """Rileva il settings module coerente con il .env appena scritto."""
    settings_module = "config.settings.prod"
    try:
        content = _ENV_PATH.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.strip().startswith("DB_ENGINE=") and "sqlite" in line.lower():
                settings_module = "config.settings.dev"
                break
    except Exception:
        pass
    return settings_module


def _env_uses_sqlserver() -> bool:
    try:
        content = _ENV_PATH.read_text(encoding="utf-8")
    except Exception:
        return True
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("DB_ENGINE="):
            engine = line.split("=", 1)[1].strip().strip("'\"").lower()
            return engine not in {"sqlite", "sqlite3"}
    return True


def _run_manage_command(args: list[str], *, timeout: int = 180) -> tuple[bool, str]:
    import subprocess
    import sys

    manage_py = _APP_DIR / "manage.py"
    if not manage_py.exists():
        return False, "manage.py non trovato"

    try:
        result = subprocess.run(
            [sys.executable, str(manage_py), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_APP_DIR),
        )
    except subprocess.TimeoutExpired:
        return False, f"Timeout ({timeout}s) durante {' '.join(args[:2])}."
    output = (result.stdout + result.stderr)[-1200:]
    if result.returncode == 0:
        return True, output or "Comando completato."
    return False, output or f"Exit code {result.returncode}"


# ── Test connessione DB ────────────────────────────────────────────────────────

@require_POST
def api_test_db(request):
    locked = _reject_if_setup_completed()
    if locked:
        return locked
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
    locked = _reject_if_setup_completed()
    if locked:
        return locked
    data, err = _parse_json(request)
    if err:
        return _json(err)

    server = (data.get("server") or "").strip()
    service_user = (data.get("service_user") or "").strip()
    service_password = (data.get("service_password") or "").strip()
    domain = (data.get("domain") or "").strip()
    upn_suffix = (data.get("upn_suffix") or "").strip()
    timeout = int(data.get("timeout") or 5)

    if not server:
        return _json({"ok": False, "error": "Server LDAP non specificato"})

    # Prova con ldap3 (libreria preferita)
    try:
        import ldap3
        srv = ldap3.Server(server, connect_timeout=timeout, get_info=ldap3.NONE)
        if not service_user:
            conn = ldap3.Connection(srv, auto_bind=False)
            if conn.bind():
                conn.unbind()
                return _json({"ok": True, "message": f"Connessione LDAP riuscita a {server}"})
            return _json({"ok": False, "error": str(conn.result)})

        attempts: list[tuple[str, str | None]] = []
        if "@" in service_user or "\\" in service_user or service_user.upper().startswith(("CN=", "OU=", "DC=")):
            attempts.append((service_user, None))
        else:
            if upn_suffix:
                attempts.append((f"{service_user}@{upn_suffix.lstrip('@')}", None))
            if domain:
                attempts.append((f"{domain}\\{service_user}", ldap3.NTLM))
            attempts.append((service_user, None))

        last_error = ""
        for bind_user, auth in attempts:
            kwargs = {
                "user": bind_user,
                "password": service_password,
                "auto_bind": False,
            }
            if auth:
                kwargs["authentication"] = auth
            conn = ldap3.Connection(srv, **kwargs)
            if conn.bind():
                conn.unbind()
                return _json({"ok": True, "message": f"Connessione LDAP riuscita a {server}"})
            last_error = str(conn.result)
        return _json({"ok": False, "error": last_error or "Bind LDAP non riuscito"})
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
    locked = _reject_if_setup_completed()
    if locked:
        return locked
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
    logo_ext = _safe_branding_ext(data.get("logo_ext"), "png")
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
    favicon_ext = _safe_branding_ext(data.get("favicon_ext"), "ico")
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
        # Rimuove newline/CR/NULL dai valori: impediscono l'iniezione di righe
        # KEY=VALUE aggiuntive nel .env (update_env_file_values scrive raw).
        val = str(data.get(key) or default)
        val = "".join(c for c in val if c not in "\r\n\x00")
        return val.strip()

    # Genera SECRET_KEY se mancante o CHANGE_ME
    secret_key = s("secret_key")
    if not secret_key or secret_key.upper() in ("CHANGE_ME", "CHANGE_ME_FROM_ENV"):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*(-_=+)"
        secret_key = "".join(secrets.choice(alphabet) for _ in range(50))

    instance_name = s("instance_name", "NOVICROM HUB")
    app_version = s("app_version", load_app_version())
    module_version_lines = build_module_version_env_block(app_version)
    env_updates = {
        "INSTANCE_NAME": instance_name,
        "DJANGO_SECRET_KEY": secret_key,
        "APP_VERSION": app_version,
        "DJANGO_DEBUG": b("debug"),
        "DJANGO_ALLOWED_HOSTS": s("allowed_hosts"),
        "SETUP_COMPLETED": "1",
        "BRANDING_LOGO": branding_logo_path,
        "BRANDING_FAVICON": branding_favicon_path,
        "SECURE_SSL_REDIRECT": b("secure_ssl"),
        "CSRF_COOKIE_SECURE": b("csrf_secure"),
        "SESSION_COOKIE_SECURE": b("session_secure"),
        "DB_ENGINE": s("db_engine", "sqlserver"),
        "DB_HOST": s("db_host"),
        "DB_NAME": s("db_name"),
        "DB_USER": s("db_user"),
        "DB_PASSWORD": s("db_password"),
        "DB_DRIVER": s("db_driver", "ODBC Driver 18 for SQL Server"),
        "DB_TRUST_CERT": b("db_trust_cert"),
        "LEGACY_AUTH_ENABLED": b("legacy_auth", True),
        "NAVIGATION_REGISTRY_ENABLED": b("nav_registry", True),
        "NAVIGATION_LEGACY_FALLBACK_ENABLED": b("nav_legacy_fallback"),
        "ASSENZE_SYNC_ON_PAGE_LOAD": b("assenze_sync"),
        "SESSION_IDLE_TIMEOUT_SECONDS": s("session_timeout", "3600"),
        "SESSION_EXPIRE_AT_BROWSER_CLOSE": b("session_expire", True),
        "LEGACY_ACL_CACHE_TTL": s("acl_cache_ttl", "120"),
        "LEGACY_NAV_CACHE_TTL": s("nav_cache_ttl", "120"),
        "LDAP_ENABLED": b("ldap_enabled"),
        "LDAP_SERVER": s("ldap_server"),
        "LDAP_DOMAIN": s("ldap_domain"),
        "LDAP_UPN_SUFFIX": s("ldap_upn"),
        "LDAP_TIMEOUT": s("ldap_timeout", "5"),
        "LDAP_SERVICE_USER": s("ldap_service_user"),
        "LDAP_SERVICE_PASSWORD": s("ldap_service_password"),
        "LDAP_BASE_DN": s("ldap_base_dn"),
        "LDAP_USER_FILTER": s("ldap_user_filter", "(&(objectCategory=person)(objectClass=user))"),
        "LDAP_GROUP_ALLOWLIST": s("ldap_group_allowlist"),
        "LDAP_SYNC_PAGE_SIZE": s("ldap_sync_page_size", "500"),
        "GRAPH_TENANT_ID": s("graph_tenant_id"),
        "GRAPH_CLIENT_ID": s("graph_client_id"),
        "GRAPH_CLIENT_SECRET": s("graph_client_secret"),
        "GRAPH_SITE_ID": s("graph_site_id"),
        "GRAPH_LIST_ID_ASSENZE": s("graph_list_assenze"),
        "GRAPH_LIST_ID_DIPENDENTI": s("graph_list_dipendenti"),
        "GRAPH_LIST_ID_CAPOREPARTO": s("graph_list_caporeparto"),
        "GRAPH_LIST_ID_ANOMALIE_DB": s("graph_list_anomalie_db"),
        "ASSENZE_SP_PULL_INTERVAL_SECONDS": s("assenze_interval", "300"),
        "ASSENZE_CALENDAR_MAX_EVENTS": s("assenze_max_events", "1500"),
        "ASSENZE_CALENDAR_COLORS_CACHE_TTL": s("assenze_colors_ttl", "300"),
        "SQL_LOG_ENABLED": "0",
        "SQL_LOG_LEVEL": "DEBUG",
        "SQL_LOG_FORCE_DEBUG_CURSOR": "0",
        "SQL_LOG_MAX_BYTES": "10485760",
        "SQL_LOG_BACKUP_COUNT": "10",
        "EMAIL_HOST": s("email_host"),
        "EMAIL_PORT": s("email_port", "587"),
        "EMAIL_HOST_USER": s("email_user"),
        "EMAIL_HOST_PASSWORD": s("email_password"),
        "EMAIL_USE_TLS": b("email_tls", True),
        "EMAIL_USE_SSL": "0",
        "EMAIL_TIMEOUT": "10",
        "DEFAULT_FROM_EMAIL": s("email_from"),
    }
    for line in module_version_lines.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_updates[key.strip()] = value.strip()

    try:
        update_env_file_values(
            env_updates,
            dotenv_path=_ENV_PATH,
            delete_keys=["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"],
        )
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


def _json(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status)


# ── Esegui migrazioni ─────────────────────────────────────────────────────────

@require_POST
def api_run_migrations(request):
    """Esegue `manage.py migrate` come sottoprocesso dopo il salvataggio del .env."""
    locked = _reject_if_setup_completed()
    if locked:
        return locked
    settings_module = _settings_module_from_env()

    try:
        ok, output = _run_manage_command(
            ["migrate", f"--settings={settings_module}", "--no-input"],
            timeout=180,
        )
        if ok:
            return _json({"ok": True, "message": output or "Migrazioni completate."})
        return _json({"ok": False, "error": output})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@require_POST
def api_finalize_database(request):
    """Esegue gli step tecnici post-migration necessari a una installazione pronta."""
    locked = _reject_if_setup_completed()
    if locked:
        return locked
    settings_module = _settings_module_from_env()
    sqlserver = _env_uses_sqlserver()
    warnings: list[str] = []
    messages: list[str] = []

    steps: list[tuple[str, list[str], bool, int]] = []
    if sqlserver:
        steps.append((
            "Schema legacy runtime",
            ["ensure_legacy_schema", f"--settings={settings_module}"],
            True,
            240,
        ))
    steps.append((
        "Cache table Django",
        ["createcachetable", f"--settings={settings_module}"],
        False,
        120,
    ))
    if sqlserver:
        steps.extend([
            (
                "Allineamento vincolo assenze",
                ["allinea_tipo_assenza_flessibilita", f"--settings={settings_module}"],
                False,
                120,
            ),
            (
                "Trigger SQL automazioni",
                ["apply_sql_triggers", f"--settings={settings_module}"],
                False,
                180,
            ),
        ])
    steps.extend([
        (
            "Bootstrap ACL v2",
            ["bootstrap_acl_v2", "--import-legacy", "--apply", f"--settings={settings_module}"],
            False,
            240,
        ),
        (
            "Seed descrizioni pulsanti",
            ["seed_pulsanti_descrizioni", f"--settings={settings_module}"],
            False,
            120,
        ),
    ])

    try:
        for label, args, blocking, timeout in steps:
            ok, output = _run_manage_command(args, timeout=timeout)
            if ok:
                messages.append(f"{label}: OK")
                continue
            detail = f"{label}: {output}"
            if blocking:
                return _json({"ok": False, "error": detail, "warnings": warnings})
            warnings.append(detail)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "warnings": warnings})

    message = "Finalizzazione database completata."
    if messages:
        message += "\n" + "\n".join(messages)
    return _json({"ok": True, "message": message, "warnings": warnings})


# ── Crea utente admin ─────────────────────────────────────────────────────────

@require_POST
def api_create_admin(request):
    """Crea un superuser Django. Richiede che le migrazioni siano già state eseguite."""
    locked = _reject_if_setup_completed()
    if locked:
        return locked
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

        # Difesa in profondità: una volta che esiste un amministratore, questo
        # endpoint (esente da auth durante il setup) non deve poterne creare altri.
        if User.objects.filter(is_superuser=True).exists():
            return _json({
                "ok": False,
                "error": "Esiste già un amministratore: creazione superuser non consentita da questo endpoint.",
            }, status=403)

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
    locked = _reject_if_setup_completed()
    if locked:
        return locked
    data, err = _parse_json(request)
    if err:
        return _json(err)

    selected = set(data.get("modules") or [])
    all_optional = [
        "assenze", "anomalie", "assets", "tasks", "tickets",
        "notizie", "anagrafica", "automazioni", "timbri", "planimetria",
        "dpi", "procedure_refresh",
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

