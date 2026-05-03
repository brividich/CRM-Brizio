from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor


OK = "OK"
WARN = "WARN"
FAIL = "FAIL"
SEVERITY_ORDER = {OK: 0, WARN: 1, FAIL: 2}

PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "change_me",
    "change-me",
    "change-me-in-dev",
    "change_me_from_env",
    "password",
    "secret",
    "example",
    "example.local",
    "tenant-id",
    "client-id",
    "client-secret",
    "<change_me>",
    "<secret>",
    "<graph_tenant_id>",
    "<graph_client_id>",
    "<graph_client_secret>",
}

SENSITIVE_NAME_PARTS = ("PASSWORD", "SECRET", "TOKEN", "KEY", "PRIVATE")


@dataclass
class CheckResult:
    section: str
    name: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_placeholder(value: Any) -> str:
    return _text(value).strip("'\"").lower()


def _is_placeholder(value: Any) -> bool:
    normalized = _normalize_placeholder(value)
    if normalized in PLACEHOLDER_VALUES:
        return True
    if not normalized:
        return True
    if normalized.startswith(("change_me", "changeme", "your_", "replace_")):
        return True
    if normalized.startswith("<") and normalized.endswith(">"):
        return True
    if normalized.startswith("${") or "{{" in normalized or "}}" in normalized:
        return True
    return False


def _get_setting_or_env(name: str, default: Any = "") -> Any:
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return value
    return os.environ.get(name, default)


def _get_first_setting_or_env(*names: str, default: str = "") -> str:
    for name in names:
        value = _get_setting_or_env(name, "")
        if _text(value):
            return _text(value)
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _get_setting_or_env(name, None)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "on"}


def _mask_if_sensitive(key: str, value: Any) -> Any:
    if any(part in key.upper() for part in SENSITIVE_NAME_PARTS):
        return "<set>" if _text(value) else "<empty>"
    return value


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    return {key: _mask_if_sensitive(key, value) for key, value in details.items()}


def _database_name_for_report(raw_name: Any) -> str:
    name = _text(raw_name)
    if not name:
        return "<empty>"
    # SQLite NAME is often an absolute path. Show the file name to keep the
    # report useful without dumping local directory structure.
    if any(sep in name for sep in ("\\", "/")):
        return Path(name).name or name
    return name


def _path_state(path_value: Any) -> tuple[str, str]:
    path_text = _text(path_value)
    if not path_text:
        return FAIL, "non configurato"

    path = Path(path_text)
    if path.exists():
        if path.is_dir():
            return OK, "directory esistente"
        return FAIL, "il path esiste ma non e' una directory"

    parent = path.parent
    candidates = [parent, *parent.parents]
    for candidate in candidates:
        if candidate.exists():
            if os.access(candidate, os.W_OK):
                return WARN, f"directory mancante, parent creabile: {candidate}"
            return FAIL, f"directory mancante e parent non scrivibile: {candidate}"
    return FAIL, "directory mancante e nessun parent esistente"


class DeploymentValidator:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def add(self, section: str, name: str, severity: str, message: str, **details: Any) -> None:
        self.results.append(
            CheckResult(
                section=section,
                name=name,
                severity=severity,
                message=message,
                details=_safe_details(details),
            )
        )

    def run(self, *, with_integration: bool = False) -> list[CheckResult]:
        self.check_django_settings()
        self.check_database()
        self.check_static_media()
        self.check_cache()
        self.check_graph()
        self.check_ldap()
        self.check_email()
        self.check_security()
        if with_integration:
            self.check_runtime_integrations()
        return self.results

    def check_runtime_integrations(self) -> None:
        """Esegue i probe runtime di monitoring/health.py.

        Riusa la stessa logica di /readyz cosi' che "deploy validato" e
        "ready per il traffico" usino lo stesso set di check, evitando drift
        fra validation e runtime.
        """
        try:
            from monitoring.health import run_readyz_checks
        except Exception as exc:
            self.add(
                "integration",
                "import",
                FAIL,
                f"Impossibile importare monitoring.health: {exc.__class__.__name__}: {exc}",
            )
            return

        report = run_readyz_checks()
        for check in report.checks:
            severity = OK
            if check.status == "fail":
                severity = FAIL if check.critical else WARN
            elif check.status == "warn":
                severity = WARN
            elif check.status == "skipped":
                severity = OK

            message = check.message or f"Check {check.name}: {check.status}"
            details: dict[str, Any] = {
                "status": check.status,
                "latency_ms": check.latency_ms,
                "critical": check.critical,
            }
            if check.details:
                details.update(check.details)
            self.add("integration", check.name, severity, message, **details)

    def check_django_settings(self) -> None:
        settings_module = _text(os.environ.get("DJANGO_SETTINGS_MODULE"))
        debug = bool(getattr(settings, "DEBUG", False))
        environment = settings_module or _text(getattr(settings, "MONITORING_ENVIRONMENT", ""))
        lowered_env = environment.lower()

        if "prod" in lowered_env and debug:
            self.add("django", "DEBUG", WARN, "DEBUG=True in un ambiente che sembra prod.", environment=environment)
        elif "dev" in lowered_env and not debug:
            self.add("django", "DEBUG", WARN, "DEBUG=False in un ambiente che sembra dev.", environment=environment)
        elif "test" in lowered_env and debug:
            self.add("django", "DEBUG", WARN, "DEBUG=True in un ambiente di test.", environment=environment)
        else:
            self.add("django", "DEBUG", OK, "DEBUG coerente con l'ambiente rilevato.", debug=debug, environment=environment)

        secret_key = _text(getattr(settings, "SECRET_KEY", ""))
        if _is_placeholder(secret_key):
            self.add("django", "SECRET_KEY", FAIL, "SECRET_KEY assente o placeholder.")
        else:
            self.add("django", "SECRET_KEY", OK, "SECRET_KEY configurata.", SECRET_KEY=secret_key)

        allowed_hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])
        if not debug and not allowed_hosts:
            self.add("django", "ALLOWED_HOSTS", FAIL, "ALLOWED_HOSTS vuoto con DEBUG=False.")
        else:
            self.add("django", "ALLOWED_HOSTS", OK, "ALLOWED_HOSTS configurato.", count=len(allowed_hosts))

        timezone = _text(getattr(settings, "TIME_ZONE", ""))
        if timezone:
            self.add("django", "TIME_ZONE", OK, "TIME_ZONE valorizzato.", value=timezone)
        else:
            self.add("django", "TIME_ZONE", WARN, "TIME_ZONE non valorizzato.")

        app_version = _text(getattr(settings, "APP_VERSION", ""))
        if app_version:
            self.add("django", "APP_VERSION", OK, "APP_VERSION leggibile.", value=app_version)
        else:
            self.add("django", "APP_VERSION", WARN, "APP_VERSION non valorizzato.")

    def check_database(self) -> None:
        try:
            connection = connections[DEFAULT_DB_ALIAS]
            db_settings = connection.settings_dict
            self.add(
                "database",
                "configuration",
                OK,
                "Database default configurato.",
                engine=db_settings.get("ENGINE", ""),
                database_name=_database_name_for_report(db_settings.get("NAME", "")),
                host=db_settings.get("HOST", ""),
                user="<set>" if _text(db_settings.get("USER", "")) else "<empty>",
            )
        except Exception as exc:
            self.add("database", "configuration", FAIL, f"Impossibile leggere la configurazione database: {exc}")
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            self.add("database", "connection", OK, "Connessione default verificata con SELECT 1.")
        except Exception as exc:
            self.add("database", "connection", FAIL, f"Connessione default fallita: {exc.__class__.__name__}: {exc}")
            return

        try:
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)
            if plan:
                self.add(
                    "database",
                    "migrations",
                    WARN,
                    "Sono presenti migration non applicate.",
                    unapplied_count=len(plan),
                    first_unapplied=f"{plan[0][0].app_label}.{plan[0][0].name}",
                )
            else:
                self.add("database", "migrations", OK, "Migration state allineato.")
        except Exception as exc:
            self.add(
                "database",
                "migrations",
                WARN,
                f"Migration state non verificabile: {exc.__class__.__name__}: {exc}",
            )

    def check_static_media(self) -> None:
        debug = bool(getattr(settings, "DEBUG", False))
        static_root = getattr(settings, "STATIC_ROOT", "")
        if not debug and not _text(static_root):
            self.add("static_media", "STATIC_ROOT", FAIL, "STATIC_ROOT richiesto con DEBUG=False ma non configurato.")
        elif _text(static_root):
            severity, message = _path_state(static_root)
            self.add("static_media", "STATIC_ROOT", severity, message, path=str(static_root))
        else:
            self.add("static_media", "STATIC_ROOT", WARN, "STATIC_ROOT non configurato.")

        media_root = getattr(settings, "MEDIA_ROOT", "")
        if _text(media_root):
            severity, message = _path_state(media_root)
            self.add("static_media", "MEDIA_ROOT", severity, message, path=str(media_root))
        else:
            self.add("static_media", "MEDIA_ROOT", WARN, "MEDIA_ROOT non configurato.")

    def check_cache(self) -> None:
        caches = getattr(settings, "CACHES", {}) or {}
        default_cache = caches.get("default", {})
        backend = default_cache.get("BACKEND", "")
        if backend:
            self.add("cache", "backend", OK, "Backend cache default configurato.", backend=backend)
        else:
            self.add("cache", "backend", WARN, "Backend cache default non configurato.")

        key = f"validate_deployment:{uuid.uuid4()}"
        value = f"ok:{uuid.uuid4()}"
        try:
            cache.set(key, value, timeout=30)
            cached = cache.get(key)
            cache.delete(key)
            if cached == value:
                self.add("cache", "roundtrip", OK, "Cache set/get/delete riuscito.")
            else:
                self.add("cache", "roundtrip", FAIL, "Cache get non ha restituito il valore atteso.")
        except Exception as exc:
            self.add("cache", "roundtrip", FAIL, f"Cache roundtrip fallito: {exc.__class__.__name__}: {exc}")

    def check_graph(self) -> None:
        values = {
            "GRAPH_TENANT_ID": _get_first_setting_or_env("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
            "GRAPH_CLIENT_ID": _get_first_setting_or_env("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
            "GRAPH_CLIENT_SECRET": _get_first_setting_or_env("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
            "GRAPH_SITE_ID": _get_first_setting_or_env("GRAPH_SITE_ID"),
            "APPROVAL_MAILBOX_BACKEND": _get_first_setting_or_env("APPROVAL_MAILBOX_BACKEND", default=""),
            "APPROVAL_MAILBOX_ADDRESS": _get_first_setting_or_env("APPROVAL_MAILBOX_ADDRESS", default=""),
        }
        graph_enabled = _env_bool("GRAPH_ENABLED", False) or any(
            _text(value) for key, value in values.items() if key != "APPROVAL_MAILBOX_BACKEND"
        )
        if values["APPROVAL_MAILBOX_BACKEND"].lower() == "graph":
            graph_enabled = True

        present = {key: bool(_text(value)) for key, value in values.items()}
        self.add(
            "graph",
            "detected",
            OK if graph_enabled else WARN,
            "Microsoft Graph rilevato." if graph_enabled else "Microsoft Graph non configurato/rilevato.",
            **present,
        )

        required = ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")
        missing = [key for key in required if not _text(values[key])]
        placeholders = [key for key in required if _text(values[key]) and _is_placeholder(values[key])]
        if graph_enabled and missing:
            self.add("graph", "credentials", WARN, "Graph abilitato/rilevato ma credenziali incomplete.", missing=", ".join(missing))
        elif placeholders:
            self.add("graph", "credentials", WARN, "Credenziali Graph valorizzate con placeholder.", placeholders=", ".join(placeholders))
        else:
            self.add("graph", "credentials", OK, "Credenziali Graph presenti o integrazione non abilitata.")

    def check_ldap(self) -> None:
        enabled = bool(getattr(settings, "LDAP_ENABLED", False))
        server = _text(getattr(settings, "LDAP_SERVER", ""))
        base_dn = _text(getattr(settings, "LDAP_BASE_DN", ""))
        user_filter = _text(getattr(settings, "LDAP_USER_FILTER", ""))
        group_allowlist = getattr(settings, "LDAP_GROUP_ALLOWLIST", []) or []

        self.add("ldap", "detected", OK if enabled else WARN, "LDAP/AD abilitato." if enabled else "LDAP/AD non abilitato.", enabled=enabled)
        if not enabled:
            return

        missing = []
        if not server or _is_placeholder(server):
            missing.append("LDAP_SERVER")
        if not base_dn or _is_placeholder(base_dn):
            missing.append("LDAP_BASE_DN")
        if not user_filter or _is_placeholder(user_filter):
            missing.append("LDAP_USER_FILTER")
        if not group_allowlist:
            missing.append("LDAP_GROUP_ALLOWLIST")

        if missing:
            self.add("ldap", "configuration", WARN, "LDAP/AD abilitato ma configurazione incompleta.", missing=", ".join(missing))
        else:
            self.add("ldap", "configuration", OK, "Configurazione LDAP/AD minima presente.")

    def check_email(self) -> None:
        backend = _text(getattr(settings, "EMAIL_BACKEND", ""))
        host = _text(getattr(settings, "EMAIL_HOST", ""))
        port = getattr(settings, "EMAIL_PORT", "")
        user = _text(getattr(settings, "EMAIL_HOST_USER", ""))
        default_from = _text(getattr(settings, "DEFAULT_FROM_EMAIL", ""))
        approval_mailbox = _get_first_setting_or_env("APPROVAL_MAILBOX_ADDRESS", default="")

        self.add("email", "backend", OK if backend else WARN, "Backend email configurato." if backend else "Backend email non configurato.", backend=backend)
        if backend.endswith(".smtp.EmailBackend"):
            if not host or _is_placeholder(host):
                self.add("email", "smtp", WARN, "SMTP backend attivo ma EMAIL_HOST mancante o placeholder.", port=port)
            else:
                self.add("email", "smtp", OK, "SMTP host/porta configurati.", host=host, port=port, user=user)
        else:
            self.add("email", "smtp", OK, "SMTP non richiesto dal backend email corrente.", backend=backend)

        placeholder_fields = [
            name
            for name, value in {
                "EMAIL_HOST_USER": user,
                "DEFAULT_FROM_EMAIL": default_from,
                "APPROVAL_MAILBOX_ADDRESS": approval_mailbox,
            }.items()
            if _text(value) and _is_placeholder(value)
        ]
        if placeholder_fields:
            self.add("email", "placeholders", WARN, "Valori email placeholder rilevati.", fields=", ".join(placeholder_fields))
        else:
            self.add(
                "email",
                "approval_mailbox",
                OK if approval_mailbox else WARN,
                "Mailbox approvazioni configurata." if approval_mailbox else "Mailbox approvazioni non configurata.",
                mailbox=approval_mailbox,
            )

    def check_security(self) -> None:
        settings_module = _text(os.environ.get("DJANGO_SETTINGS_MODULE"))
        debug = bool(getattr(settings, "DEBUG", False))
        if "prod" in settings_module.lower() and debug:
            self.add("security", "DEBUG", WARN, "DEBUG=True usando settings prod.")
        else:
            self.add("security", "DEBUG", OK, "Nessun mismatch prod/DEBUG rilevato.", debug=debug)

        secret_key = _text(getattr(settings, "SECRET_KEY", ""))
        if _is_placeholder(secret_key):
            self.add("security", "SECRET_KEY", FAIL, "SECRET_KEY contiene un placeholder o valore vuoto.")
        else:
            self.add("security", "SECRET_KEY", OK, "SECRET_KEY non sembra un placeholder.", SECRET_KEY=secret_key)

        self.add("security", "public_repo", WARN, "Controllo repository pubblico non eseguito: web check non applicabile.")


def _summary(results: list[CheckResult]) -> dict[str, int]:
    return {
        OK: sum(1 for item in results if item.severity == OK),
        WARN: sum(1 for item in results if item.severity == WARN),
        FAIL: sum(1 for item in results if item.severity == FAIL),
    }


def _worst(results: list[CheckResult]) -> str:
    return max((item.severity for item in results), key=lambda severity: SEVERITY_ORDER[severity], default=OK)


class Command(BaseCommand):
    help = (
        "Valida in modo diagnostico l'ambiente di deploy/test/prod senza modificare "
        "configurazioni runtime. Exit code non-zero con FAIL; con --fail-on-warn anche con WARN."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Formato output (default: text).",
        )
        parser.add_argument(
            "--fail-on-warn",
            action="store_true",
            help="Ritorna exit code non-zero anche se sono presenti solo WARN.",
        )
        parser.add_argument(
            "--fail-on-fail",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Ritorna exit code non-zero in presenza di FAIL (default: true).",
        )
        parser.add_argument(
            "--with-integration",
            action="store_true",
            help=(
                "Esegue anche i probe runtime di monitoring/health.py "
                "(DB, cache, Graph token, LDAP, SMTP, queue automazioni). "
                "Da usare in pre-rilascio o per diagnosi rapida."
            ),
        )

    def handle(self, *args, **options):
        results = DeploymentValidator().run(with_integration=bool(options["with_integration"]))
        summary = _summary(results)

        if options["format"] == "json":
            payload = {
                "ok": summary[FAIL] == 0,
                "summary": summary,
                "worst": _worst(results),
                "checks": [asdict(item) for item in results],
            }
            self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING("NOVICROM HUB deployment validation"))
            self.stdout.write(f"Summary: OK={summary[OK]} WARN={summary[WARN]} FAIL={summary[FAIL]}")
            current_section = None
            for item in results:
                if item.section != current_section:
                    current_section = item.section
                    self.stdout.write("")
                    self.stdout.write(self.style.MIGRATE_LABEL(current_section.upper()))
                style = self.style.SUCCESS
                if item.severity == WARN:
                    style = self.style.WARNING
                elif item.severity == FAIL:
                    style = self.style.ERROR
                details = ""
                if item.details:
                    rendered = ", ".join(f"{key}={value}" for key, value in item.details.items())
                    details = f" ({rendered})"
                self.stdout.write(style(f"[{item.severity}] {item.name}: {item.message}{details}"))

        should_fail = (bool(options["fail_on_fail"]) and summary[FAIL] > 0) or (
            bool(options["fail_on_warn"]) and summary[WARN] > 0
        )
        if should_fail:
            raise CommandError(
                f"Deployment validation failed: OK={summary[OK]}, WARN={summary[WARN]}, FAIL={summary[FAIL]}"
            )
