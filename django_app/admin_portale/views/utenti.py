"""Viste del Pannello di amministrazione — Utenti: elenco, scheda, creazione/modifica, LDAP, capi reparto, attività.

Spacchettamento di ``admin_portale/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json
import logging
import os
from io import StringIO
from pathlib import Path
from urllib.parse import urlsplit

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.core.validators import validate_email
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError, connections, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from werkzeug.security import generate_password_hash

from automazioni.approval_mailbox_runtime import (
    get_approval_imap_form_defaults,
    get_approval_imap_status,
    run_approval_imap_poll_now,
    save_approval_imap_settings,
)
from core.audit import log_action
from core.exporting import export_rows_response
from core.caporeparto_utils import (
    format_caporeparto_label,
    normalize_caporeparto_option,
)
from core.impersonation import start_impersonation
from core.ldap_conn import build_ldap_server, ldap_receive_timeout
from core.legacy_anagrafica import ensure_anagrafica_schema, sync_anagrafica_from_legacy_user
from core.legacy_models import AnagraficaDipendente, Pulsante, Ruolo, UtenteLegacy
from core.legacy_utils import get_legacy_user, legacy_table_columns
from core.models import (
    AnagraficaRisposta,
    AnagraficaVoce,
    ChecklistEsecuzione,
    EmployeeBoardConfig,
    Notifica,
    OptioneConfig,
    Profile,
    UserDashboardConfig,
    UserDashboardLayout,
    UserExtraInfo,
    UserUiPreference,
    UserModuleVisibility,
    UserPermissionOverride,
)

from ..decorators import legacy_admin_required
from ..forms import BulkRoleForm, UtenteCreateForm, UtenteUpdateForm
from core import naming

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


def _safe_redirect_url(request, candidate: str | None, fallback: str) -> str:
    """Restituisce candidate solo se Ã¨ un URL locale sicuro, altrimenti fallback.

    Protegge da open redirect: rifiuta URL assoluti verso domini esterni, URL
    con schema javascript:/data: e qualsiasi valore che non passi il controllo
    Django url_has_allowed_host_and_scheme.
    """
    if candidate:
        candidate = str(candidate).strip()
        if url_has_allowed_host_and_scheme(
            url=candidate,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return candidate
    return fallback


def _asset_model():
    try:
        return django_apps.get_model("assets", "Asset")
    except Exception:
        return None


def _storico_asset(asset_ids, *, fonte: str, utente=None, dettaglio: str = ""):
    """Storico assegnazioni asset (servizio unico di ``assets``), transazionale con la modifica.

    Senza il modulo asset installato e' un blocco vuoto: le scritture restano invariate.
    """
    from contextlib import nullcontext

    if not django_apps.is_installed("assets"):
        return nullcontext()
    from assets.services.storico_asset import traccia

    return traccia(asset_ids, fonte=fonte, utente=utente, dettaglio=dettaglio)


LDAP_DIAG_FIELDS: tuple[dict[str, object], ...] = (
    {
        "key": "enabled",
        "label": "LDAP abilitato",
        "setting_name": "LDAP_ENABLED",
        "env_key": "LDAP_ENABLED",
        "ini_key": "enabled",
        "default": False,
        "kind": "bool",
    },
    {
        "key": "server",
        "label": "Server LDAP",
        "setting_name": "LDAP_SERVER",
        "env_key": "LDAP_SERVER",
        "ini_key": "server",
        "default": "",
        "kind": "str",
    },
    {
        "key": "domain",
        "label": "Dominio (NetBIOS)",
        "setting_name": "LDAP_DOMAIN",
        "env_key": "LDAP_DOMAIN",
        "ini_key": "domain",
        "default": "",
        "kind": "str",
    },
    {
        "key": "upn_suffix",
        "label": "UPN suffix",
        "setting_name": "LDAP_UPN_SUFFIX",
        "env_key": "LDAP_UPN_SUFFIX",
        "ini_key": "upn_suffix",
        "default": "",
        "kind": "str",
    },
    {
        "key": "timeout",
        "label": "Timeout (s)",
        "setting_name": "LDAP_TIMEOUT",
        "env_key": "LDAP_TIMEOUT",
        "ini_key": "timeout",
        "default": 5,
        "kind": "int",
    },
    {
        "key": "service_user",
        "label": "Service user",
        "setting_name": "LDAP_SERVICE_USER",
        "env_key": "LDAP_SERVICE_USER",
        "ini_key": "service_user",
        "default": "",
        "kind": "str",
    },
    {
        "key": "base_dn",
        "label": "Base DN",
        "setting_name": "LDAP_BASE_DN",
        "env_key": "LDAP_BASE_DN",
        "ini_key": "base_dn",
        "default": "",
        "kind": "str",
    },
    {
        "key": "user_filter",
        "label": "User filter",
        "setting_name": "LDAP_USER_FILTER",
        "env_key": "LDAP_USER_FILTER",
        "ini_key": "user_filter",
        "default": "(&(objectCategory=person)(objectClass=user))",
        "kind": "str",
    },
    {
        "key": "group_allowlist",
        "label": "Group allowlist",
        "setting_name": "LDAP_GROUP_ALLOWLIST",
        "env_key": "LDAP_GROUP_ALLOWLIST",
        "ini_key": "group_allowlist",
        "default": [],
        "kind": "csv",
    },
    {
        "key": "sync_page_size",
        "label": "Sync page size",
        "setting_name": "LDAP_SYNC_PAGE_SIZE",
        "env_key": "LDAP_SYNC_PAGE_SIZE",
        "ini_key": "sync_page_size",
        "default": 500,
        "kind": "int",
    },
)


def _config_ini_path() -> Path:
    return Path(settings.BASE_DIR).parent / "config.ini"


def _ldap_effective_service_password() -> str:
    return _helpers._effective_env_value(
        "LDAP_SERVICE_PASSWORD",
        str(getattr(settings, "LDAP_SERVICE_PASSWORD", "") or ""),
    )


def _ldap_csv_items(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        items = value
    elif value in (None, ""):
        items = []
    else:
        items = str(value).split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def _ldap_normalize_field_value(field: dict[str, object], value):
    kind = str(field.get("kind") or "str")
    default = field.get("default")
    if kind == "bool":
        return _helpers._bool_from_any(default if value is None else value)
    if kind == "int":
        coerced = _helpers._int_or_none(value)
        if coerced is None:
            coerced = _helpers._int_or_none(default)
        return coerced or 0
    if kind == "csv":
        return tuple(item.casefold() for item in _ldap_csv_items(value))
    return str(value or "").strip()


def _ldap_display_field_value(field: dict[str, object], value) -> str:
    kind = str(field.get("kind") or "str")
    if kind == "bool":
        return "Si" if _ldap_normalize_field_value(field, value) else "No"
    if kind == "int":
        return str(_ldap_normalize_field_value(field, value))
    if kind == "csv":
        items = _ldap_csv_items(value)
        return ", ".join(items) if items else "(vuota)"
    text = str(value or "").strip()
    return text or "(non configurato)"


def _ldap_form_field_value(field: dict[str, object], value):
    kind = str(field.get("kind") or "str")
    if kind == "bool":
        return _ldap_normalize_field_value(field, value)
    if kind == "int":
        return _ldap_normalize_field_value(field, value)
    if kind == "csv":
        return ", ".join(_ldap_csv_items(value))
    return str(value or "").strip()


def _load_config_ini_ad_values() -> dict[str, str]:
    """Legge la sezione [ACTIVE_DIRECTORY] da config.ini e restituisce un dict chiave->valore."""
    import configparser as _cp
    parser = _cp.ConfigParser()
    config_path = _config_ini_path()
    if config_path.exists():
        try:
            parser.read(str(config_path), encoding="utf-8")
        except Exception:
            pass
    if parser.has_section("ACTIVE_DIRECTORY"):
        return dict(parser.items("ACTIVE_DIRECTORY"))
    return {}


def _ldap_source_label(source_key: str) -> str:
    mapping = {
        "dotenv": ".env",
        "process_env": "ambiente processo",
        "config_ini": "config.ini",
        "default": "default codice",
        "stale_runtime": "runtime gia caricato",
    }
    return mapping.get(source_key, source_key)


def _ldap_runtime_source(
    field: dict[str, object],
    runtime_value,
    dotenv_values: dict[str, str],
    ini_values: dict[str, str] | None = None,
) -> str:
    runtime_norm = _ldap_normalize_field_value(field, runtime_value)
    env_key = str(field.get("env_key") or "")
    ini_key = str(field.get("ini_key") or "")
    dotenv_value = dotenv_values.get(env_key)
    process_env_value = os.environ.get(env_key)

    if process_env_value is not None and (dotenv_value is None or process_env_value != dotenv_value):
        if runtime_norm == _ldap_normalize_field_value(field, process_env_value):
            return "process_env"
    if dotenv_value is not None and runtime_norm == _ldap_normalize_field_value(field, dotenv_value):
        return "dotenv"
    if ini_values is not None and ini_key and ini_key in ini_values:
        if runtime_norm == _ldap_normalize_field_value(field, ini_values[ini_key]):
            return "config_ini"
    if runtime_norm == _ldap_normalize_field_value(field, field.get("default")):
        return "default"
    return "stale_runtime"


def _ldap_next_boot_value(
    field: dict[str, object],
    dotenv_values: dict[str, str],
    ini_values: dict[str, str] | None = None,
):
    env_key = str(field.get("env_key") or "")
    ini_key = str(field.get("ini_key") or "")
    dotenv_value = dotenv_values.get(env_key)
    process_env_value = os.environ.get(env_key)
    if process_env_value is not None and (dotenv_value is None or process_env_value != dotenv_value):
        return process_env_value, "process_env"
    if dotenv_value is not None:
        return dotenv_value, "dotenv"
    if ini_values is not None and ini_key and ini_key in ini_values:
        return ini_values[ini_key], "config_ini"
    return field.get("default"), "default"


def _ldap_diag_runtime_rows(runtime_cfg: dict[str, object]) -> tuple[list[dict[str, object]], bool, bool]:
    dotenv_values = _helpers._load_dotenv_values()
    ini_values = _load_config_ini_ad_values()
    rows: list[dict[str, object]] = []
    has_pending_restart = False
    has_env_override = False

    for field in LDAP_DIAG_FIELDS:
        key = str(field["key"])
        runtime_value = runtime_cfg.get(key)
        runtime_source = _ldap_runtime_source(field, runtime_value, dotenv_values, ini_values)
        next_value, next_source = _ldap_next_boot_value(field, dotenv_values, ini_values)

        runtime_norm = _ldap_normalize_field_value(field, runtime_value)
        next_norm = _ldap_normalize_field_value(field, next_value)
        runtime_matches_next = runtime_norm == next_norm
        dotenv_value = dotenv_values.get(str(field.get("env_key") or ""))
        override_active = (
            next_source == "process_env"
            and dotenv_value is not None
            and _ldap_normalize_field_value(field, dotenv_value) != next_norm
        )

        if not runtime_matches_next:
            status_label = "Riavvio necessario"
            status_tone = "warning"
            note = "Il processo Django attuale non usa ancora il valore che verra letto al prossimo avvio."
            has_pending_restart = True
        elif override_active:
            status_label = "Override attivo"
            status_tone = "warning"
            note = f"{_ldap_source_label(next_source)} ha priorita su .env per questo campo."
            has_env_override = True
        elif next_source in {"dotenv", "process_env", "config_ini"}:
            status_label = "Allineato"
            status_tone = "success"
            note = f"Il runtime legge questo campo da {_ldap_source_label(next_source)}."
        else:
            status_label = "Default"
            status_tone = "muted"
            note = "Nessun valore persistito trovato: resta attivo il default applicativo."

        rows.append(
            {
                "key": key,
                "label": field["label"],
                "runtime_value_display": _ldap_display_field_value(field, runtime_value),
                "runtime_source_label": _ldap_source_label(runtime_source),
                "next_value_display": _ldap_display_field_value(field, next_value),
                "next_source_label": _ldap_source_label(next_source),
                "status_label": status_label,
                "status_tone": status_tone,
                "note": note,
            }
        )

    return rows, has_pending_restart, has_env_override


def _ldap_effective_form_state() -> tuple[dict[str, object], dict[str, str]]:
    dotenv_values = _helpers._load_dotenv_values()
    ini_values = _load_config_ini_ad_values()
    values: dict[str, object] = {}
    source_labels: dict[str, str] = {}

    for field in LDAP_DIAG_FIELDS:
        key = str(field["key"])
        next_value, next_source = _ldap_next_boot_value(field, dotenv_values, ini_values)
        values[key] = _ldap_form_field_value(field, next_value)
        source_labels[key] = _ldap_source_label(next_source)

    return values, source_labels


def _ldap_file_defaults(runtime_cfg: dict[str, object]) -> dict[str, object]:
    values, _source_labels = _ldap_effective_form_state()
    return values


def _ldap_effective_source_labels() -> dict[str, str]:
    _values, source_labels = _ldap_effective_form_state()
    return source_labels


def _ldap_missing_required_labels(cfg: dict[str, object], required_keys: tuple[str, ...]) -> list[str]:
    labels_by_key = {
        str(field["key"]): str(field["label"])
        for field in LDAP_DIAG_FIELDS
    }
    labels_by_key["service_password"] = "Password service account"
    missing: list[str] = []

    for key in required_keys:
        if key == "enabled":
            if not _helpers._bool_from_any(cfg.get(key)):
                missing.append(labels_by_key.get(key, key))
            continue
        if key == "service_password":
            if not bool(cfg.get("service_password_configured")):
                missing.append(labels_by_key.get(key, key))
            continue
        if not str(cfg.get(key) or "").strip():
            missing.append(labels_by_key.get(key, key))

    return missing


def _ldap_diag_defaults() -> dict[str, object]:
    allowlist = getattr(settings, "LDAP_GROUP_ALLOWLIST", []) or []
    return {
        "enabled": bool(getattr(settings, "LDAP_ENABLED", False)),
        "server": str(getattr(settings, "LDAP_SERVER", "") or ""),
        "domain": str(getattr(settings, "LDAP_DOMAIN", "") or ""),
        "upn_suffix": str(getattr(settings, "LDAP_UPN_SUFFIX", "") or ""),
        "timeout": int(getattr(settings, "LDAP_TIMEOUT", 5) or 5),
        "service_user": str(getattr(settings, "LDAP_SERVICE_USER", "") or ""),
        "base_dn": str(getattr(settings, "LDAP_BASE_DN", "") or ""),
        "user_filter": str(getattr(settings, "LDAP_USER_FILTER", "") or ""),
        "group_allowlist": ", ".join([str(v).strip() for v in allowlist if str(v).strip()]),
        "sync_page_size": int(getattr(settings, "LDAP_SYNC_PAGE_SIZE", 500) or 500),
        "sync_limit": 0,
        "sync_dry_run": True,
        "sync_replace_allowlist": False,
    }


def _smtp_diag_defaults() -> dict[str, str | bool | int]:
    return {
        "host": _helpers._effective_env_value("EMAIL_HOST", str(getattr(settings, "EMAIL_HOST", "") or "")),
        "port": _helpers._effective_env_int("EMAIL_PORT", int(getattr(settings, "EMAIL_PORT", 587) or 587)),
        "user": _helpers._effective_env_value("EMAIL_HOST_USER", str(getattr(settings, "EMAIL_HOST_USER", "") or "")),
        "password_configured": bool(
            _helpers._effective_env_value("EMAIL_HOST_PASSWORD", str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""))
        ),
        "use_tls": _helpers._effective_env_bool("EMAIL_USE_TLS", bool(getattr(settings, "EMAIL_USE_TLS", True))),
        "use_ssl": _helpers._effective_env_bool("EMAIL_USE_SSL", bool(getattr(settings, "EMAIL_USE_SSL", False))),
        "timeout": _helpers._effective_env_int("EMAIL_TIMEOUT", int(getattr(settings, "EMAIL_TIMEOUT", 10) or 10)),
        "default_from_email": _helpers._effective_env_value(
            "DEFAULT_FROM_EMAIL",
            str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""),
        ),
        "test_to": "",
    }


def _ldap_test_connect(server_url: str, timeout: int) -> tuple[bool, str]:
    try:
        pass
    except Exception as exc:
        return False, f"ldap3 non disponibile: {exc}"
    try:
        server = build_ldap_server(server_url, timeout)
        # open() prova la connessione TCP senza bind credenziali
        from ldap3 import Connection
        conn = Connection(server)
        conn.open()
        # ldap3 puo' restituire None su open() anche con socket aperto.
        if not conn.closed:
            conn.unbind()
            return True, "Connessione LDAP riuscita."
        err = conn.last_error or conn.result or "nessun dettaglio disponibile"
        return False, f"Connessione LDAP fallita: {err}"
    except Exception as exc:
        return False, f"Connessione LDAP fallita: {exc}"


def _ldap_test_bind(server_url: str, timeout: int, username: str, password: str, domain: str, upn_suffix: str) -> tuple[bool, str]:
    try:
        from ldap3 import NTLM, SIMPLE, Connection
    except Exception as exc:
        return False, f"ldap3 non disponibile: {exc}"

    ident = (username or "").strip()
    pwd = (password or "").strip()
    if not ident or not pwd:
        return False, "Username e password sono obbligatori per il test bind."

    server = build_ldap_server(server_url, timeout)
    alias = ident.split("\\")[-1]
    attempts: list[tuple[str, object, str]] = []
    if "\\" in ident:
        attempts.append((ident, NTLM, f"NTLM ({ident})"))
    elif "@" in ident:
        attempts.append((ident, SIMPLE, f"UPN ({ident})"))
    else:
        suffix = (upn_suffix or "").lstrip("@")
        bind_dn = f"{alias}@{suffix}" if suffix else alias
        attempts.append((bind_dn, SIMPLE, f"UPN ({bind_dn})"))
        if bind_dn != alias:
            attempts.append((alias, SIMPLE, f"SIMPLE ({alias})"))
        if domain:
            ntlm_user = f"{domain}\\{alias}"
            attempts.append((ntlm_user, NTLM, f"NTLM ({ntlm_user})"))

    last_error = "nessun dettaglio disponibile"
    for bind_user, authentication, label in attempts:
        try:
            conn = Connection(
                server,
                user=bind_user,
                password=pwd,
                authentication=authentication,
                auto_bind=False,
                auto_referrals=False,
                raise_exceptions=False,
                receive_timeout=ldap_receive_timeout(),
            )
            if conn.bind():
                conn.unbind()
                return True, f"Bind LDAP riuscito con {label}."
            last_error = str(conn.result)
            conn.unbind()
        except Exception as exc:
            last_error = str(exc)
            _helpers.logger.info("LDAP bind test failed for %s: %s", label, exc)

    return False, f"Bind fallito. Ultimo errore: {last_error}"


def _ldap_save_service_account(service_user: str, service_password: str) -> tuple[bool, str]:
    password_to_save = (service_password or "").strip() or _ldap_effective_service_password()
    if not service_user:
        return False, "Username service account obbligatorio."
    if not password_to_save:
        return False, "Password service account obbligatoria: inseriscila almeno al primo salvataggio."

    ok, message = _helpers._update_dotenv_assignments(
        {
            "LDAP_SERVICE_USER": service_user,
            "LDAP_SERVICE_PASSWORD": password_to_save,
        }
    )
    if not ok:
        return ok, message
    return True, f"Service account salvato: {service_user}. Riavvia il server per applicare."


def _ldap_save_settings(
    *,
    enabled: bool,
    server: str,
    domain: str,
    upn_suffix: str,
    timeout: int,
    base_dn: str,
    user_filter: str,
    group_allowlist: str,
    sync_page_size: int,
) -> tuple[bool, str]:
    normalized_timeout = max(1, int(timeout or 5))
    normalized_page_size = max(100, min(int(sync_page_size or 500), 2000))

    ok, message = _helpers._update_dotenv_assignments(
        {
            "LDAP_ENABLED": "1" if enabled else "0",
            "LDAP_SERVER": server,
            "LDAP_DOMAIN": domain,
            "LDAP_UPN_SUFFIX": upn_suffix,
            "LDAP_TIMEOUT": str(normalized_timeout),
            "LDAP_BASE_DN": base_dn,
            "LDAP_USER_FILTER": user_filter,
            "LDAP_GROUP_ALLOWLIST": group_allowlist,
            "LDAP_SYNC_PAGE_SIZE": str(normalized_page_size),
        }
    )
    if not ok:
        return ok, message
    return True, "Configurazione LDAP salvata. Riavvia il server per applicare."


def _smtp_test_connect(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    use_tls: bool,
    use_ssl: bool,
    timeout: int,
) -> tuple[bool, str]:
    if not host:
        return False, "Server SMTP non configurato."
    if use_tls and use_ssl:
        return False, "SMTP non valido: use_tls e use_ssl non possono essere entrambi attivi."

    try:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host,
            port=int(port or 0),
            username=username or "",
            password=password or "",
            use_tls=bool(use_tls),
            use_ssl=bool(use_ssl),
            timeout=int(timeout or 10),
            fail_silently=False,
        )
        connection.open()
        connection.close()
        return True, "Connessione SMTP riuscita."
    except Exception as exc:
        return False, f"Connessione SMTP fallita: {exc}"


def _smtp_normalize_recipients(value) -> tuple[bool, list[str], str]:
    if value is None:
        return True, [], ""
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value).replace(";", ",").split(",")
    recipients = [str(item).strip() for item in raw_items if str(item).strip()]
    for email in recipients:
        try:
            validate_email(email)
        except ValidationError:
            return False, [], f"Indirizzo email non valido: {email}"
    return True, recipients, ""


def _smtp_send_test_email(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    use_tls: bool,
    use_ssl: bool,
    timeout: int,
    from_email: str,
    to_email: str,
) -> tuple[bool, str]:
    sender = (from_email or "").strip()
    recipient_value = (to_email or "").strip()
    if not sender:
        return False, "Default from email obbligatoria per l'invio di test."
    try:
        validate_email(sender)
    except ValidationError:
        return False, f"Default from email non valida: {sender}"

    ok, recipients, error_message = _smtp_normalize_recipients(recipient_value)
    if not ok:
        return False, error_message
    if not recipients:
        return False, "Destinatario test obbligatorio."
    if use_tls and use_ssl:
        return False, "Configurazione SMTP non valida: TLS e SSL non possono essere entrambi attivi."

    connection = None
    try:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=host,
            port=int(port or 0),
            username=username or "",
            password=password or "",
            use_tls=bool(use_tls),
            use_ssl=bool(use_ssl),
            timeout=int(timeout or 10),
            fail_silently=False,
        )
        body_text = (
            "Questa e' una mail di test inviata dal pannello Config SRV del Portale Applicativo.\n\n"
            f"Server: {host}:{port}\n"
            f"Utente SMTP: {username or '(vuoto)'}"
        )
        from core.email_utils import send_hub_mail
        sent_count = send_hub_mail(
            "Test SMTP Portale Applicativo",
            body_text,
            recipients,
            email_type="Config SRV",
            title="Test SMTP",
            from_email=sender,
            connection=connection,
            fail_silently=False,
        )
        if sent_count < 1:
            return False, "Invio mail di test non riuscito: nessun messaggio inviato."
        return True, f"Mail di test inviata con successo a {', '.join(recipients)}."
    except Exception as exc:
        return False, f"Invio mail di test fallito: {exc}"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _smtp_save_settings(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    use_tls: bool,
    use_ssl: bool,
    timeout: int,
    default_from_email: str,
) -> tuple[bool, str]:
    current_password = _helpers._effective_env_value(
        "EMAIL_HOST_PASSWORD",
        str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""),
    )
    effective_password = str(password or "").strip() or current_password
    return _helpers._update_dotenv_assignments(
        {
            "EMAIL_HOST": host,
            "EMAIL_PORT": str(port),
            "EMAIL_HOST_USER": user,
            "EMAIL_HOST_PASSWORD": effective_password,
            "EMAIL_USE_TLS": "1" if use_tls else "0",
            "EMAIL_USE_SSL": "1" if use_ssl else "0",
            "EMAIL_TIMEOUT": str(timeout),
            "DEFAULT_FROM_EMAIL": default_from_email,
        }
    )


def _role_name_map() -> dict[int, str]:
    return {int(r.id): (r.nome or "") for r in _helpers._role_choices()}


def _group_perm_rows_by_modulo(rows: list[_helpers.PermRow]) -> list[tuple[str, list[_helpers.PermRow]]]:
    grouped: dict[str, list[_helpers.PermRow]] = {}
    for row in rows:
        key = (row.modulo or "").strip() or "N/D"
        grouped.setdefault(key, []).append(row)
    result = []
    for modulo in sorted(grouped.keys(), key=str.lower):
        items = sorted(grouped[modulo], key=lambda r: ((r.label or "").lower(), (r.azione or "").lower()))
        result.append((modulo, items))
    return result


@legacy_admin_required
def ldap_diagnostica(request):
    runtime_cfg = _ldap_diag_defaults()
    defaults = _ldap_file_defaults(runtime_cfg)
    defaults["service_password_configured"] = bool(_ldap_effective_service_password())
    ldap_cfg_source_labels = _ldap_effective_source_labels()
    ldap_sync_cfg = {
        "sync_limit": 0,
        "sync_dry_run": True,
        "sync_replace_allowlist": False,
        "group_allowlist": str(defaults["group_allowlist"] or ""),
    }
    ldap_diag_rows, ldap_runtime_has_pending_restart, ldap_runtime_has_env_override = _ldap_diag_runtime_rows(runtime_cfg)
    smtp_defaults = _smtp_diag_defaults()
    ollama_defaults = _helpers._ollama_diag_defaults()
    approval_imap_status = get_approval_imap_status()
    approval_imap_form = get_approval_imap_form_defaults()
    result_connect = None
    result_bind = None
    result_service = None
    result_smtp = None
    result_ollama = None
    result_approval_imap = None
    sync_result = None
    bind_username = ""

    if request.method == "POST":
        def _posted_str(key: str, fallback: str) -> str:
            if key in request.POST:
                return (request.POST.get(key) or "").strip()
            return str(fallback or "").strip()

        action = (request.POST.get("action") or "").strip().lower()
        server = _posted_str("server", defaults["server"])
        domain = _posted_str("domain", defaults["domain"])
        upn_suffix = _posted_str("upn_suffix", defaults["upn_suffix"])
        timeout = _helpers._int_or_none(request.POST.get("timeout")) if "timeout" in request.POST else None
        timeout = timeout or int(defaults["timeout"])
        base_dn = _posted_str("base_dn", defaults["base_dn"])
        user_filter = _posted_str("user_filter", defaults["user_filter"])
        group_allowlist = _posted_str("group_allowlist", defaults["group_allowlist"])
        sync_page_size = _helpers._int_or_none(request.POST.get("sync_page_size")) if "sync_page_size" in request.POST else None
        sync_page_size = sync_page_size or int(defaults["sync_page_size"])
        bind_username = (request.POST.get("bind_username") or "").strip()
        bind_password = (request.POST.get("bind_password") or "").strip()
        defaults.update(
            {
                "server": server,
                "domain": domain,
                "upn_suffix": upn_suffix,
                "timeout": timeout,
                "base_dn": base_dn,
                "user_filter": user_filter,
                "group_allowlist": group_allowlist,
                "sync_page_size": sync_page_size,
            }
        )
        if action in ("save_service_account", "test_service_bind"):
            svc_user = (request.POST.get("service_user") or "").strip()
            svc_password = (request.POST.get("service_password") or "").strip()
            effective_svc_password = svc_password or _ldap_effective_service_password()
            defaults["service_user"] = svc_user
            defaults["service_password_configured"] = bool(_ldap_effective_service_password())
            if action == "save_service_account":
                ok, msg = _ldap_save_service_account(svc_user, svc_password)
                result_service = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
                if ok:
                    defaults = _ldap_file_defaults(runtime_cfg)
                    defaults["service_password_configured"] = bool(_ldap_effective_service_password())
                    ldap_cfg_source_labels = _ldap_effective_source_labels()
                    ldap_diag_rows, ldap_runtime_has_pending_restart, ldap_runtime_has_env_override = _ldap_diag_runtime_rows(runtime_cfg)
            else:
                if not server:
                    result_service = {
                        "ok": False,
                        "message": "Server LDAP non configurato nei valori effettivi. Controlla ambiente processo o .env.",
                    }
                else:
                    try:
                        ok, msg = _ldap_test_bind(
                            server,
                            int(timeout),
                            svc_user,
                            effective_svc_password,
                            domain,
                            upn_suffix,
                        )
                    except Exception as exc:
                        ok, msg = False, f"Errore connessione LDAP: {exc}"
                    result_service = {"ok": ok, "message": f"[Service Account] {msg}"}
                    (messages.success if ok else messages.error)(request, result_service["message"])
        elif action in ("test_smtp_connect", "test_smtp_send", "save_smtp_config"):
            smtp_host = (request.POST.get("smtp_host") or smtp_defaults["host"]).strip()
            smtp_port = _helpers._int_or_none(request.POST.get("smtp_port")) or int(smtp_defaults["port"])
            smtp_user = (request.POST.get("smtp_user") or smtp_defaults["user"]).strip()
            smtp_password = (request.POST.get("smtp_password") or "").strip()
            smtp_use_tls = _helpers._bool_from_any(request.POST.get("smtp_use_tls"))
            smtp_use_ssl = _helpers._bool_from_any(request.POST.get("smtp_use_ssl"))
            smtp_timeout = _helpers._int_or_none(request.POST.get("smtp_timeout")) or int(smtp_defaults["timeout"])
            smtp_from_email = (request.POST.get("smtp_default_from_email") or smtp_defaults["default_from_email"]).strip()
            smtp_test_to = (request.POST.get("smtp_test_to") or smtp_defaults.get("test_to") or "").strip()

            smtp_defaults.update(
                {
                    "host": smtp_host,
                    "port": smtp_port,
                    "user": smtp_user,
                    "password_configured": bool(smtp_password or smtp_defaults.get("password_configured")),
                    "use_tls": smtp_use_tls,
                    "use_ssl": smtp_use_ssl,
                    "timeout": smtp_timeout,
                    "default_from_email": smtp_from_email,
                    "test_to": smtp_test_to,
                }
            )

            if action == "test_smtp_connect":
                effective_password = smtp_password or _helpers._effective_env_value(
                    "EMAIL_HOST_PASSWORD",
                    str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""),
                )
                ok, msg = _smtp_test_connect(
                    smtp_host,
                    smtp_port,
                    smtp_user,
                    effective_password,
                    use_tls=smtp_use_tls,
                    use_ssl=smtp_use_ssl,
                    timeout=smtp_timeout,
                )
                result_smtp = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
            elif action == "test_smtp_send":
                effective_password = smtp_password or _helpers._effective_env_value(
                    "EMAIL_HOST_PASSWORD",
                    str(getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""),
                )
                ok, msg = _smtp_send_test_email(
                    smtp_host,
                    smtp_port,
                    smtp_user,
                    effective_password,
                    use_tls=smtp_use_tls,
                    use_ssl=smtp_use_ssl,
                    timeout=smtp_timeout,
                    from_email=smtp_from_email,
                    to_email=smtp_test_to,
                )
                result_smtp = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
            else:
                ok, msg = _smtp_save_settings(
                    host=smtp_host,
                    port=smtp_port,
                    user=smtp_user,
                    password=smtp_password,
                    use_tls=smtp_use_tls,
                    use_ssl=smtp_use_ssl,
                    timeout=smtp_timeout,
                    default_from_email=smtp_from_email,
                )
                result_smtp = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
        elif action in ("test_ollama_config", "save_ollama_config"):
            ollama_defaults = _helpers._ollama_posted_config(request.POST, ollama_defaults)
            if action == "test_ollama_config":
                ok, msg, metadata = _helpers._ollama_test_connect(ollama_defaults)
                result_ollama = {"ok": ok, "message": msg}
                _helpers._audit_safe(
                    request,
                    "ollama_config_test",
                    "admin_portale",
                    {
                        "ok": ok,
                        "provider": str(ollama_defaults.get("provider") or "ollama"),
                        "base_url_host": urlsplit(str(ollama_defaults.get("base_url") or "")).netloc,
                        "model": str(ollama_defaults.get("model") or ""),
                        "rag_enabled": bool(ollama_defaults.get("rag_enabled")),
                        "version": metadata.get("version") if isinstance(metadata, dict) else "",
                        "model_available": metadata.get("model_available") if isinstance(metadata, dict) else None,
                    },
                )
                (messages.success if ok else messages.error)(request, msg)
            else:
                ok, msg, normalized = _helpers._ollama_save_settings(ollama_defaults)
                result_ollama = {"ok": ok, "message": msg}
                if ok:
                    ollama_defaults = _helpers._ollama_diag_defaults()
                else:
                    ollama_defaults = normalized
                _helpers._audit_safe(
                    request,
                    "ollama_config_save",
                    "admin_portale",
                    {
                        "ok": ok,
                        "enabled": bool(ollama_defaults.get("enabled")),
                        "provider": str(ollama_defaults.get("provider") or "ollama"),
                        "base_url_host": urlsplit(str(ollama_defaults.get("base_url") or "")).netloc,
                        "model": str(ollama_defaults.get("model") or ""),
                        "rag_enabled": bool(ollama_defaults.get("rag_enabled")),
                        "rag_max_chunks": ollama_defaults.get("rag_max_chunks"),
                        "rag_max_db_entries": ollama_defaults.get("rag_max_db_entries"),
                    },
                )
                (messages.success if ok else messages.error)(request, msg)
        elif action == "save_approval_imap_config":
            posted_port = (request.POST.get("approval_imap_port") or "").strip()
            try:
                parsed_port = max(int(posted_port or approval_imap_form["port"]), 1)
            except (TypeError, ValueError):
                parsed_port = int(approval_imap_form["port"])

            approval_imap_form = {
                "host": (request.POST.get("approval_imap_host") or "").strip(),
                "port": parsed_port,
                "user": (request.POST.get("approval_imap_user") or "").strip(),
                "password": "",
                "folder": (request.POST.get("approval_imap_folder") or "").strip() or "INBOX",
                "use_ssl": _helpers._bool_from_any(request.POST.get("approval_imap_use_ssl")),
                "password_configured": bool((request.POST.get("approval_imap_password") or "").strip())
                or bool(approval_imap_form.get("password_configured")),
            }
            ok, msg = save_approval_imap_settings(
                host=str(approval_imap_form["host"]),
                port=int(approval_imap_form["port"]),
                user=str(approval_imap_form["user"]),
                password=(request.POST.get("approval_imap_password") or "").strip(),
                use_ssl=bool(approval_imap_form["use_ssl"]),
                folder=str(approval_imap_form["folder"]),
                dotenv_path=_helpers._dotenv_path(),
            )
            result_approval_imap = {"ok": ok, "message": msg, "output": "", "stats": {}}
            approval_imap_status = get_approval_imap_status()
            if ok:
                approval_imap_form = get_approval_imap_form_defaults()
            (messages.success if ok else messages.error)(request, msg)
        elif action == "run_approval_imap_poll":
            result_approval_imap = run_approval_imap_poll_now()
            approval_imap_status = get_approval_imap_status()
            (messages.success if result_approval_imap.get("ok") else messages.error)(
                request,
                str(result_approval_imap.get("message") or "Polling mailbox fallito."),
            )
        elif action == "save_ldap_config":
            enabled = _helpers._bool_from_any(request.POST.get("enabled"))
            defaults["enabled"] = enabled
            ok, msg = _ldap_save_settings(
                enabled=enabled,
                server=server,
                domain=domain,
                upn_suffix=upn_suffix,
                timeout=timeout,
                base_dn=base_dn,
                user_filter=user_filter,
                group_allowlist=group_allowlist,
                sync_page_size=sync_page_size,
            )
            result_connect = {"ok": ok, "message": msg}
            (messages.success if ok else messages.error)(request, msg)
            if ok:
                defaults = _ldap_file_defaults(runtime_cfg)
                defaults["service_password_configured"] = bool(_ldap_effective_service_password())
                ldap_cfg_source_labels = _ldap_effective_source_labels()
                ldap_diag_rows, ldap_runtime_has_pending_restart, ldap_runtime_has_env_override = _ldap_diag_runtime_rows(runtime_cfg)
        elif action == "test_connect":
            if not server:
                result_connect = {
                    "ok": False,
                    "message": "Server LDAP non configurato nei valori effettivi. Compila il campo oppure verifica ambiente processo e .env.",
                }
            else:
                ok, msg = _ldap_test_connect(server, int(timeout))
                result_connect = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
        elif action == "test_bind":
            if not server:
                result_bind = {
                    "ok": False,
                    "message": "Server LDAP non configurato nei valori effettivi. Compila il campo oppure verifica ambiente processo e .env.",
                }
            else:
                ok, msg = _ldap_test_bind(server, int(timeout), bind_username, bind_password, domain, upn_suffix)
                result_bind = {"ok": ok, "message": msg}
                (messages.success if ok else messages.error)(request, msg)
        elif action == "sync_users":
            sync_limit = _helpers._int_or_none(request.POST.get("sync_limit")) or 0
            sync_dry_run = _helpers._bool_from_any(request.POST.get("sync_dry_run"))
            sync_replace_allowlist = _helpers._bool_from_any(request.POST.get("sync_replace_allowlist"))
            sync_group_allowlist = (request.POST.get("sync_group_allowlist") or "").strip()
            ldap_sync_cfg.update(
                {
                    "sync_limit": sync_limit,
                    "sync_dry_run": sync_dry_run,
                    "sync_replace_allowlist": sync_replace_allowlist,
                    "group_allowlist": sync_group_allowlist or str(defaults.get("group_allowlist") or ""),
                }
            )

            cmd_out = StringIO()
            cmd_err = StringIO()
            cmd_kwargs = {"stdout": cmd_out, "stderr": cmd_err}
            service_password = _ldap_effective_service_password()
            if sync_dry_run:
                cmd_kwargs["dry_run"] = True
            if sync_limit > 0:
                cmd_kwargs["limit"] = int(sync_limit)
            if sync_replace_allowlist:
                cmd_kwargs["replace_allowlist_memberships"] = True
            if sync_group_allowlist:
                cmd_kwargs["group_allowlist"] = sync_group_allowlist
            else:
                effective_group_allowlist = str(defaults.get("group_allowlist") or "").strip()
                if effective_group_allowlist:
                    cmd_kwargs["group_allowlist"] = effective_group_allowlist
            cmd_kwargs.update(
                {
                    "ldap_enabled": _helpers._bool_from_any(defaults.get("enabled")),
                    "server": str(defaults.get("server") or "").strip(),
                    "domain": str(defaults.get("domain") or "").strip(),
                    "upn_suffix": str(defaults.get("upn_suffix") or "").strip(),
                    "timeout": int(defaults.get("timeout") or 5),
                    "service_user": str(defaults.get("service_user") or "").strip(),
                    "service_password": service_password,
                    "search_base": str(defaults.get("base_dn") or "").strip(),
                    "user_filter": str(defaults.get("user_filter") or "").strip(),
                    "page_size": int(defaults.get("sync_page_size") or 500),
                }
            )

            try:
                call_command("sync_ldap_users", **cmd_kwargs)
                out_text = (cmd_out.getvalue() or "").strip()
                err_text = (cmd_err.getvalue() or "").strip()
                full_output = "\n".join([part for part in [out_text, err_text] if part]).strip()
                sync_result = {"ok": True, "output": full_output}
                messages.success(request, "Sync utenti LDAP completata.")
            except Exception as exc:
                out_text = (cmd_out.getvalue() or "").strip()
                err_text = (cmd_err.getvalue() or "").strip()
                full_output = "\n".join([part for part in [out_text, err_text] if part]).strip()
                sync_result = {"ok": False, "output": full_output, "error": str(exc)}
                messages.error(request, f"Sync utenti LDAP fallita: {exc}")
        else:
            messages.warning(request, "Azione non riconosciuta.")

    ldap_effective_auth_missing = _ldap_missing_required_labels(defaults, ("enabled", "server"))
    ldap_effective_sync_missing = _ldap_missing_required_labels(
        defaults,
        ("enabled", "server", "service_user", "service_password", "base_dn", "user_filter"),
    )
    dotenv_target_label = _helpers._dotenv_target_label()

    return render(
        request,
        "admin_portale/pages/ldap_diagnostica.html",
        {
            "ldap_cfg": defaults,
            "ldap_cfg_source_labels": ldap_cfg_source_labels,
            "ldap_runtime_cfg": runtime_cfg,
            "ldap_runtime_rows": ldap_diag_rows,
            "ldap_runtime_has_pending_restart": ldap_runtime_has_pending_restart,
            "ldap_runtime_has_env_override": ldap_runtime_has_env_override,
            "ldap_effective_auth_ready": len(ldap_effective_auth_missing) == 0,
            "ldap_effective_auth_missing": ldap_effective_auth_missing,
            "ldap_effective_sync_ready": len(ldap_effective_sync_missing) == 0,
            "ldap_effective_sync_missing": ldap_effective_sync_missing,
            "ldap_sync_cfg": ldap_sync_cfg,
            "dotenv_target_label": dotenv_target_label,
            "smtp_cfg": smtp_defaults,
            "ollama_cfg": ollama_defaults,
            "approval_imap_status": approval_imap_status,
            "approval_imap_form": approval_imap_form,
            "result_connect": result_connect,
            "result_bind": result_bind,
            "result_service": result_service,
            "result_smtp": result_smtp,
            "result_ollama": result_ollama,
            "result_approval_imap": result_approval_imap,
            "bind_username": bind_username,
            "sync_result": sync_result,
        },
    )


@legacy_admin_required
def ldap_import_utenti(request):
    """Pagina importazione selettiva utenti da LDAP/AD."""
    server_url = _helpers._effective_env_value("LDAP_SERVER", str(getattr(settings, "LDAP_SERVER", "") or ""))
    service_user = _helpers._effective_env_value("LDAP_SERVICE_USER", str(getattr(settings, "LDAP_SERVICE_USER", "") or ""))
    service_password = _ldap_effective_service_password()
    base_dn = _helpers._effective_env_value("LDAP_BASE_DN", str(getattr(settings, "LDAP_BASE_DN", "") or ""))
    user_filter_tmpl = _helpers._effective_env_value(
        "LDAP_USER_FILTER",
        str(getattr(settings, "LDAP_USER_FILTER", "") or ""),
    )
    domain = _helpers._effective_env_value("LDAP_DOMAIN", str(getattr(settings, "LDAP_DOMAIN", "") or ""))
    upn_suffix = _helpers._effective_env_value("LDAP_UPN_SUFFIX", str(getattr(settings, "LDAP_UPN_SUFFIX", "") or ""))
    timeout = _helpers._effective_env_int("LDAP_TIMEOUT", int(getattr(settings, "LDAP_TIMEOUT", 5) or 5))
    ldap_enabled = _helpers._effective_env_bool("LDAP_ENABLED", bool(getattr(settings, "LDAP_ENABLED", False)))
    ldap_configured = bool(server_url and service_user and service_password and base_dn and user_filter_tmpl)

    if request.method == "GET":
        return render(
            request,
            "admin_portale/pages/ldap_import.html",
            {
                "ldap_enabled": ldap_enabled,
                "ldap_configured": ldap_configured,
                "ldap_server": server_url,
                "roles": _helpers._role_choices(),
            },
        )

    # POST — azioni AJAX
    action = (request.POST.get("action") or "").strip()

    if not ldap_configured:
        return JsonResponse(
            {"ok": False, "error": "LDAP non configurato (server, service account, password o base DN mancanti)."},
            status=400,
        )

    try:
        from ldap3 import NTLM, SIMPLE, SUBTREE, Connection
        from ldap3.core.exceptions import LDAPException, LDAPSocketOpenError
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"ldap3 non disponibile: {exc}"}, status=500)

    def _ldap_connect():
        srv = build_ldap_server(server_url, timeout)
        if "\\" in service_user:
            attempts = [(service_user, NTLM)]
        elif "@" in service_user:
            attempts = [(service_user, SIMPLE)]
        else:
            attempts = []
            suffix = (upn_suffix or "").strip().lstrip("@")
            if suffix:
                attempts.append((f"{service_user}@{suffix}", SIMPLE))
            attempts.append((service_user, SIMPLE))
            if domain:
                attempts.append((f"{domain}\\{service_user}", NTLM))

        last_result = None
        for bind_user, authentication in attempts:
            conn = Connection(
                srv,
                user=bind_user,
                password=service_password,
                authentication=authentication,
                auto_bind=False,
                auto_referrals=False,
                raise_exceptions=False,
                receive_timeout=ldap_receive_timeout(),
            )
            if conn.bind():
                return conn, None
            last_result = conn.result
            try:
                conn.unbind()
            except Exception:
                pass
        return None, f"Bind LDAP fallito: {last_result}"

    def _first(data, key):
        raw = data.get(key)
        if isinstance(raw, list):
            return str(raw[0]).strip() if raw else ""
        return str(raw or "").strip()

    def _entry_to_user(data):
        upn = _first(data, "userPrincipalName").lower()
        mail = _first(data, "mail").lower()
        sam = _first(data, "sAMAccountName")
        given = _first(data, "givenName")
        sn = _first(data, "sn")
        display = naming.normalizza_parte(_first(data, "displayName")) or naming.nome_completo(given, sn) or sam
        if not upn and sam and upn_suffix:
            upn = f"{sam.lower()}@{upn_suffix.lstrip('@')}"
        ident = upn or mail
        member_dns = data.get("memberOf") or []
        if isinstance(member_dns, str):
            member_dns = [member_dns]
        groups = []
        for dn in member_dns:
            for part in str(dn).split(","):
                chunk = part.strip()
                if chunk.upper().startswith("CN="):
                    groups.append(chunk[3:])
                    break
        return ident, sam, display, groups[:8]

    if action == "search":
        name_q = (request.POST.get("q") or "").strip()
        if name_q:
            ldap_filter = f"(&{user_filter_tmpl}(|(displayName=*{name_q}*)(sAMAccountName=*{name_q}*)(mail=*{name_q}*)))"
        else:
            ldap_filter = user_filter_tmpl

        try:
            conn, err = _ldap_connect()
            if not conn:
                return JsonResponse({"ok": False, "error": err}, status=400)
        except (LDAPSocketOpenError, LDAPException, OSError) as exc:
            return JsonResponse({"ok": False, "error": f"Connessione LDAP fallita: {exc}"}, status=400)

        attrs = ["displayName", "givenName", "sn", "mail", "userPrincipalName", "sAMAccountName", "memberOf"]
        try:
            ok = conn.search(
                search_base=base_dn,
                search_filter=ldap_filter,
                search_scope=SUBTREE,
                attributes=attrs,
                paged_size=500,
            )
        except (LDAPSocketOpenError, LDAPException, OSError) as exc:
            conn.unbind()
            return JsonResponse({"ok": False, "error": f"Ricerca LDAP fallita: {exc}"}, status=400)
        if not ok:
            conn.unbind()
            return JsonResponse({"ok": False, "error": f"Ricerca LDAP fallita: {conn.result}"}, status=400)

        existing_emails = {(e or "").strip().lower() for e in UtenteLegacy.objects.values_list("email", flat=True) if e}

        users = []
        for entry in conn.entries:
            data = entry.entry_attributes_as_dict if hasattr(entry, "entry_attributes_as_dict") else {}
            ident, sam, display, groups = _entry_to_user(data)
            if not ident:
                continue
            users.append({
                "display_name": display,
                "email": ident,
                "sam": sam,
                "groups": groups,
                "already_imported": ident.lower() in existing_emails,
            })

        conn.unbind()
        users.sort(key=lambda u: (u["already_imported"], (u["display_name"] or "").lower()))
        return JsonResponse({"ok": True, "users": users, "total": len(users)})

    elif action == "import":
        selected_emails_raw = request.POST.getlist("emails[]")
        ruolo_id = _helpers._int_or_none(request.POST.get("ruolo_id"))

        if not selected_emails_raw:
            return JsonResponse({"ok": False, "error": "Nessun utente selezionato."}, status=400)

        target_set = {e.strip().lower() for e in selected_emails_raw if e.strip()}

        ruolo_name = ""
        if ruolo_id:
            try:
                ruolo_obj = Ruolo.objects.filter(id=ruolo_id).first()
                if ruolo_obj:
                    ruolo_name = (ruolo_obj.nome or "").strip()
            except DatabaseError:
                pass
        if not ruolo_name:
            try:
                default_role = Ruolo.objects.filter(nome__iexact="utente").first()
                if default_role:
                    ruolo_name = default_role.nome
                    ruolo_id = int(default_role.id)
            except DatabaseError:
                pass

        from core.legacy_utils import legacy_table_columns, sync_django_user_from_legacy
        user_cols = legacy_table_columns("utenti")
        has_json_ruoli = "ruoli" in user_cols

        # Costruisce filtro LDAP mirato se pochi utenti, altrimenti cerca tutti e filtra
        if len(target_set) <= 30:
            upn_clauses = "".join(f"(userPrincipalName={e})" for e in target_set)
            mail_clauses = "".join(f"(mail={e})" for e in target_set)
            ldap_filter = f"(&{user_filter_tmpl}(|{upn_clauses}{mail_clauses}))"
        else:
            ldap_filter = user_filter_tmpl

        try:
            conn, err = _ldap_connect()
            if not conn:
                return JsonResponse({"ok": False, "error": err}, status=400)
        except (LDAPSocketOpenError, LDAPException, OSError) as exc:
            return JsonResponse({"ok": False, "error": f"Connessione LDAP fallita: {exc}"}, status=400)

        attrs = ["displayName", "givenName", "sn", "mail", "userPrincipalName", "sAMAccountName"]
        try:
            ok = conn.search(
                search_base=base_dn,
                search_filter=ldap_filter,
                search_scope=SUBTREE,
                attributes=attrs,
                paged_size=500,
            )
        except (LDAPSocketOpenError, LDAPException, OSError) as exc:
            conn.unbind()
            return JsonResponse({"ok": False, "error": f"Ricerca LDAP fallita: {exc}"}, status=400)
        if not ok:
            conn.unbind()
            return JsonResponse({"ok": False, "error": f"Ricerca LDAP fallita: {conn.result}"}, status=400)

        results = {"created": [], "updated": [], "errors": []}

        try:
            with transaction.atomic():
                for entry in conn.entries:
                    data = entry.entry_attributes_as_dict if hasattr(entry, "entry_attributes_as_dict") else {}
                    ident, sam, display, _groups = _entry_to_user(data)
                    if not ident:
                        continue
                    if len(target_set) > 30 and ident.lower() not in target_set:
                        continue

                    try:
                        legacy_user = UtenteLegacy.objects.filter(email__iexact=ident).first()
                        if legacy_user is None:
                            create_kwargs = {
                                "nome": display,
                                "email": ident,
                                "password": "*AD_MANAGED*",
                                "ruolo": ruolo_name,
                                "attivo": True,
                                "deve_cambiare_password": False,
                            }
                            if ruolo_id:
                                create_kwargs["ruolo_id"] = ruolo_id
                            if has_json_ruoli:
                                create_kwargs["ruoli"] = f'["{ruolo_name}"]' if ruolo_name else "[]"
                            legacy_user = UtenteLegacy.objects.create(**create_kwargs)
                            sync_django_user_from_legacy(legacy_user)
                            results["created"].append({"nome": display, "email": ident})
                            _helpers._audit_safe(request, "ldap_import_user_create", "admin_portale", {
                                "email": ident, "nome": display, "ruolo_id": ruolo_id, "ruolo": ruolo_name,
                            })
                        else:
                            changed = []
                            if (legacy_user.password or "") != "*AD_MANAGED*":
                                legacy_user.password = "*AD_MANAGED*"
                                changed.append("password")
                            if not bool(legacy_user.attivo):
                                legacy_user.attivo = True
                                changed.append("attivo")
                            if changed:
                                legacy_user.save(update_fields=changed)
                            sync_django_user_from_legacy(legacy_user)
                            results["updated"].append({"nome": display, "email": ident})
                            _helpers._audit_safe(request, "ldap_import_user_update", "admin_portale", {
                                "email": ident, "nome": display, "changed": changed,
                            })
                    except DatabaseError as exc:
                        results["errors"].append({"email": ident, "error": str(exc)})
        except Exception as exc:
            conn.unbind()
            return JsonResponse({"ok": False, "error": f"Errore durante l'importazione: {exc}"}, status=500)

        conn.unbind()
        return JsonResponse({"ok": True, "results": results})

    return JsonResponse({"ok": False, "error": "Azione non valida."}, status=400)


@legacy_admin_required
@require_GET
def utenti_list(request):
    q = (request.GET.get("q") or "").strip()
    attivo_filter = (request.GET.get("attivo") or "").strip()
    ruolo_filter = (request.GET.get("ruolo_id") or "").strip()
    pwd_filter = (request.GET.get("pwd_change") or "").strip()
    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)

    utenti_qs = UtenteLegacy.objects.all().order_by("id")
    if q:
        utenti_qs = utenti_qs.filter(Q(nome__icontains=q) | Q(email__icontains=q) | naming.q_persona(q, "nome"))
    if attivo_filter in {"0", "1"}:
        utenti_qs = utenti_qs.filter(attivo=bool(int(attivo_filter)))
    if ruolo_filter.isdigit():
        utenti_qs = utenti_qs.filter(ruolo_id=int(ruolo_filter))
    if pwd_filter in {"0", "1"}:
        utenti_qs = utenti_qs.filter(deve_cambiare_password=bool(int(pwd_filter)))

    paginator = Paginator(utenti_qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    utenti_page = list(page_obj.object_list)
    _attach_anagrafica_to_users(utenti_page)
    page_obj.object_list = utenti_page
    roles = _helpers._role_choices()
    role_map = {int(r.id): r for r in roles}

    # Attacca info 2FA direttamente su ogni oggetto utente (twofa_info o None)
    _attach_twofa_to_users(utenti_page)
    sistema_ruoli = _attach_ruoli_portale_to_users(utenti_page)

    return render(
        request,
        "admin_portale/pages/utenti_list.html",
        {
            "page_obj": page_obj,
            "roles": roles,
            "role_map": role_map,
            "filters": {"q": q, "attivo": attivo_filter, "ruolo_id": ruolo_filter, "pwd_change": pwd_filter},
            "create_form": UtenteCreateForm(initial={"attivo": True, "deve_cambiare_password": True}),
            "current_legacy_user_id": int(current_legacy_user.id) if current_legacy_user else None,
            "sistema_ruoli": sistema_ruoli,
        },
    )


def _attach_ruoli_portale_to_users(users: list) -> bool:
    """Con «Ruoli e permessi» acceso attacca ``ruoli_portale`` a ogni utente.

    A sistema acceso il ruolo legacy (``utenti.ruolo_id``) non decide piu' nulla:
    la colonna deve mostrare i ruoli del portale (a mano + organigramma), dal piu'
    alto in ordine, cioe' quello che comanda. Ritorna se il sistema e' acceso.
    """
    from core.permessi.motore import PRESET_BASE, sistema_ruoli_attivo

    if not sistema_ruoli_attivo():
        return False
    for u in users:
        u.ruoli_portale = []
        u.ruolo_portale_base = ""
    ids = [int(u.id) for u in users if u.id]
    if not ids:
        return True
    try:
        from core.models import AccessGroup, AccessGroupMembership
        from core.permessi.organigramma import provenienze_per_utenti
        from core.permessi.scadenze import q_appartenenze_valide

        a_mano: dict[int, set[int]] = {}
        for uid, gid in AccessGroupMembership.objects.filter(
            q_appartenenze_valide(), legacy_user_id__in=ids
        ).values_list("legacy_user_id", "group_id"):
            a_mano.setdefault(int(uid), set()).add(int(gid))
        da_org = {int(uid): set(gruppi) for uid, gruppi in provenienze_per_utenti(ids).items()}
        tutti = set().union(*a_mano.values(), *da_org.values()) if (a_mano or da_org) else set()
        gruppi = {
            int(g.id): g
            for g in AccessGroup.objects.filter(is_active=True).filter(Q(id__in=tutti) | Q(preset=PRESET_BASE))
        }
    except DatabaseError:
        logger.warning("utenti_list: ruoli del portale non leggibili", exc_info=True)
        return True
    base = next((g for g in gruppi.values() if g.preset == PRESET_BASE), None)
    for u in users:
        uid = int(u.id or 0)
        mano, org = a_mano.get(uid, set()), da_org.get(uid, set())
        propri = [g for gid, g in gruppi.items() if gid in (mano | org) and g.preset != PRESET_BASE]
        propri.sort(key=lambda g: (-int(g.priority or 0), str(g.label or ""), int(g.id)))
        u.ruoli_portale = [
            {"id": int(g.id), "label": str(g.label or "").strip() or f"#{g.id}", "da_organigramma": int(g.id) in org and int(g.id) not in mano}
            for g in propri
        ]
        if not propri and base is not None:
            u.ruolo_portale_base = str(base.label or "").strip() or "Ruolo base"
    return True


def _attach_twofa_to_users(users: list) -> None:
    """Attacca `twofa_info` (dict o None) a ogni UtenteLegacy della lista."""
    if not users:
        return
    try:
        from core.models import Profile
        from twofa.models import UserTwoFactor

        legacy_ids = [int(u.id) for u in users if u.id]
        profiles = Profile.objects.filter(legacy_user_id__in=legacy_ids).values("legacy_user_id", "user_id")
        legacy_to_django = {int(p["legacy_user_id"]): int(p["user_id"]) for p in profiles}

        django_ids = list(legacy_to_django.values())
        u2f_records = UserTwoFactor.objects.filter(user_id__in=django_ids).values(
            "user_id", "method", "is_active", "totp_confirmed", "force_setup"
        )
        django_to_u2f = {int(r["user_id"]): r for r in u2f_records}

        for u in users:
            django_id = legacy_to_django.get(int(u.id)) if u.id else None
            u2f = django_to_u2f.get(django_id) if django_id else None
            if django_id is None:
                u.twofa_info = None
            else:
                u.twofa_info = {
                    "django_user_id": django_id,
                    "method": u2f["method"] if u2f else None,
                    "is_active": u2f["is_active"] if u2f else None,
                    "totp_confirmed": u2f["totp_confirmed"] if u2f else False,
                    "configured": u2f is not None,
                }
    except Exception:
        for u in users:
            u.twofa_info = None


def _attach_anagrafica_to_users(users: list[UtenteLegacy]) -> None:
    """Arricchisce gli utenti con campi da anagrafica_dipendenti.

    Strategia: JOIN diretto via utente_id (FK) se disponibile,
    con fallback a match per email/alias per record non ancora collegati.
    """
    if not users:
        return
    cols = legacy_table_columns("anagrafica_dipendenti")
    if not cols:
        return

    selectable = ["id", "utente_id", "email", "email_notifica", "reparto", "mansione", "aliasusername", "attivo"]
    select_cols = [c for c in selectable if c in cols]
    has_utente_id = "utente_id" in select_cols

    user_ids = [int(u.id) for u in users if u.id]
    if not user_ids:
        return

    by_utente_id: dict[int, dict] = {}
    orphans: list[dict] = []

    try:
        if has_utente_id:
            placeholders = ", ".join(["%s"] * len(user_ids))
            sql = (
                f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti "
                f"WHERE utente_id IN ({placeholders})"
            )
            with connections["default"].cursor() as cur:
                cur.execute(sql, user_ids)
                db_cols = [str(c[0]).lower() for c in cur.description]
                for row in cur.fetchall():
                    record = dict(zip(db_cols, row))
                    uid = record.get("utente_id")
                    if uid is not None:
                        by_utente_id[int(uid)] = record

        # Fallback per utenti non ancora collegati tramite FK
        unlinked = [u for u in users if int(u.id) not in by_utente_id]
        if unlinked and "email" in cols:
            emails = sorted({str(u.email or "").strip().lower() for u in unlinked if str(u.email or "").strip()})
            aliases = sorted(
                {
                    str(u.email or "").strip().lower().split("@", 1)[0]
                    for u in unlinked
                    if "@" in str(u.email or "").strip().lower()
                }
            )
            if emails or aliases:
                where_parts: list[str] = []
                params: list[str] = []
                if emails:
                    where_parts.append("LOWER(COALESCE(email,'')) IN (" + ", ".join(["%s"] * len(emails)) + ")")
                    params.extend(emails)
                if aliases and "aliasusername" in select_cols:
                    where_parts.append(
                        "LOWER(COALESCE(aliasusername,'')) IN (" + ", ".join(["%s"] * len(aliases)) + ")"
                    )
                    params.extend(aliases)
                if where_parts:
                    sql = (
                        f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti "
                        "WHERE " + " OR ".join(where_parts)
                    )
                    with connections["default"].cursor() as cur:
                        cur.execute(sql, params)
                        db_cols = [str(c[0]).lower() for c in cur.description]
                        orphans = [dict(zip(db_cols, row)) for row in cur.fetchall()]
    except Exception:
        return

    for u in users:
        uid = int(u.id)
        row: dict = by_utente_id.get(uid, {})

        if not row and orphans:
            user_email = str(u.email or "").strip().lower()
            user_alias = user_email.split("@", 1)[0] if "@" in user_email else ""
            best_score = -1
            for cand in orphans:
                row_email = str(cand.get("email") or "").strip().lower()
                row_alias = str(cand.get("aliasusername") or "").strip().lower()
                score = 0
                if row_email and row_email == user_email:
                    score += 8
                elif user_alias and row_alias and row_alias == user_alias:
                    score += 5
                else:
                    continue
                if str(cand.get("reparto") or "").strip():
                    score += 2
                if str(cand.get("mansione") or "").strip():
                    score += 1
                if score > best_score:
                    best_score = score
                    row = cand

        u.anagrafica_reparto = str(row.get("reparto") or "").strip()
        u.anagrafica_mansione = str(row.get("mansione") or "").strip()
        u.anagrafica_aliasusername = str(row.get("aliasusername") or "").strip()
        u.anagrafica_email_notifica = str(row.get("email_notifica") or "").strip()
        raw_attivo = row.get("attivo")
        if raw_attivo is None:
            u.anagrafica_attivo = None
        else:
            u.anagrafica_attivo = bool(raw_attivo)


def _sync_legacy_user_to_anagrafica(utente: UtenteLegacy, *, force_active: bool | None = None) -> dict:
    ensure_anagrafica_schema()
    return sync_anagrafica_from_legacy_user(utente, force_active=force_active)


def _load_caporeparto_options() -> list[dict[str, str]]:
    """Carica le opzioni caporeparto configurate localmente nel portale."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for option in OptioneConfig.objects.filter(tipo__iexact="caporeparto", is_active=True).order_by("ordine", "valore", "id"):
        txt = str(option.valore or "").strip()
        legacy_user_id = _helpers._int_or_none(getattr(option, "legacy_user_id", None))
        key = str(legacy_user_id or txt).strip().casefold()
        if not txt or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "value": txt,
                "label": format_caporeparto_label(txt, legacy_user_id=legacy_user_id),
                "title": txt,
                "legacy_user_id": str(legacy_user_id or ""),
            }
        )

    return out


@legacy_admin_required
@require_GET
def utente_edit(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    roles = _helpers._role_choices()
    flag_names = _helpers._perm_flag_names()

    # Permessi del ruolo
    perm_rows: list[_helpers.PermRow] = []
    grouped_perm_rows: list[tuple[str, list[_helpers.PermRow]]] = []
    if utente.ruolo_id:
        try:
            perm_rows = _helpers._permission_rows_for_role(int(utente.ruolo_id))
            grouped_perm_rows = _group_perm_rows_by_modulo(perm_rows)
        except DatabaseError:
            pass

    # Override per-utente (mappa {(modulo, azione): dict_flags})
    overrides_map: dict[str, dict] = {}
    try:
        for ov in UserPermissionOverride.objects.filter(legacy_user_id=utente.id):
            key = f"{ov.modulo}|{ov.azione}"
            overrides_map[key] = {
                "can_view": ov.can_view,
                "can_edit": ov.can_edit,
                "can_delete": ov.can_delete,
                "can_approve": ov.can_approve,
            }
    except Exception:
        pass

    # Dashboard: tutti i pulsanti del ruolo + visibilitÃ  per-utente (pulsante + modulo)
    dash_by_module: list[dict] = []
    module_vis_map: dict[str, bool] = {}
    try:
        dash_hidden: set[int] = {
            row.pulsante_id
            for row in UserDashboardConfig.objects.filter(legacy_user_id=utente.id, visible=False)
        }
        module_vis_map = {
            mv.modulo.lower(): mv.visible
            for mv in UserModuleVisibility.objects.filter(legacy_user_id=utente.id)
        }
        # Costruisce lista flat, poi raggruppa per modulo
        flat: list[dict] = []
        for pr in perm_rows:
            try:
                puls = Pulsante.objects.filter(
                    modulo__iexact=pr.modulo, codice__iexact=pr.azione
                ).first()
                if not puls:
                    continue
                pid = int(puls.id)
                modulo_display = (puls.modulo or pr.modulo or "Generale").strip() or "Generale"
                flat.append({
                    "pulsante_id": pid,
                    "name": puls.label,
                    "modulo": modulo_display,
                    "url": (puls.url or "").strip(),
                    "puls_visible": pid not in dash_hidden,
                })
            except Exception:
                continue

        # Raggruppa per modulo mantenendo l'ordine di prima comparsa
        seen_mod: dict[str, dict] = {}
        for item in flat:
            mod = item["modulo"]
            if mod not in seen_mod:
                seen_mod[mod] = {
                    "modulo": mod,
                    "module_visible": module_vis_map.get(mod.lower(), True),
                    "pulsanti": [],
                }
            seen_mod[mod]["pulsanti"].append(item)
        dash_by_module = list(seen_mod.values())
    except Exception:
        pass

    # Anagrafica: lookup via utente_id (FK) con fallback su email
    anagrafica_row: dict | None = None
    try:
        all_cols = legacy_table_columns("anagrafica_dipendenti")
        selectable = ["nome", "cognome", "reparto", "mansione", "email", "email_notifica", "aliasusername", "attivo", "utente_id"]
        select_cols = [c for c in selectable if c in all_cols]
        if select_cols:
            with connections["default"].cursor() as cur:
                if "utente_id" in all_cols:
                    cur.execute(
                        f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti WHERE utente_id = %s",
                        [utente.id],
                    )
                    row = cur.fetchone()
                    if not row and utente.email:
                        cur.execute(
                            f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti WHERE LOWER(email) = LOWER(%s)",
                            [utente.email.strip()],
                        )
                        row = cur.fetchone()
                elif utente.email:
                    cur.execute(
                        f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti WHERE LOWER(email) = LOWER(%s)",
                        [utente.email.strip()],
                    )
                    row = cur.fetchone()
                else:
                    row = None
                if row:
                    anagrafica_row = dict(zip([c[0] for c in cur.description], row))
    except Exception:
        pass

    # Extra info (upsert on save)
    extra_info = UserExtraInfo.objects.filter(legacy_user_id=utente.id).first()

    # Asset assegnabili/assegnati al dipendente
    assets_for_assignment = []
    asset_assigned_ids: list[int] = []
    asset_model = _asset_model()
    if asset_model is not None:
        try:
            assets_for_assignment = list(
                asset_model.objects.all()
                .order_by("asset_tag", "name", "id")
                .only("id", "asset_tag", "name", "status", "assignment_to", "assigned_legacy_user_id")
            )
            asset_assigned_ids = [
                int(a.id)
                for a in assets_for_assignment
                if int(getattr(a, "assigned_legacy_user_id", 0) or 0) == int(utente.id)
            ]
        except Exception:
            assets_for_assignment = []
            asset_assigned_ids = []

    # Opzioni dropdown configurabili (reparto, caporeparto, macchina, ...)
    opzioni_by_tipo: dict[str, list[str]] = {}
    for o in OptioneConfig.objects.filter(is_active=True):
        opzioni_by_tipo.setdefault(o.tipo, []).append(o.valore)
    caporeparto_options = _load_caporeparto_options()

    # Campi extra anagrafica configurabili
    anagrafica_voci = list(AnagraficaVoce.objects.filter(is_active=True).order_by("categoria", "ordine", "id"))
    for v in anagrafica_voci:
        v.scelte_json = json.dumps(v.scelte)

    # Risposte salvate per questo utente
    anagrafica_risposte_map: dict[int, str] = {
        r.voce_id: r.valore
        for r in AnagraficaRisposta.objects.filter(legacy_user_id=utente.id)
    }

    # Onboarding wizard primo accesso
    onboarding_data = None
    django_user_id = None
    django_username = None
    ui_prefs_data = None
    try:
        from core.models import Profile, UserOnboarding
        _profile = Profile.objects.filter(legacy_user_id=utente.id).select_related("user").first()
        if _profile:
            django_user_id = _profile.user_id
            if _profile.user:
                django_username = _profile.user.username
            onboarding_data = UserOnboarding.objects.filter(user_id=django_user_id).first()
            ui_prefs_data = UserUiPreference.objects.filter(user_id=django_user_id).first()
    except Exception:
        pass

    return render(
        request,
        "admin_portale/pages/utente_edit.html",
        {
            "utente_obj": utente,
            "roles": roles,
            "flag_names": flag_names,
            "grouped_perm_rows": grouped_perm_rows,
            "overrides_map": overrides_map,
            "overrides_map_json": json.dumps(overrides_map),
            "dash_by_module": dash_by_module,
            "module_vis_json": json.dumps(module_vis_map),
            "anagrafica_row": anagrafica_row,
            "extra_info": extra_info,
            "assets_for_assignment": assets_for_assignment,
            "asset_assigned_ids": asset_assigned_ids,
            "opzioni_by_tipo": opzioni_by_tipo,
            "caporeparto_options": caporeparto_options,
            "anagrafica_voci": anagrafica_voci,
            "anagrafica_risposte_map": anagrafica_risposte_map,
            "anagrafica_risposte_json": json.dumps(anagrafica_risposte_map),
            "checklist_checkin":  ChecklistEsecuzione.objects.filter(legacy_user_id=utente.id, tipo_checklist="checkin").first(),
            "checklist_checkout": ChecklistEsecuzione.objects.filter(legacy_user_id=utente.id, tipo_checklist="checkout").first(),
            "current_legacy_user_id": int(current_legacy_user.id) if current_legacy_user else None,
            "onboarding_data": onboarding_data,
            "django_user_id": django_user_id,
            "django_username": django_username,
            "ui_prefs_data": ui_prefs_data,
        },
    )


@legacy_admin_required
@csrf_protect
@require_POST
def utente_create(request):
    form = UtenteCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Dati nuovo utente non validi: {form.errors.as_text()}")
        return redirect("admin_portale:utenti_list")

    data = form.cleaned_data
    ruolo_id = _helpers._int_or_none(data.get("ruolo_id"))
    ruolo_name = ""
    if ruolo_id:
        try:
            ruolo = Ruolo.objects.filter(id=ruolo_id).first()
            if ruolo:
                ruolo_name = (ruolo.nome or "").strip()
        except DatabaseError:
            ruolo_name = ""

    if bool(data.get("ad_managed")):
        password_value = "*AD_MANAGED*"
    else:
        password_value = generate_password_hash((data.get("password_iniziale") or "").strip())

    try:
        with transaction.atomic():
            utente = UtenteLegacy.objects.create(
                nome=naming.normalizza_parte(data.get("nome")),
                email=(data.get("email") or "").strip(),
                password=password_value,
                ruolo=ruolo_name,
                ruolo_id=ruolo_id,
                attivo=bool(data.get("attivo")),
                deve_cambiare_password=bool(data.get("deve_cambiare_password")),
            )
            _sync_legacy_user_to_anagrafica(utente)
        _helpers._audit_safe(request, "utente_create", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "nome": utente.nome,
            "email": utente.email,
            "ruolo_id": utente.ruolo_id,
            "ruolo": utente.ruolo,
            "attivo": bool(utente.attivo),
            "ad_managed": bool(data.get("ad_managed")),
        })
        messages.success(request, f"Utente creato (ID {utente.id}).")
    except DatabaseError as exc:
        messages.error(request, f"Errore creazione utente: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore creazione utente/anagrafica: {exc}")

    return redirect("admin_portale:utenti_list")


def _delete_legacy_user_with_dependencies(utente: UtenteLegacy) -> dict[str, int]:
    profile = Profile.objects.select_related("user").filter(legacy_user_id=utente.id).first()
    django_user_id = int(profile.user_id) if profile and profile.user_id else 0
    asset_model = _asset_model()
    released_assets = 0

    with transaction.atomic():
        if asset_model is not None:
            assigned_ids = list(asset_model.objects.filter(assigned_legacy_user_id=utente.id).values_list("id", flat=True))
            with _storico_asset(assigned_ids, fonte="admin", dettaglio=f"Eliminazione utente #{utente.id}"):
                released_assets = int(
                    asset_model.objects.filter(assigned_legacy_user_id=utente.id).update(
                        assigned_legacy_user_id=None,
                        assignment_to="",
                        assignment_reparto="",
                    )
                )

        UserPermissionOverride.objects.filter(legacy_user_id=utente.id).delete()
        UserDashboardConfig.objects.filter(legacy_user_id=utente.id).delete()
        UserModuleVisibility.objects.filter(legacy_user_id=utente.id).delete()
        UserDashboardLayout.objects.filter(legacy_user_id=utente.id).delete()
        UserExtraInfo.objects.filter(legacy_user_id=utente.id).delete()
        EmployeeBoardConfig.objects.filter(legacy_user_id=utente.id).delete()
        AnagraficaRisposta.objects.filter(legacy_user_id=utente.id).delete()
        ChecklistEsecuzione.objects.filter(legacy_user_id=utente.id).delete()
        Notifica.objects.filter(legacy_user_id=utente.id).delete()
        anagrafica_unlinked = int(AnagraficaDipendente.objects.filter(utente_id=utente.id).update(utente=None))

        if profile and profile.user_id:
            profile.user.delete()
        else:
            Profile.objects.filter(legacy_user_id=utente.id).delete()

        utente.delete()

    return {
        "django_user_id": django_user_id,
        "released_assets": released_assets,
        "anagrafica_unlinked": anagrafica_unlinked,
    }


@legacy_admin_required
@csrf_protect
@require_POST
def utente_update(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    form = UtenteUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Dati non validi: {form.errors.as_text()}")
        return redirect("admin_portale:utente_edit", user_id=user_id)

    data = form.cleaned_data
    utente.nome = naming.normalizza_parte(data.get("nome"))
    utente.email = (data.get("email") or "").strip()
    utente.attivo = bool(data.get("attivo"))
    utente.ruolo_id = _helpers._int_or_none(data.get("ruolo_id"))
    utente.deve_cambiare_password = bool(data.get("deve_cambiare_password")) or bool(data.get("force_password_reset"))

    if utente.ruolo_id:
        try:
            ruolo = Ruolo.objects.filter(id=utente.ruolo_id).first()
            if ruolo:
                utente.ruolo = (ruolo.nome or "").strip()
        except DatabaseError:
            pass

    # Lo username NON si modifica da qui: la fonte di verità è
    # `anagrafica_dipendenti.aliasusername`, gestito dalla scheda dipendente
    # (`anagrafica:dipendente_username_set`), che lo propaga all'account Django.

    try:
        with transaction.atomic():
            utente.save()
            _sync_legacy_user_to_anagrafica(utente)
        _helpers._audit_safe(request, "utente_update", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "nome": utente.nome,
            "email": utente.email,
            "ruolo_id": utente.ruolo_id,
            "ruolo": utente.ruolo,
            "attivo": bool(utente.attivo),
            "deve_cambiare_password": bool(utente.deve_cambiare_password),
        })
        messages.success(request, f"Utente #{utente.id} aggiornato.")
    except DatabaseError as exc:
        messages.error(request, f"Errore salvataggio utente: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore sincronizzazione utente/anagrafica: {exc}")

    return redirect("admin_portale:utente_edit", user_id=user_id)


@legacy_admin_required
@csrf_protect
@require_POST
def utenti_bulk_role(request):
    form = BulkRoleForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Dati non validi: {form.errors.as_text()}")
        return redirect("admin_portale:utenti_list")

    ids_from_checkboxes = [_helpers._int_or_none(v) for v in request.POST.getlist("user_ids")]
    ids = [v for v in ids_from_checkboxes if v is not None]
    ids = ids or form.cleaned_user_ids()
    ruolo_id = form.cleaned_data["ruolo_id"]
    role_name = _role_name_map().get(int(ruolo_id), "")

    if not ids:
        messages.warning(request, "Nessun utente selezionato.")
        return redirect("admin_portale:utenti_list")

    try:
        with transaction.atomic():
            UtenteLegacy.objects.filter(id__in=ids).update(ruolo_id=ruolo_id, ruolo=role_name)
        _helpers._audit_safe(request, "utenti_bulk_role", "admin_portale", {
            "target_user_ids": ids,
            "ruolo_id": ruolo_id,
            "ruolo": role_name,
            "count": len(ids),
        })
        messages.success(request, f"Ruolo aggiornato per {len(ids)} utenti.")
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento massivo: {exc}")

    return redirect("admin_portale:utenti_list")


@legacy_admin_required
@csrf_protect
@require_POST
def utenti_bulk_action(request):
    ids_from_checkboxes = [_helpers._int_or_none(v) for v in request.POST.getlist("user_ids")]
    ids = [v for v in ids_from_checkboxes if v is not None]
    mode = (request.POST.get("bulk_mode") or "").strip().lower()
    if not ids:
        messages.warning(request, "Nessun utente selezionato.")
        return redirect("admin_portale:utenti_list")

    try:
        with transaction.atomic():
            if mode == "activate":
                updated_users = list(UtenteLegacy.objects.filter(id__in=ids))
                UtenteLegacy.objects.filter(id__in=ids).update(attivo=True)
                for utente in updated_users:
                    utente.attivo = True
                    _sync_legacy_user_to_anagrafica(utente, force_active=True)
                _sync_django_active_from_legacy(ids, True)
                _helpers._audit_safe(request, "utenti_bulk_activate", "admin_portale", {"target_user_ids": ids, "count": len(ids)})
                messages.success(request, f"Attivati {len(ids)} utenti.")
            elif mode == "deactivate":
                updated_users = list(UtenteLegacy.objects.filter(id__in=ids))
                UtenteLegacy.objects.filter(id__in=ids).update(attivo=False)
                for utente in updated_users:
                    utente.attivo = False
                    _sync_legacy_user_to_anagrafica(utente, force_active=False)
                _sync_django_active_from_legacy(ids, False)
                _helpers._audit_safe(request, "utenti_bulk_deactivate", "admin_portale", {"target_user_ids": ids, "count": len(ids)})
                messages.success(request, f"Disattivati {len(ids)} utenti.")
            elif mode == "force_pwd":
                UtenteLegacy.objects.filter(id__in=ids).update(deve_cambiare_password=True)
                _helpers._audit_safe(request, "utenti_bulk_force_pwd", "admin_portale", {"target_user_ids": ids, "count": len(ids)})
                messages.success(request, f"Forzato cambio password per {len(ids)} utenti.")
            elif mode == "delete":
                current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
                current_id = int(current_legacy_user.id) if current_legacy_user else None
                safe_ids = [i for i in ids if i != current_id]
                skipped = len(ids) - len(safe_ids)
                deleted = 0
                errors = 0
                for uid in safe_ids:
                    try:
                        utente = UtenteLegacy.objects.filter(id=uid).first()
                        if utente:
                            _delete_legacy_user_with_dependencies(utente)
                            deleted += 1
                    except Exception:
                        _helpers.logger.exception("utenti_bulk_delete: errore uid=%s", uid)
                        errors += 1
                _helpers._audit_safe(request, "utenti_bulk_delete", "admin_portale", {
                    "target_user_ids": safe_ids,
                    "deleted": deleted,
                    "errors": errors,
                    "skipped_self": skipped,
                })
                parts = [f"Eliminati {deleted} utenti."]
                if skipped:
                    parts.append(f"{skipped} saltati (utente corrente).")
                if errors:
                    parts.append(f"{errors} errori durante l'eliminazione.")
                if errors:
                    messages.warning(request, " ".join(parts))
                else:
                    messages.success(request, " ".join(parts))
            else:
                messages.error(request, "Azione bulk non valida.")
    except DatabaseError as exc:
        messages.error(request, f"Errore azione bulk utenti: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore sincronizzazione massiva utenti/anagrafica: {exc}")

    return redirect("admin_portale:utenti_list")


@legacy_admin_required
@csrf_protect
@require_POST
def utente_force_change_password(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    try:
        utente.deve_cambiare_password = True
        utente.save(update_fields=["deve_cambiare_password"])
        messages.success(request, f"Forzato cambio password per utente #{utente.id}.")
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento utente: {exc}")
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)
    return redirect(next_url)


def _legacy_user_is_privileged(legacy_user: UtenteLegacy) -> bool:
    """Utente legacy amministratore o collegato a un account Django privilegiato."""
    try:
        from core.legacy_utils import is_legacy_admin

        if is_legacy_admin(legacy_user):
            return True
    except Exception:
        return True  # fail-closed
    profile = Profile.objects.select_related("user").filter(legacy_user_id=legacy_user.id).first()
    user = profile.user if profile else None
    return bool(user and (user.is_superuser or user.is_staff))


@legacy_admin_required
@csrf_protect
@require_POST
def utente_impersonate(request, user_id: int):
    target_user = get_object_or_404(UtenteLegacy, id=user_id)
    admin_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    next_url = _safe_redirect_url(request, (request.POST.get("next") or "").strip(), reverse("dashboard_home"))

    if getattr(request, "impersonation_active", False):
        messages.error(request, "Esci prima dall'impersonazione corrente.")
        return redirect(next_url)

    if not bool(target_user.attivo):
        messages.error(request, f"L'utente #{target_user.id} non e' attivo.")
        return redirect(next_url)

    if admin_user and int(target_user.id) == int(admin_user.id):
        messages.info(request, "Sei gia' autenticato come questo utente.")
        return redirect(next_url)

    # SEC (audit A1): solo un superuser puo' impersonare un amministratore.
    if not _helpers._acting_is_superuser(request) and _legacy_user_is_privileged(target_user):
        _helpers._audit_safe(request, "impersonation_denied", "admin_portale", {
            "target_legacy_user_id": int(target_user.id),
            "reason": "target_privileged",
        })
        messages.error(request, "Non puoi impersonare un amministratore.")
        return redirect(next_url)

    context = start_impersonation(request, target_user)
    if not context:
        messages.error(request, "Impossibile avviare l'impersonazione per questo utente.")
        return redirect(next_url)

    from core.security_notify import avviso_impersonazione_attivo, notify_security_event

    # Interruttore in «Gestione notifiche»: spento, resta solo l'audit.
    avviso_attivo = avviso_impersonazione_attivo()
    if avviso_attivo:
        notify_security_event(
            context["target_user"],
            "Accesso al tuo account da parte di un amministratore",
            "Un amministratore del portale ha appena iniziato a usare il tuo account in modalità "
            "impersonazione (assistenza o verifica dei permessi). L'operazione è registrata nel log di audit.",
        )
    log_action(
        request,
        "impersonation_start",
        "admin_portale",
        {
            "target_legacy_user_id": int(target_user.id),
            "target_display": (target_user.nome or target_user.email or "").strip(),
            "avviso_utente": avviso_attivo,
        },
    )
    from core.eventi_sicurezza import segnala

    segnala("impersonazione_avviata", utente=request.user, request=request,
            titolo=f"Impersonazione: {request.user.get_username()} come "
                   f"{(target_user.nome or target_user.email or '').strip()}",
            dettaglio={"target_legacy_user_id": int(target_user.id), "avviso_utente": avviso_attivo})
    messages.warning(
        request,
        f"Impersonazione attiva per {target_user.nome or target_user.email or f'utente #{target_user.id}'}.",
    )
    return redirect(next_url)


def _sync_django_active_from_legacy(legacy_ids, active: bool) -> int:
    """Allinea ``User.is_active`` agli utenti legacy (audit M4).

    I backend legacy/LDAP rifiutano in ``get_user`` un utente non attivo: così la
    disattivazione chiude subito anche le sessioni già aperte.
    """
    ids = [int(i) for i in legacy_ids]
    if not ids:
        return 0
    user_ids = list(Profile.objects.filter(legacy_user_id__in=ids).values_list("user_id", flat=True))
    if not user_ids:
        return 0
    return get_user_model().objects.filter(id__in=user_ids).exclude(is_active=active).update(is_active=active)


@legacy_admin_required
@csrf_protect
@require_POST
def utente_toggle_active(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    try:
        with transaction.atomic():
            utente.attivo = not bool(utente.attivo)
            utente.save(update_fields=["attivo"])
            _sync_legacy_user_to_anagrafica(utente, force_active=bool(utente.attivo))
            _sync_django_active_from_legacy([utente.id], bool(utente.attivo))
        _helpers._audit_safe(request, "utente_toggle_active", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "attivo": bool(utente.attivo),
        })
        messages.success(
            request,
            f"Utente #{utente.id} {'attivato' if utente.attivo else 'disattivato'}.",
        )
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento utente: {exc}")
    except Exception as exc:
        messages.error(request, f"Errore sincronizzazione utente/anagrafica: {exc}")
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)
    return redirect(next_url)


@legacy_admin_required
@csrf_protect
@require_POST
def utente_delete(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)

    if current_legacy_user and int(current_legacy_user.id) == int(utente.id):
        messages.error(request, "Non puoi eliminare l'utente con cui sei autenticato.")
        return redirect(next_url)

    user_label = (utente.nome or utente.email or f"Utente #{utente.id}").strip()

    try:
        cleanup = _delete_legacy_user_with_dependencies(utente)
        log_action(
            request,
            "utente_delete",
            "admin_portale",
            {
                "target_legacy_user_id": int(user_id),
                "target_display": user_label,
                "deleted_django_user_id": cleanup["django_user_id"] or None,
                "released_assets": cleanup["released_assets"],
                "anagrafica_unlinked": cleanup["anagrafica_unlinked"],
            },
        )
        messages.success(request, f"Utente #{user_id} eliminato definitivamente.")
    except Exception as exc:
        _helpers.logger.exception("utente_delete: errore eliminazione utente_id=%s", user_id)
        messages.error(request, f"Errore eliminazione utente: {exc}")

    return redirect(next_url)


@legacy_admin_required
@csrf_protect
@require_POST
def utente_quick_role(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    role_key = f"quick_ruolo_id_{user_id}"
    ruolo_id = _helpers._int_or_none(request.POST.get(role_key))
    ruolo_name = ""
    if ruolo_id:
        try:
            ruolo = Ruolo.objects.filter(id=ruolo_id).first()
            if ruolo:
                ruolo_name = (ruolo.nome or "").strip()
        except DatabaseError:
            ruolo_name = ""
    try:
        utente.ruolo_id = ruolo_id
        utente.ruolo = ruolo_name
        utente.save(update_fields=["ruolo_id", "ruolo"])
        _helpers._audit_safe(request, "utente_quick_role", "admin_portale", {
            "target_legacy_user_id": int(utente.id),
            "ruolo_id": ruolo_id,
            "ruolo": ruolo_name,
        })
        messages.success(request, f"Ruolo aggiornato per utente #{utente.id}.")
    except DatabaseError as exc:
        messages.error(request, f"Errore aggiornamento ruolo utente: {exc}")
    _fallback = reverse("admin_portale:utenti_list")
    next_url = _safe_redirect_url(request, request.POST.get("next") or request.META.get("HTTP_REFERER"), _fallback)
    return redirect(next_url)


@legacy_admin_required
@require_GET
def utente_permessi_effettivi(request, user_id: int):
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    rows: list[_helpers.PermRow] = []
    grouped_rows: list[tuple[str, list[_helpers.PermRow]]] = []
    if utente.ruolo_id:
        try:
            rows = _helpers._permission_rows_for_role(int(utente.ruolo_id))
            grouped_rows = _group_perm_rows_by_modulo(rows)
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura permessi effettivi: {exc}")
    return render(
        request,
        "admin_portale/pages/utente_permessi_effettivi.html",
        {
            "utente_obj": utente,
            "perm_rows": rows,
            "grouped_perm_rows": grouped_rows,
            "flag_names": _helpers._perm_flag_names(),
        },
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_user_perm_override(request, user_id: int):
    """Imposta/rimuove un override permesso per-utente.
    Payload: {modulo, azione, field, value}  (value: true/false/null)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    modulo = (payload.get("modulo") or "").strip()
    azione = (payload.get("azione") or "").strip()
    field = (payload.get("field") or "").strip()
    value = payload.get("value")  # true / false / null

    allowed_fields = {"can_view", "can_edit", "can_delete", "can_approve"}
    if not modulo or not azione or field not in allowed_fields:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    # value None = rimuovi override per quel campo
    bool_value = None if value is None else bool(value)

    try:
        ov, _ = UserPermissionOverride.objects.get_or_create(
            legacy_user_id=utente.id,
            modulo=modulo,
            azione=azione,
        )
        setattr(ov, field, bool_value)
        ov.save(update_fields=[field])

        # Se tutti i campi sono None â†’ elimina il record
        ov.refresh_from_db()
        if ov.all_null():
            ov.delete()

        try:
            from core.audit import log_action
            log_action(request, "override_permesso", "admin", {
                "target_user_id": utente.id,
                "modulo": modulo,
                "azione": azione,
                "field": field,
                "value": bool_value,
            })
        except Exception:
            pass

        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@legacy_admin_required
@require_POST
def api_user_dashboard_toggle(request, user_id: int):
    """Imposta visibilitÃ  pulsante dashboard per-utente.
    Payload: {pulsante_id, visible}  (visible: bool)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    pulsante_id = _helpers._int_or_none(payload.get("pulsante_id"))
    visible = payload.get("visible")

    if pulsante_id is None or visible is None:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    bool_visible = bool(visible)
    try:
        if bool_visible:
            # visible=True â†’ rimuovi il record (default Ã¨ visibile)
            UserDashboardConfig.objects.filter(
                legacy_user_id=utente.id, pulsante_id=pulsante_id
            ).delete()
        else:
            UserDashboardConfig.objects.update_or_create(
                legacy_user_id=utente.id,
                pulsante_id=pulsante_id,
                defaults={"visible": False},
            )
        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@legacy_admin_required
@require_POST
def api_user_module_toggle(request, user_id: int):
    """Imposta visibilitÃ  di un intero modulo dashboard per-utente.
    Payload: {modulo, visible}  (visible: bool)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    modulo = (payload.get("modulo") or "").strip()
    visible = payload.get("visible")

    if not modulo or visible is None:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    bool_visible = bool(visible)
    try:
        if bool_visible:
            # visible=True â†’ rimuovi il record (default Ã¨ visibile)
            UserModuleVisibility.objects.filter(
                legacy_user_id=utente.id, modulo=modulo
            ).delete()
        else:
            UserModuleVisibility.objects.update_or_create(
                legacy_user_id=utente.id,
                modulo=modulo,
                defaults={"visible": False},
            )
        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@legacy_admin_required
@require_POST
def api_user_extra_info(request, user_id: int):
    """Salva le informazioni anagrafiche extra per un utente.
    Payload: { caporeparto, macchina, telefono, cellulare, note }
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)

    before_obj = UserExtraInfo.objects.filter(legacy_user_id=utente.id).first()
    before = {
        "reparto": (before_obj.reparto if before_obj else ""),
        "caporeparto": (before_obj.caporeparto if before_obj else ""),
        "macchina": (before_obj.macchina if before_obj else ""),
        "telefono": (before_obj.telefono if before_obj else ""),
        "cellulare": (before_obj.cellulare if before_obj else ""),
        "note": (before_obj.note if before_obj else ""),
    }

    new_reparto    = (payload.get("reparto") or "").strip()[:200]
    new_caporeparto = (payload.get("caporeparto") or "").strip()[:200]

    # Auto-assegna caporeparto da mapping se il reparto cambia e il caporeparto
    # non Ã¨ stato impostato esplicitamente nel payload.
    if new_reparto and not new_caporeparto:
        from core.models import RepartoCapoMapping
        mapping = RepartoCapoMapping.objects.filter(
            reparto__iexact=new_reparto, is_active=True
        ).first()
        if mapping:
            new_caporeparto = mapping.caporeparto

    if new_caporeparto:
        normalized = normalize_caporeparto_option(new_caporeparto, promote_role=True)
        if not normalized.get("ok"):
            return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
        new_caporeparto = str(normalized["value"] or "").strip()[:200]

    defaults = {
        "reparto":     new_reparto,
        "caporeparto": new_caporeparto,
        "macchina":    (payload.get("macchina") or "").strip()[:200],
        "telefono":    (payload.get("telefono") or "").strip()[:50],
        "cellulare":   (payload.get("cellulare") or "").strip()[:50],
        "note":        (payload.get("note") or "").strip(),
    }
    try:
        UserExtraInfo.objects.update_or_create(
            legacy_user_id=utente.id,
            defaults=defaults,
        )
        _helpers._audit_safe(
            request,
            "utente_extra_info_update",
            "admin_anagrafica",
            {
                "target_user_id": utente.id,
                "before": before,
                "after": defaults,
            },
        )
        return JsonResponse({"ok": True})
    except Exception:
        _helpers.logger.exception("api_user_extra_info: errore salvataggio info extra")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


# â”€â”€ Anagrafica config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@legacy_admin_required
@require_POST
def api_user_asset_assignments(request, user_id: int):
    """Assegna uno o piu asset a un dipendente (replace completo delle assegnazioni utente)."""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    raw_ids = payload.get("asset_ids")
    if raw_ids is None:
        raw_ids = []
    if not isinstance(raw_ids, list):
        return JsonResponse({"ok": False, "error": "asset_ids deve essere una lista."}, status=400)

    requested_ids: list[int] = []
    for value in raw_ids:
        iv = _helpers._int_or_none(value)
        if iv and iv > 0:
            requested_ids.append(int(iv))
    requested_ids = sorted(set(requested_ids))

    asset_model = _asset_model()
    if asset_model is None:
        return JsonResponse({"ok": False, "error": "Modulo asset non disponibile."}, status=503)

    try:
        valid_ids = set(asset_model.objects.filter(id__in=requested_ids).values_list("id", flat=True))
        display_name = (utente.nome or utente.email or f"Utente #{utente.id}").strip()[:200]

        reparto = ""
        extra = UserExtraInfo.objects.filter(legacy_user_id=utente.id).first()
        if extra:
            reparto = (extra.reparto or "").strip()[:120]
        if not reparto:
            ana = AnagraficaDipendente.objects.filter(utente_id=utente.id).first()
            if ana:
                reparto = (ana.reparto or "").strip()[:120]

        touched_ids = set(valid_ids) | set(
            asset_model.objects.filter(assigned_legacy_user_id=utente.id).values_list("id", flat=True)
        )
        with _storico_asset(touched_ids, fonte="api", utente=request.user,
                            dettaglio=f"Assegnazioni da anagrafica utente #{utente.id}"):
            released = asset_model.objects.filter(assigned_legacy_user_id=utente.id).exclude(id__in=valid_ids).update(
                assigned_legacy_user_id=None,
                assignment_to="",
                assignment_reparto="",
            )
            assign_defaults = {
                "assigned_legacy_user_id": int(utente.id),
                "assignment_to": display_name,
            }
            if reparto:
                assign_defaults["assignment_reparto"] = reparto
            assigned = asset_model.objects.filter(id__in=valid_ids).update(**assign_defaults)

        _helpers._audit_safe(
            request,
            "utente_asset_assignments_update",
            "admin_anagrafica",
            {
                "target_user_id": int(utente.id),
                "target_user_nome": display_name,
                "assigned_count": int(assigned),
                "released_count": int(released),
                "asset_ids": sorted(int(v) for v in valid_ids),
            },
        )
        return JsonResponse(
            {
                "ok": True,
                "assigned_count": int(assigned),
                "released_count": int(released),
                "asset_ids": sorted(int(v) for v in valid_ids),
            }
        )
    except Exception:
        _helpers.logger.exception("api_user_asset_assignments: errore salvataggio assegnazioni")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_reparto_capo_set(request):
    """Upsert mapping reparto â†’ caporeparto.

    Payload JSON: { reparto: str, caporeparto: str }
    Se caporeparto Ã¨ vuoto, elimina il mapping esistente per quel reparto.
    """
    from core.models import RepartoCapoMapping
    payload = _helpers._json_payload(request)
    reparto     = (payload.get("reparto") or "").strip()[:200]
    caporeparto = (payload.get("caporeparto") or "").strip()[:200]
    if not reparto:
        return JsonResponse({"ok": False, "error": "reparto obbligatorio."}, status=400)
    if not caporeparto:
        # Rimuovi eventuale mapping
        deleted, _ = RepartoCapoMapping.objects.filter(reparto__iexact=reparto).delete()
        return JsonResponse({"ok": True, "action": "deleted", "deleted": deleted})
    normalized = normalize_caporeparto_option(caporeparto, promote_role=True)
    if not normalized.get("ok"):
        return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
    caporeparto = str(normalized["value"] or "").strip()[:200]
    obj, created = RepartoCapoMapping.objects.update_or_create(
        reparto=reparto,
        defaults={"caporeparto": caporeparto, "is_active": True},
    )
    _helpers._audit_safe(request, "reparto_capo_mapping_set", "admin_anagrafica",
                {"reparto": reparto, "caporeparto": caporeparto, "created": created})
    return JsonResponse({"ok": True, "id": obj.id, "action": "created" if created else "updated"})


@legacy_admin_required
@require_POST
def api_reparto_capo_delete(request):
    """Elimina un mapping reparto â†’ caporeparto per ID."""
    from core.models import RepartoCapoMapping
    payload = _helpers._json_payload(request)
    pk = _helpers._int_or_none(payload.get("id"))
    if not pk:
        return JsonResponse({"ok": False, "error": "id obbligatorio."}, status=400)
    obj = get_object_or_404(RepartoCapoMapping, id=pk)
    obj.delete()
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_reparto_capo_sync(request):
    """Propaga il mapping reparto â†’ caporeparto a tutti gli utenti di quel reparto.

    Payload JSON: { reparto: str }
    Aggiorna UserExtraInfo.caporeparto per tutti gli utenti con quel reparto,
    solo se il mapping esiste e is_active=True.
    """
    from core.models import RepartoCapoMapping, UserExtraInfo
    payload = _helpers._json_payload(request)
    reparto = (payload.get("reparto") or "").strip()
    if not reparto:
        return JsonResponse({"ok": False, "error": "reparto obbligatorio."}, status=400)
    mapping = RepartoCapoMapping.objects.filter(reparto__iexact=reparto, is_active=True).first()
    if not mapping:
        return JsonResponse({"ok": False, "error": "Nessun mapping attivo per questo reparto."}, status=404)
    updated = UserExtraInfo.objects.filter(reparto__iexact=reparto).update(caporeparto=mapping.caporeparto)
    _helpers._audit_safe(request, "reparto_capo_sync", "admin_anagrafica",
                {"reparto": reparto, "caporeparto": mapping.caporeparto, "users_updated": updated})
    return JsonResponse({"ok": True, "reparto": reparto, "caporeparto": mapping.caporeparto, "users_updated": updated})


@legacy_admin_required
@require_POST
def api_anagrafica_risposte_save(request, user_id: int):
    """Salva le risposte ai campi extra anagrafica per un utente.
    Payload: { "risposte": [{"voce_id": int, "valore": str}, ...] }
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    risposte = payload.get("risposte") or []
    try:
        voce_ids = [_helpers._int_or_none(item.get("voce_id")) for item in risposte]
        voce_ids = [vid for vid in voce_ids if vid is not None]
        before_map = {
            r.voce_id: (r.valore or "")
            for r in AnagraficaRisposta.objects.filter(legacy_user_id=utente.id, voce_id__in=voce_ids)
        }
        changes: list[dict] = []
        for item in risposte:
            voce_id = _helpers._int_or_none(item.get("voce_id"))
            valore = (item.get("valore") or "").strip()
            if voce_id is None:
                continue
            old_value = before_map.get(voce_id, "")
            AnagraficaRisposta.objects.update_or_create(
                legacy_user_id=utente.id,
                voce_id=voce_id,
                defaults={"valore": valore},
            )
            if old_value != valore:
                changes.append({"voce_id": voce_id, "before": old_value, "after": valore})
        if changes:
            _helpers._audit_safe(
                request,
                "anagrafica_risposte_save",
                "admin_anagrafica",
                {
                    "target_user_id": utente.id,
                    "changes": changes,
                    "changed_count": len(changes),
                },
            )
        return JsonResponse({"ok": True})
    except Exception:
        _helpers.logger.exception("api_anagrafica_risposte_save: errore")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@csrf_protect
@require_POST
def api_user_modulo_perm_set(request, user_id: int):
    """Imposta can_view override per TUTTI i pulsanti di un modulo per un utente.
    Payload: {modulo, can_view}  (can_view null = rimuovi override, torna al ruolo)
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    modulo = str(payload.get("modulo") or "").strip()
    can_view_raw = payload.get("can_view")  # true / false / null
    if not modulo:
        return _helpers._json_error("Parametri non validi.")
    blocked = _helpers._canonical_module_write_block(modulo)
    if blocked is not None:
        return blocked
    can_view = None if can_view_raw is None else _helpers._bool_from_any(can_view_raw)
    acl_keys = [(m, a) for m, a in _helpers._pulsanti_acl_keys() if m.lower() == modulo.lower()]
    try:
        with transaction.atomic():
            affected = 0
            for mod, azione in acl_keys:
                if can_view is None:
                    UserPermissionOverride.objects.filter(
                        legacy_user_id=utente.id, modulo=mod, azione=azione
                    ).delete()
                else:
                    ov, _ = UserPermissionOverride.objects.get_or_create(
                        legacy_user_id=utente.id, modulo=mod, azione=azione,
                    )
                    ov.can_view = can_view
                    ov.save(update_fields=["can_view"])
                affected += 1
            _helpers._schedule_legacy_acl_cache_invalidation()
    except Exception as exc:
        return _helpers._json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "affected": affected})


@legacy_admin_required
def user_activity_view(request):
    from datetime import timedelta
    from core.models import AuditLog
    from django.core.paginator import Paginator

    days_raw = (request.GET.get("days") or "30").strip()
    try:
        days = max(1, min(365, int(days_raw)))
    except ValueError:
        days = 30
    since = timezone.now() - timedelta(days=days)
    legacy_user_id = (request.GET.get("legacy_user_id") or "").strip()
    modulo = (request.GET.get("modulo") or "").strip()
    q = (request.GET.get("q") or "").strip()

    qs = AuditLog.objects.filter(created_at__gte=since)
    if legacy_user_id:
        qs = qs.filter(legacy_user_id=legacy_user_id)
    if modulo:
        qs = qs.filter(modulo=modulo)
    if q:
        qs = qs.filter(
            Q(utente_display__icontains=q)
            | Q(azione__icontains=q)
            | Q(modulo__icontains=q)
            | Q(ip_address__icontains=q)
        )

    export_format = (request.GET.get("export") or "").strip().lower()
    if export_format in {"csv", "xlsx"}:
        return export_rows_response(
            rows=qs.order_by("-created_at"),
            columns=[
                ("Data/Ora", "created_at"),
                ("Utente", lambda e: (e.utente_display or "").upper()),
                ("Legacy user ID", "legacy_user_id"),
                ("Modulo", "modulo"),
                ("Azione", "azione"),
                ("IP", "ip_address"),
                ("Dettaglio", "dettaglio"),
            ],
            filename="attivita_utente",
            fmt=export_format,
        )

    by_module = list(qs.values("modulo").annotate(total=Count("id")).order_by("-total", "modulo")[:12])
    by_action = list(qs.values("azione").annotate(total=Count("id")).order_by("-total", "azione")[:12])
    users = list(
        AuditLog.objects.filter(created_at__gte=since)
        .exclude(legacy_user_id__isnull=True)
        .values("legacy_user_id", "utente_display")
        .annotate(total=Count("id"))
        .order_by("utente_display", "legacy_user_id")[:200]
    )
    moduli_disponibili = AuditLog.objects.values_list("modulo", flat=True).distinct().order_by("modulo")
    paginator = Paginator(qs.order_by("-created_at"), 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "admin_portale/pages/user_activity.html", {
        "page_title": "Attivita utenti",
        "page_obj": page_obj,
        "days": days,
        "legacy_user_id": legacy_user_id,
        "modulo": modulo,
        "q": q,
        "users": users,
        "moduli_disponibili": moduli_disponibili,
        "by_module": by_module,
        "by_action": by_action,
        "total_events": qs.count(),
    })
