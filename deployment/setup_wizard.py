"""
Portale Novicrom — Setup Wizard
Eseguire come Amministratore: python setup_wizard.py [--env dev|test|prod]
Requisiti: Python 3.11+ (tkinter incluso).
"""

import ctypes, json, os, re, shlex, shutil, socket, subprocess, sys, threading
import traceback, zipfile
from datetime import datetime
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None   # non-Windows: discovery Registry disabilitata

try:
    import pyodbc as _pyodbc_module
except ImportError:
    _pyodbc_module = None   # sarà disponibile nell'exe (hidden import)

# ─────────────────────────────────────────────────────────────
# PALETTE & COSTANTI
# ─────────────────────────────────────────────────────────────
def _bootstrap_tcl_tk_env() -> None:
    """Imposta i path Tcl/Tk in modo deterministico per exe frozen e runtime locali."""
    candidates: list[tuple[str, Path]] = []

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        candidates.extend(
            [
                ("TCL_LIBRARY", meipass / "_tcl_data"),
                ("TK_LIBRARY", meipass / "_tk_data"),
            ]
        )

    try:
        import _tkinter as _bootstrap_tk
    except ImportError:
        _bootstrap_tk = None

    if _bootstrap_tk is not None and getattr(_bootstrap_tk, "__file__", None):
        python_root = Path(_bootstrap_tk.__file__).resolve().parents[1]
        candidates.extend(
            [
                ("TCL_LIBRARY", python_root / "tcl" / f"tcl{_bootstrap_tk.TCL_VERSION}"),
                ("TK_LIBRARY", python_root / "tcl" / f"tk{_bootstrap_tk.TK_VERSION}"),
            ]
        )

    for env_key, path in candidates:
        if path.is_dir():
            os.environ.setdefault(env_key, path.as_posix())


_bootstrap_tcl_tk_env()

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Palette allineata al design system NOVICROM HUB (navy/cyan/arancio/verde).
BRAND        = "#1f87cd"   # cyan HUB (azione primaria)
BRAND_DARK   = "#0c2545"   # navy HUB (header)
BRAND_HOVER  = "#1769a8"   # cyan scuro (hover pulsanti)
SIDEBAR_BG   = "#0c2545"   # navy HUB
ORANGE       = "#ff6b00"   # accento HUB
SIDEBAR_W    = 210
WIN_W, WIN_H = 900, 620

GRAY50   = "#f9fafb"; GRAY100 = "#f3f4f6"; GRAY200 = "#e5e7eb"
GRAY400  = "#9ca3af"; GRAY500 = "#6b7280"; GRAY600 = "#4b5563"
GRAY700  = "#374151"; GRAY800 = "#1f2937"; GRAY900 = "#111827"

GREEN    = "#2f9e6f"; GREEN_BG  = "#f0fdf4"; GREEN_BD  = "#86efac"
YELLOW_BG= "#fffbeb"; YELLOW_BD = "#fcd34d"; YELLOW_TX = "#92400e"
RED      = "#dc2626"; RED_BG    = "#fef2f2"
BLUE_BG  = "#eff6ff"; BLUE_BD   = "#93c5fd"
CODE_BG  = "#0d1117"; CODE_FG   = "#c9d1d9"

SF  = "Segoe UI"
FN  = (SF, 10)
FNB = (SF, 10, "bold")
FSM = (SF, 9)
FMD = (SF, 12, "bold")
FLG = (SF, 18, "bold")
FMO = ("Consolas", 9)

PYTHON_MIN_VERSION = (3, 11)

STEPS = ["Benvenuto","Pacchetto","Ambiente","Python",
         "Database","Active Directory","Email","IIS / Web",
         "Prerequisiti IIS","Utente Admin","Moduli","Assistente AI","Riepilogo","Installazione","Completato"]

STEPS_RELEASE   = ["Modalità", "Configurazione", "Esecuzione", "Completato"]
STEPS_UNINSTALL = ["Configurazione", "Conferma", "Disinstallazione", "Completato"]

# Mappa ambiente → settings module Django.
# Solo dev.py e prod.py esistono; test usa prod (stesse impostazioni SQL Server).
_SETTINGS_MAP = {"dev": "dev", "test": "prod", "prod": "prod"}

_DEFAULT_APP_VERSION = "1.4.0"
_VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
_MODULE_VERSION_ENV_KEYS = (
    "APP_VERSION_CORE",
    "APP_VERSION_DASHBOARD",
    "APP_VERSION_ASSENZE",
    "APP_VERSION_ANOMALIE",
    "APP_VERSION_ASSETS",
    "APP_VERSION_TASKS",
    "APP_VERSION_ADMIN_PORTALE",
    "APP_VERSION_NOTIZIE",
    "APP_VERSION_ANAGRAFICA",
    "APP_VERSION_TICKETS",
    "APP_VERSION_DPI",
    "APP_VERSION_PROCEDURE_REFRESH",
)

# Registro centralizzato dei moduli installabili.
# Usato da ModulesPage (selezione wizard) e dal migrate selettivo in InstallPage /
# ReleaseRunPage.  Ogni voce descrive un'app Django opzionale o richiesta.
#
# Campi:
#   key          – identificatore univoco (coincide con app_label Django)
#   label        – nome visualizzato nel wizard
#   description  – descrizione breve
#   app_label    – app_label Django (per manage.py migrate <app_label>)
#   required     – True = sempre installato, checkbox disabilitato
#   default      – True = pre-selezionato nelle nuove installazioni
#   depends_on   – lista di key che devono essere selezionati insieme
#   has_migrations – True = ha migration Django da eseguire
#   tier         – "system" | "standard" | "optional"  (per UI e futuro licensing)
MODULE_REGISTRY: list[dict] = [
    # ── SISTEMA ─────────────────────────────────────────────────────────────
    {"key": "core",        "label": "Core",
     "description": "ACL, autenticazione, navigazione, audit log — base obbligatoria",
     "app_label": "core",  "required": True,  "default": True,  "depends_on": [],
     "has_migrations": True,  "tier": "system"},
    {"key": "anagrafica",  "label": "Anagrafica dipendenti",
     "description": "Anagrafica dipendenti, ruoli operativi, fornitori — richiesta da asset e ticket",
     "app_label": "anagrafica", "required": True, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "system"},
    {"key": "dashboard",   "label": "Dashboard",
     "description": "Home page personalizzabile con widget KPI multi-modulo",
     "app_label": "dashboard",  "required": True, "default": True, "depends_on": [],
     "has_migrations": False, "tier": "system"},
    {"key": "hub_tools",   "label": "Hub Strumenti Admin",
     "description": "Module Manager, DB Manager, guide e documentazione interna",
     "app_label": "hub_tools",  "required": True, "default": True, "depends_on": [],
     "has_migrations": False, "tier": "system"},
    {"key": "monitoring",  "label": "Monitoring",
     "description": "Issue tracking interno e osservabilita del portale",
     "app_label": "monitoring", "required": True, "default": True, "depends_on": [],
     "has_migrations": True, "tier": "system"},
    # ── STANDARD ────────────────────────────────────────────────────────────
    {"key": "notizie",     "label": "Notizie",
     "description": "Bacheca notizie e comunicazioni aziendali",
     "app_label": "notizie",    "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "standard"},
    {"key": "assenze",     "label": "Gestione Assenze",
     "description": "Richieste assenze, calendario, certificazioni presenza, sync SharePoint",
     "app_label": "assenze",    "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "standard"},
    {"key": "anomalie",    "label": "Anomalie Produzione",
     "description": "Segnalazione e gestione anomalie produzione",
     "app_label": "anomalie",   "required": False, "default": True, "depends_on": [],
     "has_migrations": True, "tier": "standard"},
    {"key": "assets",      "label": "Gestione Asset",
     "description": "Inventario asset, manutenzioni, ordini di lavoro, scadenzari, licenze",
     "app_label": "assets",     "required": False, "default": True,
     "depends_on": ["anagrafica"], "has_migrations": True, "tier": "standard"},
    {"key": "tickets",     "label": "Ticket Interni",
     "description": "Sistema ticket interni, categorie, stati, interventi tecnici",
     "app_label": "tickets",    "required": False, "default": True,
     "depends_on": ["assets", "anagrafica"], "has_migrations": True, "tier": "standard"},
    {"key": "automazioni", "label": "Automazioni",
     "description": "Designer visuale automazioni, trigger SQL, approvazioni, polling mail",
     "app_label": "automazioni", "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "standard"},
    {"key": "tasks",       "label": "KICK-OFF / Tasks",
     "description": "Portfolio kickoff, attività, subtask, allegati, VRF MOD.073",
     "app_label": "tasks",      "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "standard"},
    {"key": "timbri",      "label": "Timbrature",
     "description": "Report timbrature da DB legacy con importazione e storico",
     "app_label": "timbri",     "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "standard"},
    {"key": "planimetria", "label": "Planimetria",
     "description": "Wrapper planimetria e compatibilita percorsi asset",
     "app_label": "planimetria", "required": False, "default": True,
     "depends_on": ["assets"], "has_migrations": True, "tier": "standard"},
    # ── OPZIONALI ───────────────────────────────────────────────────────────
    {"key": "dpi",                    "label": "Gestione DPI",
     "description": "Dispositivi Protezione Individuale: richieste, approvazione, consegna, storico",
     "app_label": "dpi",             "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "optional"},
    {"key": "rentri",                 "label": "RENTRI",
     "description": "Tracciabilità rifiuti — normativa RENTRI",
     "app_label": "rentri",          "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "optional"},
    {"key": "diario_preposto",        "label": "Diario Preposto",
     "description": "Diario del preposto sicurezza con segnalazioni e allegati",
     "app_label": "diario_preposto", "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "optional"},
    {"key": "rilevazione_incidenti",  "label": "Rilevazione Incidenti",
     "description": "Incidenti / unsafe condition con sorgente SharePoint via Graph API",
     "app_label": "rilevazione_incidenti", "required": False, "default": True,
     "depends_on": [], "has_migrations": True, "tier": "optional"},
    {"key": "procedure_refresh",      "label": "Procedure Refresh",
     "description": "Presa visione procedure MT/MTSI: campagne, assegnazioni, tracking aperture",
     "app_label": "procedure_refresh", "required": False, "default": True, "depends_on": [],
     "has_migrations": True,  "tier": "optional"},
    {"key": "gestione_carichi_macchina", "label": "Gestione Carichi Macchina",
     "description": "Pianificazione carichi macchina (Excel/Gantt), saturazione, suggeritore",
     "app_label": "gestione_carichi_macchina", "required": False, "default": True,
     "depends_on": ["assets"], "has_migrations": True, "tier": "standard"},
    {"key": "gestione_specifiche", "label": "Gestione Specifiche",
     "description": "Flusso specifiche tecniche + MOD.133, OFI/MOD.174, distribuzione, verifica periodica",
     "app_label": "gestione_specifiche", "required": False, "default": True,
     "depends_on": ["anagrafica"], "has_migrations": True, "tier": "optional"},
    {"key": "ai_assistant", "label": "Assistente AI",
     "description": "Copilot on-premise (Ollama): chat, RAG knowledge base, suggerimenti",
     "app_label": "ai_assistant", "required": False, "default": True,
     "depends_on": [], "has_migrations": True, "tier": "optional"},
]

# Mappa key → entry per lookup O(1)
_MODULE_BY_KEY: dict[str, dict] = {m["key"]: m for m in MODULE_REGISTRY}

# App Django di sistema (non custom) che devono sempre essere migrate
# prima dei moduli custom. Django le risolve tramite le dependency declarations
# nelle migration, ma le elenchiamo esplicitamente per chiarezza e robustezza.
_DJANGO_BUILTIN_MIGRATE_LABELS: tuple[str, ...] = (
    "contenttypes", "auth", "sessions", "admin", "axes",
)


def _load_app_version(default: str = _DEFAULT_APP_VERSION) -> str:
    try:
        first_line = _VERSION_FILE.read_text(encoding="utf-8").splitlines()[0]
    except Exception:
        return default
    parsed = str(first_line or "").strip()
    return parsed or default


APP_VERSION = _load_app_version()


def _module_version_lines(version: str) -> list[str]:
    resolved = str(version or APP_VERSION).strip() or APP_VERSION
    return [f"{env_key}={resolved}" for env_key in _MODULE_VERSION_ENV_KEYS]


def _read_release_version(source_root: Path, default: str = APP_VERSION) -> str:
    """
    Resolve release version for packaging.

    Order:
    1) VERSION file in source root (single source of truth)
    2) django_app/config/app_version.py -> DEFAULT_APP_VERSION
    3) legacy fallback: parse APP_VERSION default from settings/base.py
    """
    version_file = source_root / "VERSION"
    try:
        if version_file.exists():
            value = version_file.read_text(encoding="utf-8").splitlines()[0].strip()
            if value:
                return value
    except Exception:
        pass

    app_version_py = source_root / "django_app" / "config" / "app_version.py"
    try:
        if app_version_py.exists():
            content = app_version_py.read_text(encoding="utf-8")
            match = re.search(r'DEFAULT_APP_VERSION\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
    except Exception:
        pass

    settings_base = source_root / "django_app" / "config" / "settings" / "base.py"
    try:
        if settings_base.exists():
            content = settings_base.read_text(encoding="utf-8")
            match = re.search(r'APP_VERSION\s*=\s*env\([^,]+,\s*["\']([^"\']+)["\']', content)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
    except Exception:
        pass

    return default


def _django_settings(environment: str) -> str:
    return f"config.settings.{_SETTINGS_MAP.get(environment, 'prod')}"


_SQL_SERVER_DRIVER_PREFERENCE = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "ODBC Driver 11 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)

_STATIC_ASSET_SENTINELS = (
    ("core theme", Path("core") / "css" / "theme.css"),
    ("monitoring css", Path("monitoring") / "css" / "monitoring.css"),
)


def _installed_sql_server_odbc_drivers() -> list[str]:
    if _pyodbc_module is None:
        return []
    try:
        return [driver for driver in _pyodbc_module.drivers() if "SQL Server" in driver]
    except Exception:
        return []


def _is_ssl_cert_error(err_str: str) -> bool:
    """Ritorna True se l'errore pyodbc è dovuto a un certificato SSL non verificabile."""
    low = err_str.lower()
    keywords = ("ssl", "certificate", "certificat", "catena", "-2146893019",
                "08001", "encryption", "trust", "handshake")
    return any(k in low for k in keywords)


def _try_db_connection(
    drv: str,
    host: str,
    user: str,
    pwd: str,
    trusted: bool,
    trust_cert: bool,
    database: str = "",
) -> tuple[bool, str]:
    """Tenta una connessione pyodbc e ritorna (ok, messaggio_errore)."""
    if _pyodbc_module is None:
        return False, "pyodbc non disponibile"
    tc = "yes" if trust_cert else "no"
    db_part = f"DATABASE={database};" if database else ""
    try:
        if trusted:
            cs = (f"DRIVER={{{drv}}};SERVER={host};"
                  f"{db_part}"
                  f"Trusted_Connection=yes;Connection Timeout=5;"
                  f"TrustServerCertificate={tc}")
        else:
            cs = (f"DRIVER={{{drv}}};SERVER={host};"
                  f"{db_part}"
                  f"UID={user};PWD={pwd};Connection Timeout=5;"
                  f"TrustServerCertificate={tc}")
        conn = _pyodbc_module.connect(cs, autocommit=True, timeout=5)
        conn.close()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _sql_server_driver_sort_key(driver_name: str) -> tuple[int, str]:
    normalized = str(driver_name or "").strip().lower()
    try:
        return (_SQL_SERVER_DRIVER_PREFERENCE.index(driver_name), normalized)
    except ValueError:
        return (len(_SQL_SERVER_DRIVER_PREFERENCE), normalized)


def _preferred_sql_server_odbc_driver(drivers: list[str] | None = None) -> str:
    available = list(dict.fromkeys(drivers or _installed_sql_server_odbc_drivers()))
    if not available:
        return ""
    return sorted(available, key=_sql_server_driver_sort_key)[0]


def _realign_db_driver_in_env(env_content: str) -> tuple[str, str]:
    """Controlla che DB_DRIVER nel .env sia un driver ODBC SQL Server installato.
    Se manca, è vuoto o non corrisponde a un driver installato, lo aggiunge/sostituisce
    con il miglior driver disponibile.
    Restituisce (env_content_aggiornato, nota_log).  nota_log è vuota se nessun cambio."""
    import re
    drivers = _installed_sql_server_odbc_drivers()
    if not drivers:
        return env_content, ""
    best = _preferred_sql_server_odbc_driver(drivers)
    if not best:
        return env_content, ""
    m = re.search(r"^DB_DRIVER=(.*)$", env_content, re.MULTILINE)
    if not m:
        # DB_DRIVER assente: aggiunge la riga alla fine
        updated = env_content.rstrip("\n") + f"\nDB_DRIVER={best}\n"
        return updated, f"  ✓ DB_DRIVER aggiunto: '{best}' (riga mancante nel .env)"
    current = m.group(1).strip()
    if current in drivers:
        return env_content, ""
    updated = re.sub(r"^DB_DRIVER=.*$", f"DB_DRIVER={best}", env_content, flags=re.MULTILINE)
    label = "vuoto" if not current else f"'{current}' non installato"
    return updated, f"  ✓ DB_DRIVER riallineato: {label} → '{best}'"


def _env_key_values(env_content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_content.splitlines():
        match = re.match(r"^\s*([^#=]+)=(.*)$", line)
        if not match:
            continue
        key = match.group(1).strip()
        if key:
            values[key] = match.group(2).strip()
    return values


def _apply_env_updates(text: str, updates: dict, remove=()) -> str:
    """Aggiorna le chiavi `updates` nel testo .env, elimina quelle in `remove`
    (se non anche in updates) e RIMUOVE i duplicati (tiene la prima occorrenza).
    Le chiavi assenti vengono accodate in un blocco dedicato. Commenti e righe
    non KEY=VALUE sono preservati. Usato dal Server Dashboard per editare la
    config AI senza riscrivere a mano il .env (e ripulendo eventuali duplicati)."""
    remove_set = set(remove) - set(updates)
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^\s*([^#=]+)=", line)
        if not m:
            out.append(line)
            continue
        key = m.group(1).strip()
        if key in remove_set:
            continue
        if key in updates:
            if key in seen:
                continue  # duplicato -> scartato
            out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
        out.append(line)
    missing = [k for k in updates if k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# --- Assistente AI (Server Dashboard) ---")
        out.extend(f"{k}={updates[k]}" for k in missing)
    result = "\n".join(out)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


def _ai_build_env_updates(backend, base_url, chat_model, embed_model,
                          tei_base, tei_model):
    """Costruisce (updates, remove) per la config AI in base al backend scelto
    (off | ollama | tei). Logica pura (testabile): le chiavi rispecchiano quelle
    lette da ai_assistant/services.py."""
    updates = {
        "OLLAMA_API_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": base_url,
        "OLLAMA_CHAT_MODEL": chat_model,
        "OLLAMA_CHAT_ENABLED": "True",
    }
    remove = set()
    if backend == "off":
        updates["OLLAMA_EMBED_ENABLED"] = "False"
        remove |= {"RAG_EMBED_BACKEND", "OLLAMA_EMBED_MODEL",
                   "RAG_EMBED_OPENAI_BASE_URL", "RAG_EMBED_OPENAI_MODEL"}
    elif backend == "ollama":
        updates["OLLAMA_EMBED_ENABLED"] = "True"
        updates["RAG_EMBED_BACKEND"] = "ollama"
        updates["OLLAMA_EMBED_MODEL"] = embed_model
        remove |= {"RAG_EMBED_OPENAI_BASE_URL", "RAG_EMBED_OPENAI_MODEL"}
    else:  # tei
        updates["OLLAMA_EMBED_ENABLED"] = "True"
        updates["RAG_EMBED_BACKEND"] = "openai"
        updates["RAG_EMBED_OPENAI_BASE_URL"] = tei_base
        updates["RAG_EMBED_OPENAI_MODEL"] = tei_model
        remove |= {"OLLAMA_EMBED_MODEL"}
    return updates, remove


def _env_drift_keys(config_content: str, current_content: str) -> list[str]:
    config_values = _env_key_values(config_content)
    current_values = _env_key_values(current_content)
    keys = sorted(set(config_values) | set(current_values))
    return [
        key
        for key in keys
        if config_values.get(key) != current_values.get(key)
    ]


def _missing_static_assets(static_root: Path) -> list[tuple[str, Path]]:
    root = Path(static_root)
    return [
        (label, root / relative_path)
        for label, relative_path in _STATIC_ASSET_SENTINELS
        if not (root / relative_path).exists()
    ]


def _ps_escape(value: str) -> str:
    """Escapa un valore per l'interpolazione in una stringa PowerShell double-quoted.
    Gestisce: apici doppi, backtick, dollaro."""
    return str(value).replace('`', '``').replace('"', '`"').replace('$', '`$')


def _sql_bracket_escape(name: str) -> str:
    """Escapa un nome SQL Server per la notazione bracket: ] → ]]."""
    return name.replace("]", "]]")


def _sql_string_escape(name: str) -> str:
    """Escapa un nome SQL Server per le stringhe N'...' : ' → ''."""
    return name.replace("'", "''")


def _validate_sql_identifier(name: str) -> str:
    """Valida che il nome non contenga caratteri SQL pericolosi.
    Permette: lettere, cifre, underscore, trattino, spazio.
    Solleva ValueError se il nome non è valido."""
    if not name or not re.match(r'^[\w\s\-]+$', name):
        raise ValueError(
            f"Nome database non valido: {name!r} — "
            f"usa solo lettere, cifre, trattini e underscore"
        )
    return name


def _create_junction(link_path, target_path):
    """Crea una junction NTFS. Rimuove junction preesistente.
    Se il path è una directory reale (non junction) la rinomina come backup invece di bloccare."""
    link = Path(link_path)
    target = Path(target_path)
    if link.exists() or link.is_symlink():
        # Verifica che sia una junction/symlink, NON una directory reale.
        # os.path.islink() restituisce True per junction e symlink su Windows (Python 3.8+).
        if link.is_dir() and not os.path.islink(str(link)):
            # Directory reale: rinomina come backup invece di bloccare il promote
            backup = link.parent / f"{link.name}_dir_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                link.rename(backup)
            except Exception as e:
                raise RuntimeError(
                    f"{link} è una directory reale e non è stato possibile rinominarla: {e}"
                )
        # rmdir rimuove junction senza toccare il contenuto target
        subprocess.run(f'cmd /c rmdir /Q "{link}"',
                       capture_output=True, text=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        # Se rmdir fallisce ed è ancora una junction broken, prova shutil come ultimo resort
        if link.exists() and os.path.islink(str(link)):
            try:
                shutil.rmtree(str(link))
            except Exception:
                subprocess.run(f'cmd /c rd /s /q "{link}"',
                               capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    if link.exists():
        raise RuntimeError(f"Impossibile rimuovere {link} — potrebbe essere in uso")
    # Usa _winapi.CreateJunction (API nativa Python, niente quoting cmd)
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, OSError):
        # Fallback: cmd /c mklink (stringa, non lista — evita doppio quoting)
        r = subprocess.run(f'cmd /c mklink /J "{link}" "{target}"',
                           capture_output=True, text=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(f"mklink /J fallito: {(r.stderr or r.stdout).strip()}")


# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
class Config:
    def __init__(self):
        self.package_path = ""
        self.environment  = "test"
        self.acl_seed_uat = True
        self.base_dir     = r"C:\PortaleNovicrom"
        self.python_path  = detect_python() or ""
        self.db_host = ""; self.db_name = ""; self.db_user = ""
        self.db_password = ""; self.db_trusted = False
        self.db_driver = _preferred_sql_server_odbc_driver()
        self.db_trust_cert = True   # True se il cert SSL del server non è verificabile
        self.ldap_uri = "ldap://DC01.cnovicrom.local"
        self.ldap_bind_dn = ""; self.ldap_bind_pwd = ""
        self.ldap_user_base = "OU=Users,DC=cnovicrom,DC=local"
        self.ldap_domain = "cnovicrom.local"; self.ldap_skip = False
        self.email_host = ""; self.email_port = "25"
        self.email_user = ""; self.email_pwd = ""
        self.email_tls = False; self.email_skip = False
        self.iis_hostname = ""; self.iis_port = "8080"; self.iis_https = False
        self.secret_key = ""; self.release_tag = ""
        self.dev_source     = ""
        self.admin_username = "admin"
        self.admin_email    = ""
        self.admin_password = ""
        self.admin_django_superuser = True
        # Moduli selezionati per l'installazione.
        # Default: tutti i moduli con default=True (sistema + standard).
        self.selected_modules: list[str] = [
            m["key"] for m in MODULE_REGISTRY if m["default"]
        ]
        # Assistente AI (Ollama on-premise + embeddings RAG). Scritte in to_env()
        # solo se il modulo "ai_assistant" e' selezionato. Default conservativi:
        # chat su Ollama locale, embeddings DISATTIVI (opt-in da AIPage).
        self.ai_base_url      = "http://127.0.0.1:11434"
        self.ai_chat_model    = "qwen2.5:14b-instruct"
        self.ai_embed_backend = "off"               # "off" | "ollama" | "tei"
        self.ai_embed_model   = "nomic-embed-text"  # backend ollama
        self.ai_tei_base_url  = "http://127.0.0.1:8081"  # backend tei
        self.ai_tei_model     = "BAAI/bge-m3"            # backend tei

    @property
    def env_path(self): return Path(self.base_dir) / self.environment
    @property
    def app_pool_name(self): return f"PortaleNovicrom-{self.environment.upper()}"
    @property
    def site_name(self): return f"PortaleNovicrom-{self.environment.upper()}"

    def generate_secret_key(self):
        import secrets; self.secret_key = secrets.token_hex(50)

    def to_env(self):
        p = "https" if self.iis_https else "http"
        h = self.iis_hostname or "localhost"
        pt = f":{self.iis_port}" if self.iis_port not in ("80","443") else ""
        ep = self.env_path
        db_driver = self.db_driver or _preferred_sql_server_odbc_driver() or "ODBC Driver 18 for SQL Server"
        lines = [
            f"# Generato da Setup Wizard — {datetime.now():%Y-%m-%d %H:%M}\n",
            f"DJANGO_SECRET_KEY={self.secret_key}",
            f"DJANGO_DEBUG=False",
            f"DJANGO_ALLOWED_HOSTS={h},127.0.0.1",
            f"APP_VERSION={APP_VERSION}",
            *_module_version_lines(APP_VERSION),
            "",
            f"DB_ENGINE=sqlserver",
            f"DB_NAME={self.db_name}",
            f"DB_HOST={self.db_host}",
            f"DB_DRIVER={db_driver}",
            f"DB_PORT=1433",
            f"DB_TRUST_CERT={'True' if self.db_trust_cert else 'False'}",
            ("DB_TRUSTED_CONNECTION=yes" if self.db_trusted
             else f"DB_USER={self.db_user}\nDB_PASSWORD={self.db_password}"),
            f"\nDJANGO_CSRF_TRUSTED_ORIGINS={p}://{h}{pt}",
            f"SECURE_SSL_REDIRECT=False",
            f"SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https",
            f"USE_X_FORWARDED_HOST=True",
            f"SESSION_COOKIE_SECURE={'True' if self.iis_https else 'False'}",
            f"CSRF_COOKIE_SECURE={'True' if self.iis_https else 'False'}",
            f"\nSTATIC_ROOT={ep}\\static",
            f"MEDIA_ROOT={ep}\\media",
            f"DJANGO_LOG_DIR={ep}\\logs",
            f"SETUP_COMPLETED=1\n",
        ]
        if not self.ldap_skip:
            lines += [
                f"LDAP_SERVER_URI={self.ldap_uri}",
                f"LDAP_BIND_DN={self.ldap_bind_dn}",
                f"LDAP_BIND_PASSWORD={self.ldap_bind_pwd}",
                f"LDAP_USER_SEARCH_BASE={self.ldap_user_base}",
                f"LDAP_DOMAIN={self.ldap_domain}\n",
            ]
        if not self.email_skip and self.email_host:
            lines += [
                f"EMAIL_HOST={self.email_host}",
                f"EMAIL_PORT={self.email_port}",
                f"EMAIL_USE_TLS={'True' if self.email_tls else 'False'}",
                f"EMAIL_HOST_USER={self.email_user}",
                f"EMAIL_HOST_PASSWORD={self.email_pwd}\n",
            ]
        lines += [
            f"GRAPH_TENANT_ID=\nGRAPH_CLIENT_ID=\nGRAPH_CLIENT_SECRET=\n",
            f"DJANGO_CACHE_TABLE=django_cache{'_test' if self.environment=='test' else ''}",
            f"SQL_LOG_ENABLED={'True' if self.environment=='test' else 'False'}",
            f"ENVIRONMENT={self.environment}",
        ]
        # Assistente AI (solo se il modulo e' selezionato). On-premise, fail-safe:
        # con embeddings "off" il RAG resta BM25-only; "tei" usa l'endpoint OpenAI-
        # compatibile (Text Embeddings Inference) su GPU.
        if "ai_assistant" in self.selected_modules:
            lines += [
                "\n# --- Assistente AI (Ollama + RAG) ---",
                "OLLAMA_API_PROVIDER=ollama",
                f"OLLAMA_BASE_URL={self.ai_base_url}",
                f"OLLAMA_CHAT_MODEL={self.ai_chat_model}",
                "OLLAMA_CHAT_ENABLED=True",
                "OLLAMA_RAG_SGI_ENABLED=True",
            ]
            if self.ai_embed_backend == "ollama":
                lines += [
                    "OLLAMA_EMBED_ENABLED=True",
                    "RAG_EMBED_BACKEND=ollama",
                    f"OLLAMA_EMBED_MODEL={self.ai_embed_model}",
                ]
            elif self.ai_embed_backend == "tei":
                lines += [
                    "OLLAMA_EMBED_ENABLED=True",
                    "RAG_EMBED_BACKEND=openai",
                    f"RAG_EMBED_OPENAI_BASE_URL={self.ai_tei_base_url}",
                    f"RAG_EMBED_OPENAI_MODEL={self.ai_tei_model}",
                ]
            else:
                lines += ["OLLAMA_EMBED_ENABLED=False"]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────
def is_admin():
    try: return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except: return False

def run_as_admin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1)

def _python_version_ok(version):
    return tuple(version[:2]) >= PYTHON_MIN_VERSION


def _python_version_label(version):
    return ".".join(str(part) for part in version[:3])


def _common_python_paths():
    candidates = [
        r"C:\Python313\python.exe",
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Program Files\Python313\python.exe",
        r"C:\Program Files\Python312\python.exe",
        r"C:\Program Files\Python311\python.exe",
        r"C:\Program Files (x86)\Python313\python.exe",
        r"C:\Program Files (x86)\Python312\python.exe",
        r"C:\Program Files (x86)\Python311\python.exe",
    ]

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        base = Path(local_appdata) / "Programs" / "Python"
        for version_dir in ("Python313", "Python312", "Python311"):
            candidates.append(str(base / version_dir / "python.exe"))

    seen = set()
    ordered = []
    for candidate in candidates:
        key = candidate.lower()
        if key not in seen:
            ordered.append(candidate)
            seen.add(key)
    return ordered


def _registry_python_paths():
    if winreg is None:
        return []

    candidates = []
    seen = set()
    key_specs = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Python\PythonCore"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python\PythonCore"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Python\PythonCore"),
    ]
    for hive, base_key in key_specs:
        try:
            with winreg.OpenKey(hive, base_key) as versions_key:
                count = winreg.QueryInfoKey(versions_key)[0]
                for idx in range(count):
                    try:
                        version_key = winreg.EnumKey(versions_key, idx)
                        with winreg.OpenKey(
                            hive, f"{base_key}\\{version_key}\\InstallPath"
                        ) as install_key:
                            install_path, _ = winreg.QueryValueEx(install_key, "")
                    except OSError:
                        continue
                    candidate = str(Path(install_path) / "python.exe")
                    key = candidate.lower()
                    if key not in seen:
                        candidates.append(candidate)
                        seen.add(key)
        except OSError:
            continue
    return candidates


def _probe_python_command(cmd):
    try:
        proc = subprocess.run(
            [
                *cmd,
                "-c",
                (
                    "import sys; "
                    "print(sys.executable); "
                    "print('.'.join(str(x) for x in sys.version_info[:3]))"
                ),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return None

    if proc.returncode != 0:
        return None

    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", lines[1])
    if not match:
        return None

    version = tuple(int(part) for part in match.groups())
    return {
        "path": lines[0],
        "version": version,
        "version_text": _python_version_label(version),
    }


def probe_python_path(python_path):
    python_path = (python_path or "").strip()
    if not python_path:
        return None
    return _probe_python_command([python_path])


def detect_python_info():
    if not getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if exe.name.lower() in {"python.exe", "pythonw.exe"}:
            info = probe_python_path(str(exe))
            if info and _python_version_ok(info["version"]):
                return info

    launcher = shutil.which("py")
    if launcher:
        for selector in ("-3.13", "-3.12", "-3.11"):
            info = _probe_python_command([launcher, selector])
            if info and _python_version_ok(info["version"]):
                return info

    seen = set()
    candidates = [*_common_python_paths(), *_registry_python_paths()]
    which_python = shutil.which("python")
    if which_python:
        candidates.append(which_python)

    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        info = probe_python_path(candidate)
        if info and _python_version_ok(info["version"]):
            return info
    return None


def detect_python():
    info = detect_python_info()
    return info["path"] if info else ""

def find_latest_zip(base_dir):
    d = Path(base_dir) / "shared" / "packages"
    if d.exists():
        zips = sorted(d.glob("portale-novicrom-*.zip"), reverse=True)
        if zips: return str(zips[0])
    return ""


# ─────────────────────────────────────────────────────────────
# WIDGET BASE
# ─────────────────────────────────────────────────────────────

def Label(parent, text="", font=FN, fg=GRAY700, bg="white", **kw):
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **kw)

def frame(parent, bg="white", **kw):
    return tk.Frame(parent, bg=bg, **kw)

class ScrollableFrame(tk.Frame):
    """Frame con scrollbar verticale opzionale."""
    def __init__(self, parent, bg="white", **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.bind_all("<MouseWheel>", self._on_scroll)

    def _on_canvas_resize(self, e):
        self.canvas.itemconfig(self._win, width=e.width)

    def _on_scroll(self, e):
        self.canvas.yview_scroll(-1*(e.delta//120), "units")

    def show_scrollbar(self, show=True):
        if show: self.sb.pack(side="right", fill="y")
        else: self.sb.pack_forget()


class FieldGroup(tk.Frame):
    """Label + Entry con errore opzionale."""
    def __init__(self, parent, label, var, show="", mono=False, **kw):
        super().__init__(parent, bg="white", **kw)
        self.var = var
        lf = frame(self)
        lf.pack(fill="x", pady=(0,2))
        tk.Label(lf, text=label, font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(side="left")
        self._err = tk.Label(lf, text="", font=(SF,9), fg=RED, bg="white")
        self._err.pack(side="left", padx=(8,0))
        ent = tk.Entry(self, textvariable=var, show=show, relief="flat",
                       font=FMO if mono else FN,
                       bg=GRAY50, fg=GRAY800,
                       insertbackground=BRAND,
                       highlightthickness=1, highlightbackground=GRAY200,
                       highlightcolor=BRAND)
        ent.pack(fill="x", ipady=6, ipadx=8)

    def err(self, msg=""): self._err.configure(text=msg)
    def ok(self): self._err.configure(text="")


class PrimaryButton(tk.Frame):
    def __init__(self, parent, text, command, bg=BRAND, fg="white", **kw):
        super().__init__(parent, bg=bg, cursor="hand2", **kw)
        self._bg, self._hbg = bg, BRAND_HOVER if bg==BRAND else "#374151"
        self._lbl = tk.Label(self, text=text, font=(SF,10,"bold"),
                              fg=fg, bg=bg, padx=20, pady=8, cursor="hand2")
        self._lbl.pack()
        self._lbl.bind("<Button-1>", lambda e: command())
        self.bind("<Button-1>",      lambda e: command())
        self._lbl.bind("<Enter>", lambda e: (self.config(bg=self._hbg),
                                              self._lbl.config(bg=self._hbg)))
        self._lbl.bind("<Leave>", lambda e: (self.config(bg=self._bg),
                                              self._lbl.config(bg=self._bg)))

    def configure_text(self, t): self._lbl.configure(text=t)
    def set_state(self, enabled):
        st = "hand2" if enabled else "arrow"
        col_bg = self._bg if enabled else GRAY200
        col_fg = "white" if enabled else GRAY400
        self._lbl.configure(bg=col_bg, fg=col_fg, cursor=st)
        self.configure(bg=col_bg, cursor=st)


class SecondaryButton(tk.Frame):
    def __init__(self, parent, text, command, **kw):
        super().__init__(parent, bg=GRAY100, cursor="hand2", **kw)
        self._command = command
        self._enabled = True
        self._lbl = tk.Label(self, text=text, font=FN,
                              fg=GRAY700, bg=GRAY100, padx=16, pady=8, cursor="hand2")
        self._lbl.pack()
        for w in (self, self._lbl):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _on_click(self, _=None):
        if self._enabled:
            self._command()

    def _on_enter(self, _=None):
        if self._enabled:
            self.config(bg=GRAY200); self._lbl.config(bg=GRAY200)

    def _on_leave(self, _=None):
        bg = GRAY100 if self._enabled else GRAY50
        self.config(bg=bg); self._lbl.config(bg=bg)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if enabled:
            self._lbl.configure(fg=GRAY700, cursor="hand2")
            self.configure(cursor="hand2", bg=GRAY100)
            self._lbl.configure(bg=GRAY100)
        else:
            self._lbl.configure(fg=GRAY400, cursor="arrow", bg=GRAY50)
            self.configure(cursor="arrow", bg=GRAY50)


# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

class Sidebar(tk.Frame):
    def __init__(self, parent, steps=None, subtitle="Setup Wizard"):
        super().__init__(parent, bg=SIDEBAR_BG, width=SIDEBAR_W)
        self.pack_propagate(False)
        self._current = 0
        self._steps = steps if steps is not None else STEPS

        # Logo
        hdr = frame(self, bg=SIDEBAR_BG)
        hdr.pack(fill="x", padx=22, pady=(28, 0))
        tk.Label(hdr, text="⚙", font=(SF,26), bg=SIDEBAR_BG, fg="white").pack(anchor="w")
        tk.Label(hdr, text="Portale\nNovicrom", font=(SF,14,"bold"),
                 bg=SIDEBAR_BG, fg="white", justify="left").pack(anchor="w", pady=(4,2))
        tk.Label(hdr, text=subtitle, font=(SF,9),
                 bg=SIDEBAR_BG, fg="#5bb3e8").pack(anchor="w")

        frame(self, bg="#13345e", height=1).pack(fill="x", padx=20, pady=18)

        self._steps_frame = frame(self, bg=SIDEBAR_BG)
        self._steps_frame.pack(fill="x")
        self._render()

    def _render(self):
        for w in self._steps_frame.winfo_children(): w.destroy()
        for i, name in enumerate(self._steps):
            done    = i < self._current
            active  = i == self._current
            row = frame(self._steps_frame, bg=SIDEBAR_BG)
            row.pack(fill="x", padx=14, pady=1)

            if done:
                dot_bg, dot_fg, name_fg = "#166534", "#86efac", "#93c5fd"
                sym = "✓"
            elif active:
                dot_bg, dot_fg, name_fg = ORANGE, "white", "white"
                sym = str(i+1)
            else:
                dot_bg, dot_fg, name_fg = SIDEBAR_BG, "#334155", "#475569"
                sym = "·"

            # Highlight riga attiva
            row_bg = "#12365f" if active else SIDEBAR_BG
            row.configure(bg=row_bg)

            dot = tk.Label(row, text=sym, font=(SF,8,"bold"),
                           bg=dot_bg if done or active else row_bg,
                           fg=dot_fg, width=2, height=1,
                           relief="flat", padx=2)
            dot.pack(side="left", padx=(2,8), pady=3)
            tk.Label(row, text=name, font=(SF, 9, "bold" if active else "normal"),
                     bg=row_bg, fg=name_fg, anchor="w").pack(side="left")

        # Footer
        frame(self._steps_frame, bg=SIDEBAR_BG, height=24).pack()
        tk.Label(self._steps_frame, text=f"v{APP_VERSION}", font=(SF,8),
                 bg=SIDEBAR_BG, fg="#334155").pack(side="bottom", pady=10)

    def set(self, idx):
        self._current = idx
        self._render()


# ─────────────────────────────────────────────────────────────
# BASE PAGE
# ─────────────────────────────────────────────────────────────

class Page(tk.Frame):
    def __init__(self, parent, title, subtitle=""):
        super().__init__(parent, bg="white")
        # Header
        hdr = frame(self)
        hdr.pack(fill="x", padx=32, pady=(26,0))
        self.title_label = tk.Label(hdr, text=title, font=(SF,18,"bold"),
                                     fg=GRAY900, bg="white")
        self.title_label.pack(anchor="w")
        if subtitle:
            tk.Label(hdr, text=subtitle, font=(SF,10), fg=GRAY500, bg="white").pack(anchor="w", pady=(2,0))
        frame(self, bg=GRAY100, height=1).pack(fill="x", pady=(16,0))
        # Body scrollabile
        self.sf = ScrollableFrame(self)
        self.sf.pack(fill="both", expand=True)
        self.sf.show_scrollbar(False)
        self.body = self.sf.inner

    def pad(self): return frame(self.body, pady=4)
    def on_enter(self): pass
    def validate(self): return True
    def on_leave(self): pass


# ─────────────────────────────────────────────────────────────
# HELPER — barra pulsanti inferiore (usata da WizardApp, ReleaseApp, UninstallApp)
# ─────────────────────────────────────────────────────────────

def _build_bottom_bar(parent, on_back, on_cancel, on_next, on_close,
                       next_bg=None, finish_bg="#166534"):
    """Crea la barra pulsanti inferiore comune a tutte le App.

    Restituisce (btn_back, btn_cancel, btn_next, btn_finish).
    I pulsanti sono creati ma visibilità/stato vengono gestiti dalla App via _show().
    """
    bar = frame(parent, bg=GRAY50)
    bar.configure(highlightthickness=1, highlightbackground=GRAY200)
    bar.pack(fill="x", side="bottom")

    left_bar = frame(bar, bg=GRAY50)
    left_bar.pack(side="left", padx=20, pady=12)
    btn_back   = SecondaryButton(left_bar, "◀  Indietro", on_back)
    btn_back.pack(side="left")
    btn_cancel = SecondaryButton(left_bar, "Annulla", on_cancel)
    btn_cancel.pack(side="left", padx=(8, 0))

    right_bar = frame(bar, bg=GRAY50)
    right_bar.pack(side="right", padx=20, pady=12)
    kw_next   = {"bg": next_bg} if next_bg else {}
    btn_next   = PrimaryButton(right_bar, "Avanti  ▶", on_next, **kw_next)
    btn_next.pack(side="right")
    btn_finish = PrimaryButton(right_bar, "✓  Chiudi", on_close, bg=finish_bg)
    btn_finish.pack(side="right")

    return btn_back, btn_cancel, btn_next, btn_finish


# ─────────────────────────────────────────────────────────────
# CARD SELECTOR (senza radio button nativo)
# ─────────────────────────────────────────────────────────────

class CardSelector(tk.Frame):
    """Gruppo di card selezionabili — nessun radio button nativo."""
    def __init__(self, parent, options, initial=None, on_change=None, **kw):
        super().__init__(parent, bg="white", **kw)
        self._selected = initial or options[0][0]
        self._on_change = on_change
        self._cards = {}
        for value, title, desc, colors in options:
            bg, border, title_color = colors
            c = self._make_card(value, title, desc, bg, border, title_color)
            self._cards[value] = (c, bg, border)
        self._refresh()

    def _make_card(self, value, title, desc, bg, border, title_color):
        outer = frame(self, bg="white")
        outer.pack(fill="x", pady=4)
        card = tk.Frame(outer, bg=bg, cursor="hand2",
                        highlightthickness=2, highlightbackground=border)
        card.pack(fill="x")

        inner = frame(card, bg=bg)
        inner.pack(fill="x", padx=16, pady=12)

        top = frame(inner, bg=bg)
        top.pack(fill="x")

        # Check indicator
        chk = tk.Label(top, text="", font=(SF,11,"bold"),
                        bg=bg, fg="white", width=2)
        chk.pack(side="right")

        tk.Label(top, text=title, font=(SF,11,"bold"),
                 bg=bg, fg=title_color).pack(side="left")
        tk.Label(inner, text=desc, font=(SF,9),
                 bg=bg, fg=GRAY500).pack(anchor="w", pady=(3,0))

        # Bind click su tutto
        for w in (card, inner, top, chk):
            w.bind("<Button-1>", lambda e, v=value: self.select(v))
        card._chk = chk
        card._bg  = bg
        card._value = value
        return card

    def _refresh(self):
        for value, (card, bg, border) in self._cards.items():
            if value == self._selected:
                card.configure(highlightthickness=3, highlightbackground=border)
                card._chk.configure(
                    text="✓",
                    bg=border,
                    fg="white" if border not in (YELLOW_BD,) else GRAY800
                )
            else:
                card.configure(highlightthickness=1, highlightbackground=GRAY200)
                card._chk.configure(text="", bg=card._bg)

    def select(self, value):
        self._selected = value
        self._refresh()
        if self._on_change: self._on_change(value)

    @property
    def value(self): return self._selected


# ─────────────────────────────────────────────────────────────
# PAGINE
# ─────────────────────────────────────────────────────────────

class WelcomePage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Benvenuto nel Setup Wizard",
                         "Installazione guidata di Portale Novicrom su Windows Server + IIS")
        self.cfg = cfg
        b = self.body

        frame(b, height=4).pack()

        cards = [
            ("📋 Cosa verrà fatto",
             "Struttura directory · virtualenv Python · dipendenze pip\n"
             "Django migrate · collectstatic · configurazione IIS"),
            ("⏱  Tempo stimato",
             "10–20 minuti in base alla velocità di rete"),
            ("🔐 Prerequisiti",
             "Eseguire come Amministratore · Python 3.11+\n"
             "IIS + HttpPlatformHandler · ODBC Driver 17 for SQL Server"),
        ]
        for title, desc in cards:
            c = frame(b, bg=GRAY50,
                      highlightthickness=1, highlightbackground=GRAY200)
            c.pack(fill="x", padx=32, pady=4)
            tk.Label(c, text=title, font=(SF,10,"bold"),
                     bg=GRAY50, fg=GRAY800).pack(anchor="w", padx=14, pady=(10,2))
            tk.Label(c, text=desc, font=(SF,9),
                     bg=GRAY50, fg=GRAY500, justify="left").pack(anchor="w", padx=14, pady=(0,10))

        if not is_admin():
            warn = frame(b, bg=YELLOW_BG,
                         highlightthickness=1, highlightbackground=YELLOW_BD)
            warn.pack(fill="x", padx=32, pady=(10,0))
            tk.Label(warn, text="⚠   Stai eseguendo senza privilegi di Amministratore",
                     font=(SF,9,"bold"), bg=YELLOW_BG, fg=YELLOW_TX).pack(anchor="w", padx=14, pady=(10,2))
            tk.Label(warn, text="La configurazione IIS richiede diritti di Admin. "
                                 "Usa i .bat nel menu per avviare come Admin.",
                     font=FSM, bg=YELLOW_BG, fg=YELLOW_TX).pack(anchor="w", padx=14, pady=(0,10))


class PackagePage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Pacchetto / Sorgente",
                         "Seleziona il file .zip (TEST/PROD) o la cartella sorgente (DEV)")
        self.cfg = cfg
        self._zip_var = tk.StringVar()
        self._dev_var = tk.StringVar()
        b = self.body
        frame(b, height=8).pack()

        # ── Sezione TEST/PROD (zip) ────────────────────────────
        self._zip_sec = frame(b)
        tk.Label(self._zip_sec, text="File pacchetto (.zip)", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row = frame(self._zip_sec)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._zip_var, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia…  ", self._browse_zip).pack(side="left", padx=(8,0))
        self._zip_err  = tk.Label(self._zip_sec, text="", font=FSM, fg=RED, bg="white")
        self._zip_err.pack(anchor="w", pady=(3,0))
        self._zip_info = frame(self._zip_sec, bg=GREEN_BG,
                               highlightthickness=1, highlightbackground=GREEN_BD)
        self._zip_info_lbl = tk.Label(self._zip_info, text="", font=FSM, bg=GREEN_BG, fg=GREEN)
        self._zip_info_lbl.pack(anchor="w", padx=12, pady=8)
        self._zip_var.trace_add("write", self._on_zip_change)
        frame(self._zip_sec, height=12).pack()
        tk.Label(self._zip_sec, text="Lascia vuoto se il release è già estratto in releases\\",
                 font=FSM, fg=GRAY400, bg="white").pack(anchor="w")

        # ── Sezione DEV (solo per modalità script, non exe) ───
        # Quando si gira come .exe il sorgente è bundled → questa pagina è saltata
        self._dev_sec = frame(b)
        tk.Label(self._dev_sec,
                 text="Cartella sorgente (radice del repository)",
                 font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row2 = frame(self._dev_sec)
        row2.pack(fill="x")
        tk.Entry(row2, textvariable=self._dev_var, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row2, "  Sfoglia…  ", self._browse_dev).pack(side="left", padx=(8,0))
        self._dev_err  = tk.Label(self._dev_sec, text="", font=FSM, fg=RED, bg="white")
        self._dev_err.pack(anchor="w", pady=(3,0))
        self._dev_info = frame(self._dev_sec, bg=BLUE_BG,
                               highlightthickness=1, highlightbackground=BLUE_BD)
        self._dev_info_lbl = tk.Label(self._dev_info, text="", font=FSM,
                                      bg=BLUE_BG, fg="#1d4ed8")
        self._dev_info_lbl.pack(anchor="w", padx=12, pady=8)
        self._dev_var.trace_add("write", self._on_dev_change)
        frame(self._dev_sec, height=8).pack()
        tk.Label(self._dev_sec,
                 text="Deve contenere la cartella django_app\\",
                 font=FSM, fg=GRAY400, bg="white").pack(anchor="w")

    def on_enter(self):
        if self.cfg.environment == "dev":
            self._zip_sec.pack_forget()
            self._dev_sec.pack(fill="x", padx=32)
            if not self._dev_var.get() and self.cfg.dev_source:
                self._dev_var.set(self.cfg.dev_source)
        else:
            self._dev_sec.pack_forget()
            self._zip_sec.pack(fill="x", padx=32)
            if not self._zip_var.get():
                p = find_latest_zip(self.cfg.base_dir)
                if p: self._zip_var.set(p)

    def _browse_zip(self):
        p = filedialog.askopenfilename(
            title="Seleziona pacchetto release",
            filetypes=[("Zip files","*.zip"),("All","*.*")])
        if p: self._zip_var.set(p)

    def _browse_dev(self):
        p = filedialog.askdirectory(title="Seleziona cartella sorgente del repository")
        if p: self._dev_var.set(p)

    def _on_zip_change(self, *_):
        val = self._zip_var.get().strip()
        self._zip_err.configure(text="")
        if val and Path(val).exists():
            n = Path(val).name
            m = re.search(r"v(\d+\.\d+[\.\d]*)", n)
            ver = m.group(1) if m else "?"
            sz  = round(Path(val).stat().st_size/1024/1024, 1)
            self._zip_info_lbl.configure(text=f"  ✓  {n}   ·   versione {ver}   ·   {sz} MB")
            self._zip_info.pack(fill="x", pady=(8,0))
        else:
            self._zip_info.pack_forget()

    def _on_dev_change(self, *_):
        val = self._dev_var.get().strip()
        if val and (Path(val) / "django_app").exists():
            self._dev_info_lbl.configure(
                text=f"  ✓  django_app trovata in {Path(val).name}")
            self._dev_info.pack(fill="x", pady=(8,0))
        else:
            self._dev_info.pack_forget()

    def validate(self):
        if self.cfg.environment == "dev":
            # Questa pagina è saltata quando si gira come .exe (sorgente bundled)
            # Viene mostrata solo in modalità script per puntare al repo locale
            val = self._dev_var.get().strip()
            if not val:
                self._dev_err.configure(text="Seleziona la cartella sorgente")
                return False
            if not (Path(val) / "django_app").exists():
                self._dev_err.configure(
                    text="Cartella django_app non trovata in questo percorso")
                return False
            self.cfg.dev_source = val
        else:
            val = self._zip_var.get().strip()
            if val and not Path(val).exists():
                self._zip_err.configure(text="File non trovato")
                return False
            self.cfg.package_path = val
        return True


class EnvironmentPage(Page):
    def __init__(self, parent, cfg, preselect=None):
        super().__init__(parent, "Seleziona Ambiente",
                         "In quale ambiente vuoi installare il portale?")
        self.cfg = cfg
        b = self.body
        frame(b, height=6).pack()

        options = [
            ("dev",
             "DEV — Sviluppo locale",
             "PC sviluppatore · SQLite · Django dev server (porta 8000) · senza IIS",
             (BLUE_BG, BLUE_BD, "#1d4ed8")),
            ("test",
             "TEST — Validazione interna",
             "Windows Server · SQL Server TEST · IIS porta 8080",
             (YELLOW_BG, YELLOW_BD, YELLOW_TX)),
            ("prod",
             "PROD — Produzione",
             "Windows Server · SQL Server PROD · IIS porta 80 · utenti reali",
             (GREEN_BG, GREEN_BD, "#166534")),
        ]
        self._sel = CardSelector(b, options, initial=preselect or "test",
                                  on_change=self._on_env)
        self._sel.pack(fill="x", padx=32)

        frame(b, bg=GRAY100, height=1).pack(fill="x", padx=32, pady=14)

        dirl = frame(b)
        dirl.pack(fill="x", padx=32)
        tk.Label(dirl, text="Directory base di installazione",
                 font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row = frame(dirl)
        row.pack(fill="x")
        self._base = tk.StringVar(value=r"C:\PortaleNovicrom")
        ent = tk.Entry(row, textvariable=self._base, font=FMO,
                        relief="flat", bg=GRAY50, fg=GRAY800,
                        highlightthickness=1, highlightbackground=GRAY200,
                        highlightcolor=BRAND)
        ent.pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia  ",
                         lambda: self._base.set(
                             filedialog.askdirectory() or self._base.get())
                         ).pack(side="left", padx=(8,0))

        self._seed_uat = tk.BooleanVar(value=bool(getattr(self.cfg, "acl_seed_uat", True)))
        self._acl_seed_box = frame(
            b,
            bg=YELLOW_BG,
            highlightthickness=1,
            highlightbackground=YELLOW_BD,
        )
        tk.Checkbutton(
            self._acl_seed_box,
            text="  Esegui seed UAT ACL automatico dopo bootstrap (solo TEST)",
            variable=self._seed_uat,
            font=(SF, 9, "bold"),
            bg=YELLOW_BG,
            fg=YELLOW_TX,
            activebackground=YELLOW_BG,
            activeforeground=YELLOW_TX,
            selectcolor=YELLOW_BG,
            anchor="w",
            justify="left",
        ).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Label(
            self._acl_seed_box,
            text="Crea utenti/ruoli/scenari UAT seed. Consigliato in TEST, da tenere disattivo in PROD.",
            font=FSM,
            bg=YELLOW_BG,
            fg=YELLOW_TX,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        self._dev_note = frame(b, bg=BLUE_BG,
                                highlightthickness=1, highlightbackground=BLUE_BD)
        tk.Label(self._dev_note,
                 text="ℹ   Ambiente DEV: configura solo .env + venv. IIS non viene toccato.\n"
                       "    Usa:  python manage.py runserver --settings=config.settings.dev",
                 font=FSM, bg=BLUE_BG, fg="#1d4ed8", justify="left"
                 ).pack(anchor="w", padx=14, pady=10)
        self._on_env(self._sel.value)

    def _on_env(self, val):
        if val == "test":
            self._acl_seed_box.pack(fill="x", padx=32, pady=(8,0))
        else:
            self._acl_seed_box.pack_forget()
        if val == "dev":
            self._dev_note.pack(fill="x", padx=32, pady=(8,0))
        else:
            self._dev_note.pack_forget()

    def validate(self):
        self.cfg.environment = self._sel.value
        self.cfg.acl_seed_uat = bool(self._seed_uat.get() and self._sel.value == "test")
        self.cfg.base_dir    = self._base.get().strip()
        return bool(self.cfg.base_dir)


class PythonPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Percorso Python",
                         "Eseguibile Python 3.11+ per il virtualenv dell'applicazione")
        self.cfg = cfg
        self._var    = tk.StringVar()
        self._status = tk.StringVar()
        b = self.body
        frame(b, height=8).pack()

        sec = frame(b)
        sec.pack(fill="x", padx=32)
        tk.Label(sec, text="Percorso python.exe", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))

        row = frame(sec)
        row.pack(fill="x")
        ent = tk.Entry(row, textvariable=self._var, font=FMO,
                        relief="flat", bg=GRAY50, fg=GRAY800,
                        highlightthickness=1, highlightbackground=GRAY200,
                        highlightcolor=BRAND)
        ent.pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia  ", self._browse).pack(side="left", padx=(4,0))
        SecondaryButton(row, "  Verifica  ", self._check).pack(side="left", padx=(4,0))

        self._res = tk.Label(sec, textvariable=self._status,
                              font=FSM, fg=GRAY400, bg="white")
        self._res.pack(anchor="w", pady=(5,0))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=14)
        tk.Label(sec, text="Percorsi comuni:", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,6))

        for p in _common_python_paths():
            exists = Path(p).exists()
            row2 = frame(sec)
            row2.pack(anchor="w", pady=1)
            tk.Label(row2, text="●" if exists else "○",
                     font=(SF,9), fg=GREEN if exists else GRAY400, bg="white").pack(side="left", padx=(0,8))
            lbl = tk.Label(row2, text=p, font=FMO,
                            fg=GRAY700 if exists else GRAY400, bg="white", cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, v=p: self._var.set(v))

    def on_enter(self):
        if not self._var.get(): self._var.set(detect_python())

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Seleziona python.exe",
            filetypes=[("Python","python.exe"),("All","*.*")])
        if p: self._var.set(p)

    def _check(self):
        py = self._var.get().strip()
        info = probe_python_path(py)
        if not info:
            self._status.set("✗  File non trovato")
            self._res.configure(fg=RED)
            return
        if not _python_version_ok(info["version"]):
            self._status.set(
                f"✗  Python {info['version_text']} non supportato (serve 3.11+)"
            )
            self._res.configure(fg=RED)
            return
        self._var.set(info["path"])
        self._status.set(f"✓  Python {info['version_text']} — {info['path']}")
        self._res.configure(fg=GREEN)

    def validate(self):
        py = self._var.get().strip()
        info = probe_python_path(py)
        if not info:
            messagebox.showerror("Errore", "python.exe non trovato o non eseguibile.")
            return False
        if not _python_version_ok(info["version"]):
            messagebox.showerror(
                "Errore",
                f"Versione Python non supportata: {info['version_text']}. Serve Python 3.11+.",
            )
            return False
        self.cfg.python_path = info["path"]
        self._var.set(info["path"])
        return True


class DatabasePage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Database SQL Server",
                         "Connessione al database SQL Server")
        self.cfg = cfg
        self.root = parent.winfo_toplevel()  # ← FIX: get root window
        self._host    = tk.StringVar()
        self._name    = tk.StringVar()
        self._user    = tk.StringVar()
        self._pwd     = tk.StringVar()
        self._driver  = tk.StringVar(value=cfg.db_driver or _preferred_sql_server_odbc_driver())
        self._trusted = tk.BooleanVar(value=False)
        b = self.body
        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        # Row: Server discovery
        disc_row = frame(sec)
        disc_row.pack(fill="x", pady=(0,12))
        tk.Label(disc_row, text="Server\\Istanza (es: SQL01\\SQLEXPRESS)", 
                 font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
        
        host_control = frame(disc_row)
        host_control.pack(fill="x")
        
        # Combobox per server
        from tkinter import ttk
        self._host_combo = ttk.Combobox(host_control, textvariable=self._host, 
                                         font=FMO, state="normal", width=40)
        self._host_combo.pack(side="left", fill="x", expand=1, ipady=7, ipadx=8)
        
        # Pulsante scopri
        self._discover_btn = tk.Button(host_control, text="🔍 Scopri server",
                                       command=self._discover_servers,
                                       font=(SF,9,"bold"), bg=BRAND, fg="white",
                                       relief="flat", padx=16, pady=7,
                                       cursor="hand2", activebackground=BRAND_HOVER)
        self._discover_btn.pack(side="left", padx=(8,0))

        # 2 colonne per altri campi
        grid = frame(sec)
        grid.pack(fill="x", pady=(12,0))
        grid.columnconfigure(0, weight=1); grid.columnconfigure(1, weight=1)

        def cell(row, col, lbl, var, show=""):
            f = frame(grid)
            f.grid(row=row, column=col, sticky="ew", padx=(0,12 if col==0 else 0), pady=4)
            tk.Label(f, text=lbl, font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
            e = tk.Entry(f, textvariable=var, show=show, font=FMO, relief="flat",
                          bg=GRAY50, fg=GRAY800,
                          highlightthickness=1, highlightbackground=GRAY200,
                          highlightcolor=BRAND)
            e.pack(fill="x", ipady=7, ipadx=8)

        # Nome Database: Combobox + pulsante "Lista DB"
        db_frame = frame(grid)
        db_frame.grid(row=0, column=0, sticky="ew", padx=(0,12), pady=4)
        tk.Label(db_frame, text="Nome Database", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
        db_row = frame(db_frame)
        db_row.pack(fill="x")
        self._name_combo = ttk.Combobox(db_row, textvariable=self._name,
                                        font=FMO, state="normal")
        self._name_combo.pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        self._list_db_btn = tk.Button(db_row, text="📋 Lista DB",
                                      command=self._list_databases,
                                      font=(SF,8), bg=GRAY100, fg=GRAY700,
                                      relief="flat", padx=8, pady=7,
                                      cursor="hand2")
        self._list_db_btn.pack(side="left", padx=(4,0))

        cell(0, 1, "Utente SQL", self._user)
        cell(1, 0, "Password", self._pwd, show="*")
        driver_frame = frame(grid)
        driver_frame.grid(row=1, column=1, sticky="ew", pady=4)
        tk.Label(driver_frame, text="Driver ODBC SQL Server", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
        self._driver_combo = ttk.Combobox(driver_frame, textvariable=self._driver,
                                          font=FMO, state="readonly")
        self._driver_combo.pack(fill="x", ipady=7, ipadx=8)

        frame(sec, height=10).pack()
        chk_row = frame(sec)
        chk_row.pack(fill="x")
        cb = tk.Checkbutton(chk_row, text="  Usa Windows Authentication (Trusted Connection)",
                             variable=self._trusted, font=FN, bg="white", fg=GRAY700,
                             activebackground="white", selectcolor="white",
                             command=self._toggle)
        cb.pack(side="left")
        self._note = tk.Label(sec, text="", font=FSM, fg=GRAY500, bg="white")
        self._note.pack(anchor="w", pady=(4,0))
        self._driver_note = tk.Label(sec, text="", font=FSM, fg=GRAY500, bg="white")
        self._driver_note.pack(anchor="w", pady=(2,0))
        self._err = tk.Label(sec, text="", font=FSM, fg=RED, bg="white")
        self._err.pack(anchor="w")

    def _refresh_driver_options(self) -> list[str]:
        drivers = _installed_sql_server_odbc_drivers()
        try:
            self._driver_combo["values"] = drivers
        except Exception:
            pass
        selected = self._driver.get().strip()
        if selected not in drivers:
            selected = ""
        if not selected and self.cfg.db_driver in drivers:
            selected = self.cfg.db_driver
        if not selected:
            selected = _preferred_sql_server_odbc_driver(drivers)
        if selected:
            self._driver.set(selected)
        elif drivers:
            self._driver.set(drivers[0])
        else:
            self._driver.set("")
        self._update_driver_note(drivers)
        return drivers

    def _update_driver_note(self, drivers: list[str] | None = None, *, prefix: str | None = None):
        installed = drivers if drivers is not None else _installed_sql_server_odbc_drivers()
        selected = self._driver.get().strip()
        if selected:
            message = f"Driver SQL Server allineato: {selected}"
            if len(installed) > 1:
                message += f" | Installati: {', '.join(installed)}"
        elif installed:
            message = f"Driver SQL Server installati: {', '.join(installed)}"
        else:
            message = "Nessun driver ODBC SQL Server installato sul server applicativo."
        if prefix:
            message = f"{prefix} {message}"
        self._driver_note.configure(text=message)

    def _driver_candidates(self) -> list[str]:
        drivers = []
        selected = self._driver.get().strip()
        for driver in [selected, *_installed_sql_server_odbc_drivers()]:
            if driver and driver not in drivers:
                drivers.append(driver)
        return drivers

    def _discover_servers(self):
        """Avvia la discovery SQL Server in background (multi-strategia)."""
        self._err.configure(text="")
        self._note.configure(text="🔍 Ricerca server SQL Server in corso…")
        self._discover_btn.configure(state="disabled", text="🔍 Ricerca…")
        self._discover_active = True
        threading.Thread(target=self._discover_worker, daemon=True).start()

    def _discover_worker(self):
        """Worker thread: scopre server SQL Server con 5 strategie."""
        import socket
        found = set()

        # ── Strategia 1: Windows Registry (istanze locali) ───────
        # Più affidabile per trovare SQL Server installati sulla macchina
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL")
            i = 0
            local_hostname = socket.gethostname()
            while True:
                try:
                    instance_name, _, _ = winreg.EnumValue(key, i)
                    if instance_name.upper() == "MSSQLSERVER":
                        found.add(local_hostname)
                    else:
                        found.add(f"{local_hostname}\\{instance_name}")
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

        # ── Strategia 2: Windows Services (servizi MSSQL in esecuzione) ─
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Service | Where-Object {$_.Name -like 'MSSQL*' -and $_.Status -eq 'Running'} "
                 "| ForEach-Object { $_.Name }"],
                capture_output=True, text=True, timeout=8, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
            local_hostname = socket.gethostname()
            for line in result.stdout.strip().splitlines():
                svc = line.strip()
                if not svc:
                    continue
                if svc.upper() == "MSSQLSERVER":
                    found.add(local_hostname)
                elif svc.upper().startswith("MSSQL$"):
                    instance = svc.split("$", 1)[1]
                    found.add(f"{local_hostname}\\{instance}")
        except Exception:
            pass

        # ── Strategia 3: pyodbc.sqlservers() ─────────────────────
        # UDP broadcast su porta 1434 (SQL Server Browser service)
        try:
            if _pyodbc_module is None:
                raise ImportError("pyodbc non disponibile")
            for s in _pyodbc_module.sqlservers():
                if s: found.add(s)
        except Exception:
            pass

        # ── Strategia 4: scansione TCP host comuni su porta 1433 ─
        local_hostname = ""
        try: local_hostname = socket.gethostname()
        except: pass

        candidate_hosts = [
            "localhost", "127.0.0.1",
            local_hostname,
            "SQLSERVER", "SQL01", "SQL",
        ]
        # Aggiungi varianti con dominio AD
        try:
            fqdn = socket.getfqdn()
            domain_parts = fqdn.split(".")
            if len(domain_parts) > 1:
                domain = ".".join(domain_parts[1:])
                for prefix in ("SQL01", "SQLSERVER", "DC01", "SQL"):
                    candidate_hosts.append(f"{prefix}.{domain}")
        except Exception:
            pass

        def _tcp_reachable(host, port=1433, timeout=1.5):
            clean = host.split("\\")[0]
            try:
                with socket.create_connection((clean, port), timeout=timeout):
                    return True
            except Exception:
                return False

        seen_bases = set()
        for h in candidate_hosts:
            base = h.split("\\")[0].strip()
            if not base or base in seen_bases:
                continue
            seen_bases.add(base)
            if _tcp_reachable(base):
                found.add(base)

        # ── Strategia 5: pyodbc connessione di test per verifica ──
        # Tenta connessione rapida con ciascun driver ODBC per validare le entry trovate
        # (rimuove false positive da TCP scan)
        if not found:
            # Se nessuna strategia ha trovato nulla, prova connessione diretta
            try:
                if _pyodbc_module is None:
                    raise ImportError("pyodbc non disponibile")
                drivers = [d for d in _pyodbc_module.drivers()
                           if "SQL Server" in d]
                if drivers:
                    for drv in drivers[:1]:
                        for h in [local_hostname, "localhost", "(local)"]:
                            try:
                                cs = f"DRIVER={{{drv}}};SERVER={h};Trusted_Connection=yes;Connection Timeout=3"
                                conn = _pyodbc_module.connect(cs, autocommit=True, timeout=3)
                                # Se la connessione riesce, il server è raggiungibile
                                cur = conn.cursor()
                                cur.execute("SELECT @@SERVERNAME")
                                name = cur.fetchone()[0]
                                conn.close()
                                if name:
                                    found.add(name)
                                break
                            except Exception:
                                continue
            except Exception:
                pass

        # ── Aggiorna UI sul thread principale ────────────────────
        servers = sorted(found, key=lambda x: (x.lower() != "localhost", x.lower()))

        def _ui_update():
            # Salta l'aggiornamento se la pagina non è più attiva (race condition)
            if not getattr(self, '_discover_active', False):
                return
            try:
                self._discover_btn.configure(state="normal", text="🔍 Scopri server")
                if servers:
                    self._host_combo['values'] = servers
                    if not self._host.get():
                        self._host.set(servers[0])
                    self._note.configure(
                        text=f"✓ Trovati {len(servers)} server/istanz{'e' if len(servers)!=1 else 'a'} — seleziona o digita manualmente")
                else:
                    self._note.configure(
                        text="⚠ Nessun server trovato in automatico — inserisci manualmente Server\\Istanza")
            except Exception:
                pass
        self._note.after(0, _ui_update)

    def _list_databases(self):
        """Recupera la lista dei database dal server selezionato."""
        host = self._host.get().strip()
        if not host:
            self._err.configure(text="Seleziona prima un server SQL Server"); return
        self._err.configure(text="")
        self._note.configure(text="🔍 Connessione al server per lista database…")
        self._list_db_btn.configure(state="disabled")
        threading.Thread(target=self._list_databases_worker, daemon=True).start()

    def _list_databases_worker(self):
        """Worker thread: enumera i database user del server."""
        host = self._host.get().strip()
        user = self._user.get().strip()
        pwd  = self._pwd.get().strip()
        trusted = self._trusted.get()
        selected_driver = self._driver.get().strip()
        drivers = self._driver_candidates()
        result_dbs = []
        last_err   = ""
        driver_used = ""
        for drv in drivers:
            try:
                if _pyodbc_module is None:
                    last_err = "pyodbc non disponibile — installare pyodbc"
                    break
                if trusted:
                    cs = (f"DRIVER={{{drv}}};SERVER={host};"
                          f"Trusted_Connection=yes;Connection Timeout=5;TrustServerCertificate=yes")
                else:
                    if not user:
                        last_err = "Inserisci utente SQL o attiva Windows Auth"
                        continue
                    cs = (f"DRIVER={{{drv}}};SERVER={host};"
                          f"UID={user};PWD={pwd};Connection Timeout=5;TrustServerCertificate=yes")
                conn = _pyodbc_module.connect(cs, autocommit=True)
                cur  = conn.cursor()
                cur.execute(
                    "SELECT name FROM sys.databases "
                    "WHERE name NOT IN ('master','tempdb','model','msdb') "
                    "  AND state_desc='ONLINE' ORDER BY name")
                result_dbs = [r[0] for r in cur.fetchall()]
                conn.close()
                driver_used = drv
                last_err = ""
                break
            except Exception as e:
                last_err = str(e)

        def _ui():
            # Salta l'aggiornamento se la pagina non è più attiva (race condition)
            if not getattr(self, '_discover_active', False):
                return
            try:
                self._list_db_btn.configure(state="normal")
                if result_dbs:
                    self._name_combo['values'] = result_dbs
                    if driver_used:
                        self._driver.set(driver_used)
                        self._update_driver_note(prefix="Connessione verificata.")
                    if not self._name.get() or self._name.get() not in result_dbs:
                        # Auto-seleziona il DB con il nome più probabile
                        preferred = [d for d in result_dbs
                                     if "portale" in d.lower() or "novicrom" in d.lower()]
                        self._name.set(preferred[0] if preferred else result_dbs[0])
                    self._note.configure(
                        text=f"✓ {len(result_dbs)} database disponibili — seleziona dalla lista")
                elif last_err:
                    if selected_driver:
                        self._update_driver_note(prefix="Ultimo tentativo.")
                    self._note.configure(text=f"⚠ Errore connessione: {last_err[:70]}")
                else:
                    self._note.configure(text="⚠ Nessun database trovato (verifica permessi)")
            except Exception:
                pass
        self._note.after(0, _ui)

    def on_enter(self):
        if not self._name.get():
            db_name = "PortaleNovicrom"
            if self.cfg.environment == "test":
                db_name += "_TEST"
            elif self.cfg.environment == "prod":
                db_name += "_PROD"
            elif self.cfg.environment == "dev":
                db_name += "_DEV"
            self._name.set(db_name)
        # Mostra ODBC driver disponibili come nota informativa
        if _pyodbc_module:
            try:
                odbc_drivers = [d for d in _pyodbc_module.drivers() if "SQL Server" in d]
                if odbc_drivers:
                    self._note.configure(text=f"ℹ  Driver ODBC: {', '.join(odbc_drivers)}")
                else:
                    self._note.configure(text="⚠  Nessun driver ODBC per SQL Server — installa un driver compatibile.")
            except Exception:
                pass
        drivers = self._refresh_driver_options()
        if drivers:
            self._note.configure(text="ℹ  Il wizard userà il miglior driver SQL Server installato sul server applicativo.")
        else:
            self._note.configure(text="⚠  Nessun driver ODBC per SQL Server rilevato — installa un driver prima di procedere.")
        # Avvia la discovery automaticamente
        self._discover_servers()

    def on_leave(self):
        """Disattiva il flag di aggiornamento UI per i thread di background."""
        self._discover_active = False

    def _toggle(self):
        if self._trusted.get():
            self._note.configure(
                text="ℹ  L'account 'IIS AppPool\\PortaleNovicrom-ENV' deve avere accesso al DB SQL Server.")
        else: self._note.configure(text="")

    def validate(self):
        self._err.configure(text="")
        if not self._host.get().strip():
            self._err.configure(text="Inserisci Server\\Istanza SQL Server"); return False
        if not self._name.get().strip():
            self._err.configure(text="Inserisci il nome del database"); return False
        if not self._trusted.get() and not (self._user.get() and self._pwd.get()):
            self._err.configure(text="Inserisci utente e password, oppure attiva Windows Auth"); return False
        drivers = self._refresh_driver_options()
        if not drivers:
            self._err.configure(text="Nessun driver ODBC SQL Server installato sul server applicativo"); return False
        selected_driver = self._driver.get().strip()
        if selected_driver not in drivers:
            selected_driver = _preferred_sql_server_odbc_driver(drivers)
            self._driver.set(selected_driver)
            self._update_driver_note(drivers, prefix="Driver riallineato automaticamente.")
        self.cfg.db_host = self._host.get().strip()
        self.cfg.db_name = self._name.get().strip()
        self.cfg.db_user = self._user.get().strip()
        self.cfg.db_password = self._pwd.get().strip()
        self.cfg.db_trusted  = self._trusted.get()
        self.cfg.db_driver = selected_driver

        # ── Test connessione reale ────────────────────────────────────────────────
        # Prova prima senza TrustServerCertificate; se fallisce per SSL, riprova
        # con TrustServerCertificate=yes e chiede conferma all'utente.
        if _pyodbc_module is not None:
            host    = self.cfg.db_host
            drv     = self.cfg.db_driver
            user    = self.cfg.db_user
            pwd     = self.cfg.db_password
            trusted = self.cfg.db_trusted

            ok, err = _try_db_connection(drv, host, user, pwd, trusted, trust_cert=False)
            if ok:
                # Connessione verificata con certificato SSL valido
                self.cfg.db_trust_cert = False
            elif _is_ssl_cert_error(err):
                # Certificato non verificabile — retry con TrustServerCertificate=yes
                ok2, err2 = _try_db_connection(drv, host, user, pwd, trusted, trust_cert=True)
                if ok2:
                    msg = (
                        "Il server SQL Server usa un certificato SSL self-signed o emesso da "
                        "una CA interna non installata in questo sistema.\n\n"
                        "Il wizard può proseguire abilitando TrustServerCertificate=yes "
                        "(DB_TRUST_CERT=True nel file .env).\n\n"
                        "La connessione rimane cifrata ma l'identità del server non viene "
                        "verificata crittograficamente.\n\n"
                        "Soluzione definitiva: installare il certificato della CA nel "
                        "trust store di Windows (certlm.msc → Autorità di certificazione "
                        "radice attendibili).\n\n"
                        "Procedere con DB_TRUST_CERT=True?"
                    )
                    if messagebox.askyesno(
                        "Certificato SSL non verificabile", msg, parent=self.body
                    ):
                        self.cfg.db_trust_cert = True
                        self._err.configure(text="")
                        return True
                    else:
                        self._err.configure(
                            text="Connessione bloccata — installa la CA del server in Windows "
                                 "o abilitare DB_TRUST_CERT=True manualmente nel .env"
                        )
                        return False
                else:
                    self._err.configure(
                        text=f"Errore SSL — connessione fallita anche con TrustServerCertificate=yes: "
                             f"{err2[:80]}"
                    )
                    return False
            else:
                # Errore non SSL: credenziali, host sbagliato, ecc.
                self._err.configure(text=f"Connessione fallita: {err[:90]}")
                return False

        return True


class LDAPPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Active Directory",
                         "Autenticazione utenti tramite AD aziendale (opzionale)")
        self.cfg = cfg
        self._skip   = tk.BooleanVar(value=False)
        self._uri    = tk.StringVar(value="ldap://DC01.cnovicrom.local")
        self._dn     = tk.StringVar()
        self._pwd    = tk.StringVar()
        self._base   = tk.StringVar(value="OU=Users,DC=cnovicrom,DC=local")
        self._domain = tk.StringVar(value="cnovicrom.local")
        b = self.body
        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        # Skip toggle
        skip_row = frame(sec, bg=YELLOW_BG,
                          highlightthickness=1, highlightbackground=YELLOW_BD)
        skip_row.pack(fill="x", pady=(0,14))
        cb = tk.Checkbutton(skip_row, variable=self._skip, font=(SF,10,"bold"),
                             text="  Salta — usa solo account Django locali (senza AD)",
                             bg=YELLOW_BG, fg=YELLOW_TX, activebackground=YELLOW_BG,
                             selectcolor=YELLOW_BG, command=self._toggle)
        cb.pack(anchor="w", padx=12, pady=10)

        self._form = frame(sec)
        self._form.pack(fill="x")

        def row(lbl, var, show=""):
            f = frame(self._form)
            f.pack(fill="x", pady=4)
            tk.Label(f, text=lbl, font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
            e = tk.Entry(f, textvariable=var, show=show, font=FMO, relief="flat",
                          bg=GRAY50, fg=GRAY800,
                          highlightthickness=1, highlightbackground=GRAY200,
                          highlightcolor=BRAND)
            e.pack(fill="x", ipady=7, ipadx=8)

        row("URI LDAP", self._uri)
        row("Bind DN (service account)", self._dn)
        row("Bind Password", self._pwd, show="*")
        row("User Search Base", self._base)
        row("Dominio AD", self._domain)
        self.sf.show_scrollbar(True)

    def _toggle(self):
        s = "disabled" if self._skip.get() else "normal"
        for w in self._form.winfo_descendants():
            try: w.configure(state=s)
            except: pass

    def validate(self):
        self.cfg.ldap_skip = self._skip.get()
        self.cfg.ldap_uri  = self._uri.get().strip()
        self.cfg.ldap_bind_dn  = self._dn.get().strip()
        self.cfg.ldap_bind_pwd = self._pwd.get().strip()
        self.cfg.ldap_user_base= self._base.get().strip()
        self.cfg.ldap_domain   = self._domain.get().strip()
        return True


class EmailPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Email / SMTP",
                         "Configurazione server email per notifiche (opzionale)")
        self.cfg = cfg
        self._skip = tk.BooleanVar(value=False)
        self._host = tk.StringVar()
        self._port = tk.StringVar(value="25")
        self._user = tk.StringVar()
        self._pwd  = tk.StringVar()
        self._tls  = tk.BooleanVar(value=False)
        b = self.body
        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        cb = tk.Checkbutton(sec, variable=self._skip, font=FN,
                             text="  Salta configurazione email per ora",
                             bg="white", fg=GRAY600, activebackground="white",
                             selectcolor="white", command=self._toggle)
        cb.pack(anchor="w", pady=(0,12))

        self._form = frame(sec)
        self._form.pack(fill="x")
        grid = self._form
        grid.columnconfigure(0, weight=3); grid.columnconfigure(1, weight=1)

        def gcell(row, col, lbl, var, show="", span=1):
            f = frame(grid)
            f.grid(row=row, column=col, columnspan=span, sticky="ew",
                   padx=(0,8 if col==0 else 0), pady=4)
            tk.Label(f, text=lbl, font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
            e = tk.Entry(f, textvariable=var, show=show, font=FMO, relief="flat",
                          bg=GRAY50, fg=GRAY800,
                          highlightthickness=1, highlightbackground=GRAY200,
                          highlightcolor=BRAND)
            e.pack(fill="x", ipady=7, ipadx=8)

        gcell(0, 0, "Server SMTP", self._host)
        gcell(0, 1, "Porta", self._port)
        gcell(1, 0, "Utente Email", self._user)
        gcell(1, 1, "Password", self._pwd, show="*")
        f2 = frame(grid)
        f2.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8,0))
        tk.Checkbutton(f2, text="  Usa TLS", variable=self._tls,
                        bg="white", fg=GRAY700, activebackground="white",
                        selectcolor="white", font=FN).pack(anchor="w")

    def _toggle(self):
        s = "disabled" if self._skip.get() else "normal"
        for w in self._form.winfo_descendants():
            try: w.configure(state=s)
            except: pass

    def validate(self):
        self.cfg.email_skip = self._skip.get()
        self.cfg.email_host = self._host.get().strip()
        self.cfg.email_port = self._port.get().strip() or "25"
        self.cfg.email_user = self._user.get().strip()
        self.cfg.email_pwd  = self._pwd.get().strip()
        self.cfg.email_tls  = self._tls.get()
        return True


class IISPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Configurazione IIS",
                         "Sito web e Application Pool per l'ambiente selezionato")
        self.cfg = cfg
        self._hostname = tk.StringVar()
        self._port     = tk.StringVar(value="8080")
        self._https    = tk.BooleanVar(value=False)
        b = self.body
        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        tk.Label(sec, text="Hostname (DNS interno)", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
        tk.Label(sec, text="Lascia vuoto per rispondere su tutti gli IP del server",
                 font=FSM, fg=GRAY400, bg="white").pack(anchor="w", pady=(0,4))
        tk.Entry(sec, textvariable=self._hostname, font=FMO, relief="flat",
                  bg=GRAY50, fg=GRAY800, highlightthickness=1,
                  highlightbackground=GRAY200, highlightcolor=BRAND
                  ).pack(fill="x", ipady=7, ipadx=8)

        frame(sec, height=12).pack()
        row = frame(sec)
        row.pack(fill="x")

        left = frame(row)
        left.pack(side="left", fill="x", expand=True, padx=(0,16))
        tk.Label(left, text="Porta HTTP", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,3))
        tk.Entry(left, textvariable=self._port, font=FMO, width=8, relief="flat",
                  bg=GRAY50, fg=GRAY800, highlightthickness=1,
                  highlightbackground=GRAY200, highlightcolor=BRAND
                  ).pack(fill="x", ipady=7, ipadx=8)

        right = frame(row)
        right.pack(side="left")
        frame(right, height=26).pack()
        tk.Checkbutton(right, text="  Abilita HTTPS / SSL", variable=self._https,
                        font=FN, bg="white", fg=GRAY700, activebackground="white",
                        selectcolor="white", command=self._on_https).pack(anchor="w")

        self._https_note = tk.Label(sec, text="", font=FSM, fg=GRAY500, bg="white")
        self._https_note.pack(anchor="w", pady=(4,0))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=14)

        info = frame(sec, bg=BLUE_BG,
                      highlightthickness=1, highlightbackground=BLUE_BD)
        info.pack(fill="x")
        tk.Label(info, text="Cosa viene creato in IIS:", font=(SF,9,"bold"),
                 bg=BLUE_BG, fg="#1d4ed8").pack(anchor="w", padx=14, pady=(10,4))
        for item in ["Application Pool (No Managed Code · Always Running)",
                      "Sito IIS con physical path nella directory ambiente",
                      "Virtual directory /static → ENV\\static\\",
                      "Virtual directory /media  → ENV\\media\\",
                      "web.config con HttpPlatformHandler + Waitress"]:
            tk.Label(info, text=f"   ·  {item}", font=FSM,
                     bg=BLUE_BG, fg="#1d4ed8").pack(anchor="w", padx=14)
        frame(info, bg=BLUE_BG, height=10).pack()

    def on_enter(self):
        if self._port.get() in ("8080","80","443"):
            self._port.set("8080" if self.cfg.environment=="test" else "80")
        if not self._hostname.get():
            self._hostname.set(
                "portale-test.cnovicrom.local" if self.cfg.environment=="test"
                else "portale.cnovicrom.local")

    def _on_https(self):
        if self._https.get():
            self._port.set("443")
            self._https_note.configure(
                text="Importa il certificato SSL in IIS prima del primo accesso.")
        else:
            self._port.set("80" if self.cfg.environment=="prod" else "8080")
            self._https_note.configure(text="")

    def validate(self):
        p = self._port.get().strip()
        if not p.isdigit() or not (1 <= int(p) <= 65535):
            return False
        self.cfg.iis_hostname = self._hostname.get().strip()
        self.cfg.iis_port     = p
        self.cfg.iis_https    = self._https.get()
        return True


class HttpPlatformHandlerPage(Page):
    """Step 8 — verifica presenza HttpPlatformHandler in IIS."""

    def __init__(self, parent, cfg):
        super().__init__(parent, "Prerequisiti IIS",
                         "HttpPlatformHandler — modulo IIS richiesto per eseguire app Python")
        self.cfg = cfg
        self._installed = False
        b = self.body
        frame(b, height=14).pack()

        # ── Status card ──────────────────────────────────────────────
        self._card = frame(b, bg=GRAY50, highlightthickness=1, highlightbackground=GRAY200)
        self._card.pack(fill="x", padx=32)
        hrow = frame(self._card, bg=GRAY50)
        hrow.pack(fill="x", padx=18, pady=(14, 4))
        self._icon_lbl = tk.Label(hrow, text="", font=(SF, 18), bg=GRAY50, width=3)
        self._icon_lbl.pack(side="left")
        vrgt = frame(hrow, bg=GRAY50)
        vrgt.pack(side="left", fill="x", expand=True)
        self._title_lbl = tk.Label(vrgt, text="", font=FNB, bg=GRAY50, fg=GRAY800,
                                    anchor="w", justify="left")
        self._title_lbl.pack(fill="x")
        self._sub_lbl   = tk.Label(vrgt, text="", font=FSM, bg=GRAY50, fg=GRAY500,
                                    anchor="w", justify="left", wraplength=480)
        self._sub_lbl.pack(fill="x")
        frame(self._card, bg=GRAY50, height=14).pack()

        # ── Buttons ─────────────────────────────────────────────────
        frame(b, height=12).pack()
        btn_row = frame(b)
        btn_row.pack(padx=32, anchor="w")
        self._check_btn = SecondaryButton(btn_row, "🔄  Verifica di nuovo", self._check)
        self._check_btn.pack(side="left")
        self._dl_btn = PrimaryButton(btn_row, "⬇  Scarica HttpPlatformHandler", self._open_download)
        self._dl_btn.pack(side="left", padx=(12, 0))

        # ── Info box ─────────────────────────────────────────────────
        frame(b, height=14).pack()
        info = frame(b, bg=BLUE_BG, highlightthickness=1, highlightbackground=BLUE_BD)
        info.pack(fill="x", padx=32)
        tk.Label(info, text="Cos'è HttpPlatformHandler?", font=(SF, 9, "bold"),
                 bg=BLUE_BG, fg="#1d4ed8").pack(anchor="w", padx=14, pady=(10, 4))
        tk.Label(info,
                 text="Modulo IIS di Microsoft che avvia processi non-.NET (Python, Node.js…)\n"
                      "e fa da proxy verso la porta assegnata. Richiesto da web.config.\n"
                      "Senza di esso IIS restituisce errore 500.19.",
                 font=FSM, bg=BLUE_BG, fg="#1d4ed8", justify="left").pack(anchor="w", padx=14, pady=(0, 10))

    def on_enter(self):
        self._check()

    def _check(self):
        self._set_state("check")
        self.after(150, self._do_check)

    def _do_check(self):
        self._installed = self._is_installed()
        self._set_state("ok" if self._installed else "warn")

    def _set_state(self, state):
        states = {
            "check": (GRAY50, GRAY200, "🔍", "Verifica in corso…", "", GRAY700, GRAY500),
            "ok":    (GREEN_BG, GREEN_BD, "✅", "HttpPlatformHandler installato",
                      "Puoi procedere con l'installazione.", GREEN, "#166534"),
            "warn":  (YELLOW_BG, YELLOW_BD, "⚠", "HttpPlatformHandler NON trovato",
                      "Scarica e installa il modulo, poi clicca 'Verifica di nuovo'.",
                      YELLOW_TX, YELLOW_TX),
        }
        bg, bd, icon, title, sub, title_fg, sub_fg = states[state]
        self._card.configure(bg=bg, highlightbackground=bd)
        for w in (self._icon_lbl, self._title_lbl, self._sub_lbl):
            w.configure(bg=bg)
        for child in self._card.winfo_children():
            try: child.configure(bg=bg)
            except: pass
        self._icon_lbl.configure(text=icon)
        self._title_lbl.configure(text=title, fg=title_fg)
        self._sub_lbl.configure(text=sub, fg=sub_fg)
        if state == "ok":
            self._dl_btn.pack_forget()
        else:
            self._dl_btn.pack(side="left", padx=(12, 0))

    @staticmethod
    def _is_installed() -> bool:
        try:
            ps = ("try { $m = Get-WebGlobalModule -Name 'httpPlatformHandler' "
                  "-ErrorAction SilentlyContinue; "
                  "if ($m) { Write-Output 'INSTALLED' } else { Write-Output 'MISSING' } "
                  "} catch { Write-Output 'MISSING' }")
            r = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW)
            return "INSTALLED" in (r.stdout or "")
        except Exception:
            return False

    def _open_download(self):
        try:
            os.startfile("https://www.iis.net/downloads/microsoft/httpplatformhandler")
        except Exception:
            pass

    def validate(self):
        # Non bloccante: l'utente può continuare anche senza — verrà avvisato più tardi
        if not self._installed:
            return messagebox.askyesno(
                "HttpPlatformHandler mancante",
                "HttpPlatformHandler non risulta installato.\n\n"
                "IIS restituirà errore 500.19 finché non viene installato.\n\n"
                "Continuare comunque?")
        return True


class AdminPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Utente Amministratore",
                         "Crea il primo account admin per accedere al portale")
        self.cfg = cfg
        self._user  = tk.StringVar(value="admin")
        self._email = tk.StringVar()
        self._pwd   = tk.StringVar()
        self._pwd2  = tk.StringVar()
        self._su    = tk.BooleanVar(value=True)
        b = self.body

        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        FieldGroup(sec, "Nome utente (username)", self._user).pack(fill="x", pady=(0,10))
        FieldGroup(sec, "Email", self._email).pack(fill="x", pady=(0,10))
        self._fg_pwd  = FieldGroup(sec, "Password", self._pwd,  show="*")
        self._fg_pwd.pack(fill="x", pady=(0,10))
        self._fg_pwd2 = FieldGroup(sec, "Conferma password", self._pwd2, show="*")
        self._fg_pwd2.pack(fill="x", pady=(0,10))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=(4,12))

        chk_row = frame(sec)
        chk_row.pack(fill="x")
        tk.Checkbutton(chk_row, text="  Crea anche Django superuser  (accesso a /admin/)",
                       variable=self._su,
                       font=FN, bg="white", fg=GRAY700,
                       activebackground="white", selectcolor="white").pack(anchor="w")

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        info = frame(sec, bg=BLUE_BG, highlightthickness=1, highlightbackground=BLUE_BD)
        info.pack(fill="x")
        tk.Label(info,
                 text="Cosa viene creato durante l'installazione:",
                 font=(SF,9,"bold"), bg=BLUE_BG, fg="#1d4ed8").pack(anchor="w", padx=14, pady=(10,4))
        for item in [
            "Ruolo 'admin' nella tabella legacy ruoli",
            "Utente nella tabella legacy utenti con ruolo admin",
            "Django superuser (se selezionato) per accesso a /admin/",
        ]:
            tk.Label(info, text=f"   ·  {item}", font=FSM,
                     bg=BLUE_BG, fg="#1d4ed8").pack(anchor="w", padx=14)
        frame(info, bg=BLUE_BG, height=10).pack()

    def validate(self):
        self._fg_pwd.ok(); self._fg_pwd2.ok()
        u = self._user.get().strip()
        p = self._pwd.get()
        p2 = self._pwd2.get()
        if not u:
            return False
        if len(p) < 6:
            self._fg_pwd.err("minimo 6 caratteri")
            return False
        if p != p2:
            self._fg_pwd2.err("le password non coincidono")
            return False
        self.cfg.admin_username          = u
        self.cfg.admin_email             = self._email.get().strip()
        self.cfg.admin_password          = p
        self.cfg.admin_django_superuser  = self._su.get()
        return True


class ModulesPage(Page):
    """Step selezione moduli: quale sottoinsieme di app Django installare.

    I moduli "sistema" sono sempre obbligatori (checkbox disabilitato).
    I moduli "standard" sono pre-selezionati.
    I moduli "optional" sono disattivati per default (futuro licensing).
    La selezione viene salvata in cfg.selected_modules e usata dal migrate
    selettivo in InstallPage._run_prod / _run_dev e ReleaseRunPage._run_promote.
    """

    _TIER_LABELS = {
        "system":   ("Sistema",   "#374151", "#f3f4f6"),   # grigio
        "standard": ("Incluso",   "#1d4ed8", "#eff6ff"),   # blu
        "optional": ("Opzionale", "#92400e", "#fffbeb"),   # giallo/arancio
    }
    _TIER_HEADINGS = {
        "system":   "SISTEMA  —  sempre installati",
        "standard": "STANDARD  —  inclusi nel pacchetto base",
        "optional": "OPZIONALI  —  attivabili su richiesta",
    }

    def __init__(self, parent, cfg):
        super().__init__(parent, "Selezione Moduli",
                         "Scegli i moduli da installare nel portale")
        self.cfg = cfg
        self._vars: dict[str, tk.BooleanVar] = {}
        self._rows: dict[str, tk.Frame] = {}
        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        b = self.body

        # Barra azioni in cima
        top = frame(b, bg="white")
        top.pack(fill="x", padx=32, pady=(6, 4))
        tk.Label(top, text="Seleziona i moduli da attivare:",
                 font=(SF, 9), fg=GRAY600, bg="white").pack(side="left")
        btn_frame = frame(top, bg="white")
        btn_frame.pack(side="right")
        tk.Button(btn_frame, text="Seleziona tutto", font=FSM,
                  bg=GRAY100, fg=GRAY700, relief="flat", cursor="hand2",
                  command=self._select_all).pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="Solo default", font=FSM,
                  bg=GRAY100, fg=GRAY700, relief="flat", cursor="hand2",
                  command=self._select_defaults).pack(side="left")

        # Canvas scrollabile per la lista moduli
        outer = frame(b, bg=GRAY100, bd=1, relief="solid")
        outer.pack(fill="both", expand=True, padx=32, pady=(0, 6))
        canvas = tk.Canvas(outer, bg="white", highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = frame(canvas, bg="white")
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_resize(e):
            canvas.itemconfig(canvas_window, width=e.width)
        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_resize)

        # Scroll con rotella mouse
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Raggruppa per tier
        tier_order = ["system", "standard", "optional"]
        grouped: dict[str, list[dict]] = {t: [] for t in tier_order}
        for m in MODULE_REGISTRY:
            grouped[m["tier"]].append(m)

        for tier in tier_order:
            modules = grouped[tier]
            if not modules:
                continue

            # Intestazione sezione
            hdr = frame(inner, bg=GRAY100)
            hdr.pack(fill="x", padx=0, pady=(8, 0))
            tk.Label(hdr, text=f"  {self._TIER_HEADINGS[tier]}",
                     font=(SF, 8, "bold"), fg=GRAY500, bg=GRAY100,
                     anchor="w").pack(fill="x", padx=8, pady=3)

            for m in modules:
                self._build_row(inner, m)

        frame(inner, height=6, bg="white").pack()

        self._canvas = canvas

    def _build_row(self, parent, m: dict):
        key  = m["key"]
        tier = m["tier"]
        lbl_text, lbl_fg, lbl_bg = self._TIER_LABELS[tier]

        row = frame(parent, bg="white")
        row.pack(fill="x", padx=0, pady=0)
        self._rows[key] = row

        # Linea separatrice sottile
        sep = frame(row, bg=GRAY200, height=1)
        sep.pack(fill="x")

        content = frame(row, bg="white")
        content.pack(fill="x", padx=12, pady=5)

        # Checkbox
        initial = key in self.cfg.selected_modules
        var = tk.BooleanVar(value=initial)
        self._vars[key] = var
        cb = tk.Checkbutton(content, variable=var, bg="white",
                            activebackground="white",
                            command=lambda k=key: self._on_toggle(k))
        cb.pack(side="left", padx=(0, 4))
        if m["required"]:
            cb.configure(state="disabled")

        # Nome + descrizione
        txt_frame = frame(content, bg="white")
        txt_frame.pack(side="left", fill="x", expand=True)
        name_row = frame(txt_frame, bg="white")
        name_row.pack(fill="x")
        tk.Label(name_row, text=m["label"], font=(SF, 9, "bold"),
                 fg=GRAY800, bg="white").pack(side="left")

        # Badge tier
        badge = tk.Label(name_row, text=f" {lbl_text} ", font=(SF, 7, "bold"),
                         fg=lbl_fg, bg=lbl_bg, padx=4, pady=1, relief="flat")
        badge.pack(side="left", padx=(6, 0))

        # Dipendenze (solo se ha depends_on)
        if m.get("depends_on"):
            deps_labels = [_MODULE_BY_KEY[d]["label"] for d in m["depends_on"]
                           if d in _MODULE_BY_KEY]
            dep_txt = "richiede: " + ", ".join(deps_labels)
            tk.Label(name_row, text=dep_txt, font=(SF, 7, "italic"),
                     fg=GRAY400, bg="white").pack(side="left", padx=(8, 0))

        tk.Label(txt_frame, text=m["description"], font=(SF, 8),
                 fg=GRAY500, bg="white", anchor="w").pack(fill="x")

        # Icona migration
        mig_icon = "  DB" if m["has_migrations"] else "  —"
        mig_color = BRAND if m["has_migrations"] else GRAY400
        tk.Label(content, text=mig_icon, font=(SF, 7, "bold"),
                 fg=mig_color, bg="white", width=4).pack(side="right", padx=(4, 0))

    # ── Toggle / selezione ────────────────────────────────────────────────

    def _on_toggle(self, key: str):
        m = _MODULE_BY_KEY[key]
        enabled = self._vars[key].get()
        if enabled:
            # Quando si attiva un modulo, attiva anche le dipendenze
            for dep in m.get("depends_on", []):
                if dep in self._vars and not self._vars[dep].get():
                    self._vars[dep].set(True)
        else:
            # Quando si disattiva, disattiva anche chi dipende da questo
            for other in MODULE_REGISTRY:
                if key in other.get("depends_on", []) and other["key"] in self._vars:
                    if self._vars[other["key"]].get():
                        self._vars[other["key"]].set(False)
        self._sync_cfg()

    def _select_all(self):
        for key, var in self._vars.items():
            m = _MODULE_BY_KEY[key]
            if not m["required"]:
                var.set(True)
        self._sync_cfg()

    def _select_defaults(self):
        for key, var in self._vars.items():
            m = _MODULE_BY_KEY[key]
            if not m["required"]:
                var.set(m["default"])
        self._sync_cfg()

    def _sync_cfg(self):
        self.cfg.selected_modules = [
            key for key, var in self._vars.items() if var.get()
        ]

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_enter(self):
        # Sincronizza i checkbox con cfg (potrebbe essere cambiato da pagine precedenti)
        for key, var in self._vars.items():
            var.set(key in self.cfg.selected_modules)

    def validate(self) -> bool:
        self._sync_cfg()
        # Almeno core deve essere selezionato (è required quindi sarà sempre vero)
        if "core" not in self.cfg.selected_modules:
            messagebox.showerror("Moduli", "Il modulo Core è obbligatorio.")
            return False
        return True


class AIPage(Page):
    """Step Assistente AI: configura Ollama (chat) e il backend embeddings (RAG).

    Le chiavi OLLAMA_*/RAG_EMBED_* finiscono nel .env via Config.to_env() solo se
    il modulo 'ai_assistant' e' selezionato (altrimenti la pagina e' informativa).
    On-premise: nessun servizio cloud. Gli embeddings sono opt-in (default off).
    """

    _BACKENDS = [
        ("off", "Disattivati  —  solo ricerca testuale (BM25)",
         "RAG testuale puro, nessun embedding. Sempre funzionante, nessuna GPU.",
         (GRAY50, GRAY200, GRAY700)),
        ("ollama", "Ollama nativo",
         "Embeddings calcolati da Ollama. Richiede il pull del modello sul server.",
         (BLUE_BG, BLUE_BD, BRAND)),
        ("tei", "TEI su GPU  (consigliato)",
         "Server TEI dedicato (Docker): veloce e robusto sui corpora grandi.",
         (GREEN_BG, GREEN_BD, GREEN)),
    ]

    def __init__(self, parent, cfg):
        super().__init__(parent, "Assistente AI",
                         "Motore on-premise (Ollama) e ricerca semantica (embeddings RAG)")
        self.cfg = cfg
        self._build_ui()

    def _build_ui(self):
        wrap = frame(self.body, bg="white")
        wrap.pack(fill="both", expand=True, padx=32, pady=(8, 8))

        # Banner: mostrato in on_enter se il modulo AI non e' selezionato.
        self._banner = frame(wrap, bg=YELLOW_BG)
        self._banner.configure(highlightthickness=1, highlightbackground=YELLOW_BD)
        tk.Label(self._banner,
                 text="Il modulo «Assistente AI» non e' selezionato: questa pagina e' "
                      "informativa, le chiavi non verranno scritte nel .env.",
                 font=FSM, bg=YELLOW_BG, fg=YELLOW_TX, justify="left",
                 wraplength=560).pack(anchor="w", padx=12, pady=8)
        self._banner.pack(fill="x", pady=(0, 10))

        # --- Modello di chat (Ollama) ---
        self._anchor = tk.Label(wrap, text="MODELLO DI CHAT (OLLAMA)", font=(SF, 8, "bold"),
                                fg=GRAY500, bg="white")
        self._anchor.pack(anchor="w", pady=(2, 2))
        self._var_base = tk.StringVar(value=self.cfg.ai_base_url)
        self._var_chat = tk.StringVar(value=self.cfg.ai_chat_model)
        FieldGroup(wrap, "URL del server Ollama (OLLAMA_BASE_URL)", self._var_base,
                   mono=True).pack(fill="x", pady=(0, 6))
        FieldGroup(wrap, "Modello di chat (OLLAMA_CHAT_MODEL)", self._var_chat,
                   mono=True).pack(fill="x", pady=(0, 12))

        # --- Ricerca semantica (embeddings) ---
        tk.Label(wrap, text="RICERCA SEMANTICA (EMBEDDINGS / RAG)", font=(SF, 8, "bold"),
                 fg=GRAY500, bg="white").pack(anchor="w", pady=(2, 2))
        self._sel = CardSelector(wrap, self._BACKENDS,
                                 initial=self.cfg.ai_embed_backend,
                                 on_change=self._on_backend)
        self._sel.pack(fill="x")

        # Campi condizionali — backend Ollama
        self._frm_ollama = frame(wrap, bg="white")
        self._var_emb = tk.StringVar(value=self.cfg.ai_embed_model)
        FieldGroup(self._frm_ollama, "Modello embeddings Ollama (OLLAMA_EMBED_MODEL)",
                   self._var_emb, mono=True).pack(fill="x", pady=(6, 0))

        # Campi condizionali — backend TEI
        self._frm_tei = frame(wrap, bg="white")
        self._var_tei_base = tk.StringVar(value=self.cfg.ai_tei_base_url)
        self._var_tei_model = tk.StringVar(value=self.cfg.ai_tei_model)
        FieldGroup(self._frm_tei, "Endpoint TEI (RAG_EMBED_OPENAI_BASE_URL)",
                   self._var_tei_base, mono=True).pack(fill="x", pady=(6, 0))
        FieldGroup(self._frm_tei, "Modello TEI (RAG_EMBED_OPENAI_MODEL)",
                   self._var_tei_model, mono=True).pack(fill="x", pady=(6, 0))

        tk.Label(wrap,
                 text="On-premise: nessun dato esce dalla rete. Puoi modificare questi "
                      "valori anche dopo, dal Server Dashboard.",
                 font=FSM, fg=GRAY500, bg="white", justify="left",
                 wraplength=560).pack(anchor="w", pady=(12, 0))

        self._on_backend(self.cfg.ai_embed_backend)

    def _on_backend(self, value):
        self._frm_ollama.pack_forget()
        self._frm_tei.pack_forget()
        if value == "ollama":
            self._frm_ollama.pack(fill="x", after=self._sel)
        elif value == "tei":
            self._frm_tei.pack(fill="x", after=self._sel)

    def _sync(self):
        self.cfg.ai_base_url      = self._var_base.get().strip() or "http://127.0.0.1:11434"
        self.cfg.ai_chat_model    = self._var_chat.get().strip() or "qwen2.5:14b-instruct"
        self.cfg.ai_embed_backend = self._sel.value
        self.cfg.ai_embed_model   = self._var_emb.get().strip() or "nomic-embed-text"
        self.cfg.ai_tei_base_url  = self._var_tei_base.get().strip() or "http://127.0.0.1:8081"
        self.cfg.ai_tei_model     = self._var_tei_model.get().strip() or "BAAI/bge-m3"

    def on_enter(self):
        if "ai_assistant" in self.cfg.selected_modules:
            self._banner.pack_forget()
        else:
            self._banner.pack(fill="x", pady=(0, 10), before=self._anchor)

    def validate(self):
        backend = self._sel.value
        if backend == "tei" and (not self._var_tei_base.get().strip()
                                 or not self._var_tei_model.get().strip()):
            messagebox.showwarning("Assistente AI",
                                   "Con backend TEI servono sia l'endpoint sia il modello.")
            return False
        if backend == "ollama" and not self._var_emb.get().strip():
            messagebox.showwarning("Assistente AI",
                                   "Indica il modello di embeddings di Ollama.")
            return False
        self._sync()
        return True

    def on_leave(self):
        self._sync()


class SummaryPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Riepilogo",
                         "Verifica le impostazioni prima di avviare l'installazione")
        self.cfg = cfg
        self._txt = None
        b = self.body
        frame(b, height=6).pack()

        wrap = frame(b, bg=CODE_BG)
        wrap.pack(fill="both", expand=True, padx=32, pady=(0,0))
        sb = tk.Scrollbar(wrap); sb.pack(side="right", fill="y")
        self._txt = tk.Text(wrap, font=FMO, bg=CODE_BG, fg=CODE_FG,
                             relief="flat", state="disabled",
                             yscrollcommand=sb.set, padx=14, pady=10,
                             spacing1=2, cursor="arrow")
        self._txt.pack(fill="both", expand=True)
        sb.config(command=self._txt.yview)
        self._txt.tag_configure("h",  foreground="#58a6ff", font=("Consolas",9,"bold"))
        self._txt.tag_configure("k",  foreground="#ffd700")
        self._txt.tag_configure("v",  foreground="#7ee787")
        self._txt.tag_configure("w",  foreground="#f85149")

    def on_enter(self):
        self.cfg.generate_secret_key()
        t = self._txt
        t.configure(state="normal"); t.delete("1.0","end")

        def h(s): t.insert("end", f"\n  {s}\n", "h")
        def kv(k, v, w=False):
            t.insert("end", f"  {k:<24}", "k")
            t.insert("end", f" {v}\n", "w" if w else "v")

        h("── Ambiente ────────────────────────────────────")
        kv("Ambiente",      self.cfg.environment.upper())
        if self.cfg.environment == "test":
            kv("Seed ACL UAT", "Sì" if bool(getattr(self.cfg, "acl_seed_uat", False)) else "No")
        kv("Directory",     self.cfg.base_dir)
        kv("App Pool",      self.cfg.app_pool_name)
        url = ("https" if self.cfg.iis_https else "http") + \
              f"://{self.cfg.iis_hostname or 'localhost'}:{self.cfg.iis_port}/"
        kv("URL",           url)
        h("── Python ──────────────────────────────────────")
        kv("Eseguibile",    self.cfg.python_path)
        kv("Virtualenv",    str(self.cfg.env_path / "venv"))
        if self.cfg.package_path:
            h("── Pacchetto ────────────────────────────────────")
            kv("File",      Path(self.cfg.package_path).name)
        h("── Database ────────────────────────────────────")
        kv("Server",        self.cfg.db_host)
        kv("Database",      self.cfg.db_name)
        kv("Driver ODBC",   self.cfg.db_driver or "(auto)")
        kv("Auth", "Windows (Trusted)" if self.cfg.db_trusted else self.cfg.db_user)
        h("── Active Directory ────────────────────────────")
        if self.cfg.ldap_skip: kv("LDAP", "Non configurato", True)
        else: kv("URI", self.cfg.ldap_uri); kv("Bind DN", self.cfg.ldap_bind_dn)
        h("── IIS ─────────────────────────────────────────")
        kv("Hostname",      self.cfg.iis_hostname or "(tutti gli IP)")
        kv("Porta",         self.cfg.iis_port)
        kv("HTTPS",         "Sì" if self.cfg.iis_https else "No")
        h("── Utente Admin ────────────────────────────────")
        kv("Username",      self.cfg.admin_username)
        kv("Email",         self.cfg.admin_email or "(non impostata)")
        kv("Password",      "●" * len(self.cfg.admin_password))
        kv("Django superuser", "Sì" if self.cfg.admin_django_superuser else "No")
        h("── Moduli ───────────────────────────────────────")
        sel = getattr(self.cfg, "selected_modules", [])
        for m in MODULE_REGISTRY:
            flag = "✓" if m["key"] in sel else "—"
            color_tag = "v" if m["key"] in sel else "w"
            t.insert("end", f"  {flag}  ", color_tag)
            t.insert("end", f"{m['label']}\n", "k" if m["key"] in sel else "")
        h("── Generato ────────────────────────────────────")
        kv("SECRET_KEY",    self.cfg.secret_key[:24]+"…")
        t.insert("end", "\n")
        if not is_admin():
            t.insert("end", "  ⚠  Non stai eseguendo come Amministratore!\n", "w")
        t.configure(state="disabled")


class InstallPage(Page):
    def __init__(self, parent, cfg, on_done):
        super().__init__(parent, "Installazione in corso",
                         "Non chiudere la finestra durante il processo")
        self.cfg = cfg; self._on_done = on_done; self._started = False
        self._log_file = None; self._log_path = None
        b = self.body
        frame(b, height=8).pack()

        # Step corrente
        self._step_var = tk.StringVar(value="Inizializzazione…")
        tk.Label(b, textvariable=self._step_var,
                 font=(SF,10,"bold"), fg=BRAND, bg="white").pack(anchor="w", padx=32)

        # Progress bar custom (canvas)
        frame(b, height=6).pack()
        self._pb_frame = frame(b, bg=GRAY100, height=8)
        self._pb_frame.pack(fill="x", padx=32)
        self._pb_fill = frame(self._pb_frame, bg=BRAND, height=8)
        self._pb_fill.place(x=0, y=0, relheight=1, width=0)
        self._pb_pct = tk.StringVar(value="0%")
        tk.Label(b, textvariable=self._pb_pct, font=FSM,
                 fg=GRAY400, bg="white").pack(anchor="e", padx=32, pady=(3,8))

        # Log
        wrap = frame(b, bg=CODE_BG)
        wrap.pack(fill="both", expand=True, padx=32, pady=(0,4))
        sb = tk.Scrollbar(wrap); sb.pack(side="right", fill="y")
        self._log = tk.Text(wrap, font=FMO, bg=CODE_BG, fg=CODE_FG,
                             relief="flat", state="disabled",
                             yscrollcommand=sb.set, padx=12, pady=8, spacing1=1)
        self._log.pack(fill="both", expand=True)
        sb.config(command=self._log.yview)
        self._log.tag_configure("ok",   foreground="#7ee787")
        self._log.tag_configure("err",  foreground="#f85149")
        self._log.tag_configure("warn", foreground="#fbbf24")
        self._log.tag_configure("step", foreground="#58a6ff",
                                 font=("Consolas",9,"bold"))
        self._log.tag_configure("dim",  foreground="#484f58")

    def on_enter(self):
        if not self._started:
            self._started = True
            self._open_log_file()
            threading.Thread(target=self._run, daemon=True).start()

    def _open_log_file(self):
        try:
            if getattr(sys, 'frozen', False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).parent
            log_dir = base / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_path = log_dir / f"install_{ts}.log"
            f = open(self._log_path, "w", encoding="utf-8")
            try:
                f.write(f"Portale Novicrom — Setup Wizard\n")
                f.write(f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                f.write(f"Ambiente: {self.cfg.environment.upper()}\n")
                f.write("=" * 60 + "\n\n")
                f.flush()
            except Exception:
                f.close()
                raise
            self._log_file = f
        except Exception:
            self._log_file = None

    def _log_line(self, text, tag=""):
        # Scrivi su file
        if self._log_file:
            try:
                self._log_file.write(text + "\n")
                self._log_file.flush()
            except Exception:
                pass
        # Aggiorna GUI
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", text+"\n", tag)
            self._log.see("end")
            self._log.configure(state="disabled")
        self._log.after(0, _do)

    def _set_progress(self, pct, label=""):
        def _do():
            self._step_var.set(label or self._step_var.get())
            self._pb_pct.set(f"{pct}%")
            # Aggiorna larghezza barra proporzionalmente
            self._pb_frame.update_idletasks()
            w = self._pb_frame.winfo_width()
            self._pb_fill.place(width=int(w * pct / 100))
        self._log.after(0, _do)

    @staticmethod
    def _append_error(errors, entry):
        if entry and entry not in errors:
            errors.append(entry)

    def _resolve_python_runtime(self, cfg, errors):
        configured = probe_python_path(cfg.python_path)
        if configured and _python_version_ok(configured["version"]):
            cfg.python_path = configured["path"]
            return configured

        requested_path = (cfg.python_path or "").strip()
        if requested_path:
            if configured:
                self._log_line(
                    (
                        "  ⚠ Python configurato non supportato: "
                        f"{configured['version_text']} ({requested_path})"
                    ),
                    "warn",
                )
            else:
                self._log_line(f"  ⚠ Python configurato non valido: {requested_path}", "warn")

        detected = detect_python_info()
        if detected:
            cfg.python_path = detected["path"]
            self._log_line(
                f"  ✓ Python auto-rilevato: {detected['version_text']} ({detected['path']})",
                "ok",
            )
            return detected

        self._append_error(errors, "python")
        self._log_line(
            "  ✗ Nessun Python 3.11+ valido rilevato. Seleziona python.exe o installa Python 3.11+.",
            "err",
        )
        return None

    def _cmd(self, cmd, cwd=None, env=None):
        self._log_line(f"  $ {' '.join(str(c) for c in cmd)}", "dim")
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    tag = "err" if any(x in line.lower()
                                       for x in ("error","fatal","traceback")) else ""
                    self._log_line(f"    {line}", tag)
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            self._log_line(f"  ERRORE: {e}", "err"); return False

    def _pip_install_with_retry(self, venv_py, req_file):
        """pip install con retry per gestire errori di compilazione (es. pyodbc su Python 3.14).
        
        Pre-processing: sostituisci pyodbc==5.2.0 → pyodbc>=5.2.0 per permettere wheel precompilate su Python 3.14+.
        """
        # Leggi il requirements.txt e sostituisci pyodbc==5.2.0 → pyodbc>=5.2.0
        try:
            content = req_file.read_text(encoding="utf-8")
            if "pyodbc==5.2.0" in content:
                self._log_line("  → Adattamento pyodbc==5.2.0 → pyodbc>=5.2.0 (Python 3.14 compat)", "dim")
                content = content.replace("pyodbc==5.2.0", "pyodbc>=5.2.0")
                req_file.write_text(content, encoding="utf-8")
        except Exception as e:
            self._log_line(f"  ⚠ Errore durante la modifica requirements.txt: {e}", "warn")
        
        ok = self._cmd([str(venv_py), "-m", "pip", "install", "-r", str(req_file)])
        if ok:
            return True
        # Se fallisce, tenta con --only-binary :all: per forzare wheel precompilate
        self._log_line("  ⚠ Tentando con --only-binary :all: (solo wheel precompilate)...", "warn")
        ok = self._cmd([str(venv_py), "-m", "pip", "install", "-r", str(req_file), "--only-binary", ":all:"])
        if ok:
            return True
        # Se fallisce ancora, suggerisci Visual C++ Build Tools
        self._log_line("  ⚠ Su Windows con Python 3.12+, pyodbc richiede Microsoft Visual C++ 14.0 Build Tools:", "warn")
        self._log_line("    https://visualstudio.microsoft.com/visual-cpp-build-tools/", "warn")
        return False

    def _run_acl_bootstrap_workflow(
        self,
        *,
        venv_py,
        django_app,
        env_vars,
        settings,
        include_legacy_import=True,
        run_uat_seed=False,
    ):
        """
        Esegue il workflow ACL v2 completo:
        1) audit dry-run pre
        2) apply bootstrap
        3) audit dry-run post
        4) seed UAT opzionale (solo TEST)

        Tutte le operazioni sono non bloccanti: in caso di errore loggano warning.
        """
        self._log_line("  -> ACL v2 audit pre-migrazione (--dry-run)", "dim")
        ok_pre = self._cmd(
            [
                str(venv_py),
                "manage.py",
                "bootstrap_acl_v2",
                "--dry-run",
                f"--settings={settings}",
            ],
            cwd=django_app,
            env=env_vars,
        )
        if ok_pre:
            self._log_line("  ✓ ACL v2 dry-run pre completato", "ok")
        else:
            self._log_line("  ✗ ACL v2 dry-run pre fallito (non bloccante)", "warn")

        apply_cmd = [str(venv_py), "manage.py", "bootstrap_acl_v2"]
        if include_legacy_import:
            apply_cmd.append("--import-legacy")
        apply_cmd.extend(["--apply", f"--settings={settings}"])
        ok_apply = self._cmd(apply_cmd, cwd=django_app, env=env_vars)
        if ok_apply:
            self._log_line("  ✓ ACL v2 bootstrap apply completato", "ok")
        else:
            self._log_line("  ✗ ACL v2 bootstrap apply fallito (non bloccante)", "warn")

        self._log_line("  -> ACL v2 audit post-migrazione (--dry-run)", "dim")
        ok_post = self._cmd(
            [
                str(venv_py),
                "manage.py",
                "bootstrap_acl_v2",
                "--dry-run",
                f"--settings={settings}",
            ],
            cwd=django_app,
            env=env_vars,
        )
        if ok_post:
            self._log_line("  ✓ ACL v2 dry-run post completato", "ok")
        else:
            self._log_line("  ✗ ACL v2 dry-run post fallito (non bloccante)", "warn")

        if run_uat_seed:
            self._log_line("  -> Seed ACL v2 UAT (--reset) [solo TEST]", "dim")
            ok_seed = self._cmd(
                [
                    str(venv_py),
                    "manage.py",
                    "seed_acl_uat",
                    "--reset",
                    f"--settings={settings}",
                ],
                cwd=django_app,
                env=env_vars,
            )
            if ok_seed:
                self._log_line("  ✓ Seed ACL v2 UAT completato", "ok")
            else:
                self._log_line("  ✗ Seed ACL v2 UAT fallito (non bloccante)", "warn")

    def _run_selective_migrate(
        self,
        *,
        venv_py,
        django_app,
        env_vars,
        settings,
        selected_module_keys: list[str],
    ) -> bool:
        """Esegue migrate selettivo per i moduli scelti dall'utente.

        Strategia:
        1. Migra i built-in Django (contenttypes, auth, sessions, admin, axes).
        2. Migra i moduli "required" del MODULE_REGISTRY.
        3. Migra solo i moduli opzionali presenti in selected_module_keys.

        Django risolve le migration dependency declarations all'interno di ogni
        app_label, quindi l'ordine esplicito garantisce che le tabelle siano
        create nel giusto ordine senza dipendere da `migrate --noinput` globale.

        Ritorna True solo se TUTTI i target hanno avuto successo.
        """
        selected = set(selected_module_keys)
        all_ok = True

        # 1. Built-in Django
        for app_label in _DJANGO_BUILTIN_MIGRATE_LABELS:
            ok = self._cmd(
                [str(venv_py), "manage.py", "migrate", app_label,
                 f"--settings={settings}", "--noinput"],
                cwd=django_app, env=env_vars,
            )
            if not ok:
                self._log_line(f"  ✗ migrate {app_label} fallito", "err")
                all_ok = False

        # 2. Moduli required (sistema)
        for m in MODULE_REGISTRY:
            if not m["required"] or not m["has_migrations"]:
                continue
            ok = self._cmd(
                [str(venv_py), "manage.py", "migrate", m["app_label"],
                 f"--settings={settings}", "--noinput"],
                cwd=django_app, env=env_vars,
            )
            if ok:
                self._log_line(f"  ✓ {m['label']}", "ok")
            else:
                self._log_line(f"  ✗ migrate {m['app_label']} fallito", "err")
                all_ok = False

        # 3. Moduli opzionali selezionati
        for m in MODULE_REGISTRY:
            if m["required"] or not m["has_migrations"]:
                continue
            if m["key"] not in selected:
                self._log_line(f"  —  {m['label']} (non selezionato — skip)", "dim")
                continue
            ok = self._cmd(
                [str(venv_py), "manage.py", "migrate", m["app_label"],
                 f"--settings={settings}", "--noinput"],
                cwd=django_app, env=env_vars,
            )
            if ok:
                self._log_line(f"  ✓ {m['label']}", "ok")
            else:
                self._log_line(f"  ✗ migrate {m['app_label']} fallito", "err")
                all_ok = False

        # 4. Safety-net: applica QUALSIASI migrazione residua (app non presenti nel
        # MODULE_REGISTRY o aggiunte dopo). Senza questo, un'app in INSTALLED_APPS ma
        # assente dal registry resta senza tabelle → 500 in prod.
        ok = self._cmd(
            [str(venv_py), "manage.py", "migrate",
             f"--settings={settings}", "--noinput"],
            cwd=django_app, env=env_vars,
        )
        if ok:
            self._log_line("  ✓ migrazioni residue (safety-net globale)", "ok")
        else:
            self._log_line("  ✗ migrate globale (safety-net) fallito", "err")
            all_ok = False

        return all_ok

    def _run_assenze_tipo_alignment(
        self,
        *,
        venv_py,
        django_app,
        env_vars,
        settings,
    ) -> bool:
        """
        Riallinea il vincolo legacy SQL Server `CK_assenze_tipo` al valore canonico
        `Flessibilità` subito dopo le migration su ambienti TEST/PROD.
        """
        self._log_line("  -> Assenze SQL Server: allineamento tipo_assenza legacy", "dim")
        ok = self._cmd(
            [
                str(venv_py),
                "manage.py",
                "allinea_tipo_assenza_flessibilita",
                f"--settings={settings}",
            ],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  âœ“ CK_assenze_tipo riallineato a FlessibilitÃ ", "ok")
        else:
            self._log_line("  âœ— Riallineamento CK_assenze_tipo fallito", "err")
        return ok

    def _run_ensure_legacy_schema(self, *, venv_py, django_app, env_vars, settings) -> bool:
        self._log_line("  -> Schema legacy/runtime SQL Server", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "ensure_legacy_schema", f"--settings={settings}"],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  Schema legacy/runtime allineato", "ok")
        else:
            self._log_line("  ensure_legacy_schema fallito", "err")
        return ok

    def _run_ensure_legacy_schema(self, *, venv_py, django_app, env_vars, settings) -> bool:
        self._log_line("  -> Schema legacy/runtime SQL Server", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "ensure_legacy_schema", f"--settings={settings}"],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  Schema legacy/runtime allineato", "ok")
        else:
            self._log_line("  ensure_legacy_schema fallito", "err")
        return ok

    def _run_apply_sql_triggers(self, *, venv_py, django_app, env_vars, settings) -> bool:
        self._log_line("  -> Trigger SQL automazioni", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "apply_sql_triggers", f"--settings={settings}"],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  Trigger SQL automazioni applicati", "ok")
        else:
            self._log_line("  apply_sql_triggers fallito (non bloccante)", "warn")
        return ok

    def _run_seed_pulsanti_descrizioni(self, *, venv_py, django_app, env_vars, settings):
        """Popola le descrizioni dei pulsanti via seed. Non bloccante."""
        self._log_line("  -> Seed descrizioni pulsanti", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "seed_pulsanti_descrizioni", f"--settings={settings}"],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  ✓ Seed pulsanti descrizioni completato", "ok")
        else:
            self._log_line("  ✗ Seed pulsanti descrizioni fallito (non bloccante)", "warn")

    def _verify_collectstatic_output(self, static_root: Path, errors: list[str]) -> bool:
        missing_assets = _missing_static_assets(static_root)
        if not missing_assets:
            self._log_line("  ✓ Statici condivisi verificati", "ok")
            return True
        self._append_error(errors, "collectstatic: asset statici mancanti")
        self._log_line("  ✗ collectstatic completato ma alcuni asset attesi non esistono", "err")
        for label, path in missing_assets:
            self._log_line(f"    - {label}: {path}", "err")
        return False

    def _run(self):
        """Wrapper crash-safe: garantisce che _on_done sia sempre chiamato."""
        try:
            self._run_impl()
        except Exception as e:
            self._log_line(f"\n✗ Errore critico imprevisto: {e}", "err")
            self._log_line(traceback.format_exc(), "err")
            if self._log_file:
                try: self._log_file.close()
                except: pass
            self._log.after(800, self._on_done)

    def _run_impl(self):
        """Orchestratore: delega il flusso a _run_dev() o _run_prod() in base all'ambiente."""
        cfg      = self.cfg
        ep       = cfg.env_path
        settings = _django_settings(cfg.environment)
        errors   = []

        if cfg.environment == "dev":
            self._run_dev(cfg, ep, settings, errors)
        else:
            self._run_prod(cfg, ep, settings, errors)

        # Esponi stato finale a FinishPage (non mentire all'utente).
        # Marcatori blocking: fail di venv/pip/migrate/collectstatic = ambiente non attivabile.
        cfg.install_errors = list(errors)
        _blocking = {"venv", "pip install", "waitress", "migrate", "ensure_legacy_schema", "collectstatic",
                     "collectstatic: asset statici mancanti"}
        cfg.install_blocking = [e for e in errors if e in _blocking]
        cfg.install_success = not errors

        if cfg.install_blocking:
            self._set_progress(100, "Installazione INCOMPLETA — release non attivata")
        elif errors:
            self._set_progress(100, "Installazione completata con avvisi")
        else:
            self._set_progress(100, "Installazione completata!")
        self._log_line("\n" + "─"*50, "step")
        if cfg.install_blocking:
            self._log_line(
                f"  ⚠ {len(cfg.install_blocking)} errori bloccanti — release NON attivata:", "err")
            for e in cfg.install_blocking:
                self._log_line(f"  · {e}", "err")
            other = [e for e in errors if e not in _blocking]
            if other:
                self._log_line(f"  Altri {len(other)} avvisi non bloccanti:", "warn")
                for e in other:
                    self._log_line(f"  · {e}", "warn")
        elif errors:
            self._log_line(f"  Completato con {len(errors)} avvisi:", "warn")
            for e in errors: self._log_line(f"  · {e}", "warn")
        else:
            self._log_line("  Tutto completato senza errori!", "ok")
        self._log_line("─"*50, "step")
        if self._log_path:
            self._log_line(f"  Log salvato in: {self._log_path}", "dim")
        if self._log_file:
            try: self._log_file.close()
            except: pass
        self._log.after(800, self._on_done)

    # ── Flusso DEV (7 step) ──────────────────────────────────────────────────

    def _run_dev(self, cfg, ep, settings, errors):
        """Installa/aggiorna l'ambiente di sviluppo (SQLite, nessun IIS)."""
        N = 7   # Estrai/Verifica, Venv, .env, pip, migrate, Admin, Avvio

        if getattr(sys, "frozen", False):
            dev_install_dir = Path(cfg.base_dir) / "dev" / "source"
            dev_src         = dev_install_dir
            django_app      = dev_install_dir / "django_app"
        else:
            dev_src    = Path(cfg.dev_source)
            django_app = dev_src / "django_app"
        venv_dir = dev_src / ".venv"
        venv_py  = venv_dir / "Scripts" / "python.exe"

        def step(n, title, pct):
            self._set_progress(pct, f"[{n}/{N}] {title}")
            self._log_line(f"\n── {title} {'─'*(44-len(title))}", "step")

        python_info = self._resolve_python_runtime(cfg, errors)

        # 1. Estrazione / verifica sorgente
        if getattr(sys, "frozen", False):
            step(1, "Estrazione sorgente (bundled)", 5)
            bundled = Path(sys._MEIPASS) / "_bundled_src" / "django_app"
            try:
                dev_install_dir.mkdir(parents=True, exist_ok=True)
                self._log_line(f"  Copia sorgente in {dev_install_dir} ...", "ok")
                shutil.copytree(str(bundled), str(django_app), dirs_exist_ok=True)
                self._log_line(f"  ✓ Sorgente estratto in {dev_install_dir}", "ok")
            except Exception as e:
                self._log_line(f"  ✗ {e}", "err"); errors.append(str(e))
        else:
            step(1, "Verifica cartella sorgente", 5)
            if not django_app.exists():
                self._log_line(f"  ✗ django_app non trovata in {dev_src}", "err")
                errors.append("sorgente mancante")
            else:
                self._log_line(f"  ✓ Sorgente: {dev_src}", "ok")
                self._log_line(f"  ✓ django_app: {django_app}", "ok")

        # 2. Virtualenv
        step(2, "Creazione virtualenv (.venv)", 15)
        if python_info is None:
            venv_ready = False
            self._append_error(errors, "venv")
            self._log_line("  Skip — nessun Python 3.11+ disponibile per creare il virtualenv", "warn")
        elif not venv_py.exists():
            ok = self._cmd([cfg.python_path, "-m", "venv", str(venv_dir)])
            venv_ready = ok and venv_py.exists()
            if venv_ready:
                self._log_line("  ✓ Virtualenv .venv creato", "ok")
            else:
                self._append_error(errors, "venv")
                self._log_line("  ✗ Virtualenv .venv non disponibile", "err")
        else:
            venv_ready = True
            self._log_line("  ✓ Virtualenv .venv esistente", "ok")
        if venv_ready:
            ok = self._cmd([str(venv_py), "-m", "pip", "install", "--upgrade",
                            "pip", "setuptools", "wheel"])
            if ok:
                self._log_line("  ✓ pip aggiornato", "ok")
            else:
                self._append_error(errors, "pip upgrade")
                self._log_line("  ✗ Aggiornamento pip fallito", "err")
        else:
            self._log_line("  Skip — pip non aggiornato (venv non disponibile)", "warn")

        # 3. .env
        step(3, "Scrittura .env DEV", 30)
        module_versions_block = "\n".join(_module_version_lines(APP_VERSION))
        env_content = (
            f"DJANGO_SECRET_KEY={cfg.secret_key}\n"
            f"DEBUG=True\n"
            f"ALLOWED_HOSTS=*\n"
            f"APP_VERSION={APP_VERSION}\n"
            f"{module_versions_block}\n"
            f"ENVIRONMENT=dev\n"
        )
        try:
            env_file = django_app / ".env"
            env_file.write_text(env_content, encoding="utf-8")
            self._log_line(f"  ✓ .env → {env_file}", "ok")
        except Exception as e:
            errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")

        # 4. pip install
        step(4, "Installazione dipendenze pip", 45)
        req = django_app / "requirements.txt"
        deps_ready = venv_ready
        if not venv_ready:
            deps_ready = False
            self._log_line("  Skip — venv non disponibile", "warn")
        elif req.exists():
            ok = self._pip_install_with_retry(venv_py, req)
            if ok:
                self._log_line("  ✓ Dipendenze installate", "ok")
            else:
                deps_ready = False
                self._append_error(errors, "pip install")
                self._log_line("  ✗ pip fallito", "err")
        else:
            deps_ready = False
            self._log_line("  requirements.txt non trovato — skip", "warn")

        # 5. migrate selettivo (DEV usa SQLite — migrate tutto per semplicità)
        step(5, "Django migrate (SQLite dev)", 60)
        env_vars = {**os.environ, "DJANGO_SETTINGS_MODULE": settings,
                    "PYTHONPATH": str(django_app),
                    "PORTAL_SKIP_RUNTIME_BOOTSTRAP": "1"}
        if not deps_ready:
            self._log_line("  Skip — dipendenze Python non disponibili", "warn")
        elif (django_app / "manage.py").exists():
            selected = getattr(cfg, "selected_modules",
                               [m["key"] for m in MODULE_REGISTRY])
            ok = self._run_selective_migrate(
                venv_py=venv_py, django_app=django_app,
                env_vars=env_vars, settings=settings,
                selected_module_keys=selected,
            )
            if ok:
                self._log_line("  ✓ migrate completato", "ok")
                self._run_acl_bootstrap_workflow(
                    venv_py=venv_py,
                    django_app=django_app,
                    env_vars=env_vars,
                    settings=settings,
                    include_legacy_import=True,
                    run_uat_seed=bool(getattr(cfg, "acl_seed_uat", True) and cfg.environment == "test"),
                )
            else:
                self._append_error(errors, "migrate")
                self._log_line("  ✗ migrate fallito (vedi dettagli sopra)", "err")
        else:
            self._log_line("  manage.py non trovato — skip", "warn")

        # 6. Admin
        step(6, "Creazione utente amministratore", 78)
        if not deps_ready:
            self._log_line("  Skip — ambiente Python non pronto", "warn")
        elif cfg.admin_username and cfg.admin_password and (django_app / "manage.py").exists():
            self._create_legacy_admin(cfg, venv_py, django_app, env_vars, settings)
        else:
            self._log_line("  Skip — nessun admin configurato", "warn")

        # 7. Istruzioni avvio
        step(7, "Configurazione completata", 95)
        self._log_line("  ✓ Ambiente DEV pronto!", "ok")
        self._log_line(f"  Attiva il venv:", "ok")
        self._log_line(f"    {venv_dir}\\Scripts\\Activate.ps1", "dim")
        self._log_line(f"  Avvia il server:", "ok")
        self._log_line(f"    python manage.py runserver --settings=config.settings.dev", "dim")
        self._log_line(f"  (dalla cartella {django_app})", "dim")

    # ── Flusso TEST / PROD (11 step) ─────────────────────────────────────────

    def _run_prod(self, cfg, ep, settings, errors):
        """Installa/aggiorna l'ambiente TEST o PROD (SQL Server, IIS)."""
        N = 12
        tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        cfg.release_tag = tag
        rel_dir    = ep / "releases" / tag
        django_app = rel_dir / "django_app"
        venv_dir   = ep / "venv"
        venv_py    = venv_dir / "Scripts" / "python.exe"

        def step(n, title, pct):
            self._set_progress(pct, f"[{n}/{N}] {title}")
            self._log_line(f"\n── {title} {'─'*(44-len(title))}", "step")

        python_info = self._resolve_python_runtime(cfg, errors)

        # 1. Directory
        step(1, "Creazione struttura directory", 5)
        for d in [ep/"releases", ep/"logs", ep/"config", ep/"static",
                  ep/"media", ep/"run",
                  Path(cfg.base_dir)/"shared"/"packages",
                  Path(cfg.base_dir)/"shared"/"backups",
                  Path(cfg.base_dir)/"shared"/"scripts"]:
            try:
                d.mkdir(parents=True, exist_ok=True)
                self._log_line(f"  ✓ {d}", "ok")
            except Exception as e:
                self._log_line(f"  ✗ {d}: {e}", "err"); errors.append(str(e))

        # 2. Copia script PS
        step(2, "Copia script deployment", 12)
        if getattr(sys, "frozen", False):
            src = Path(sys._MEIPASS) / "scripts"
        else:
            src = Path(__file__).parent / "scripts"
        dst = Path(cfg.base_dir) / "shared" / "scripts"
        if src.exists():
            for f in src.glob("*.ps1"):
                try: shutil.copy2(f, dst/f.name); self._log_line(f"  ✓ {f.name}", "ok")
                except Exception as e: self._log_line(f"  Avviso: {e}", "warn")
        else: self._log_line("  Scripts non trovati — skip", "warn")

        # 3. Virtualenv
        step(3, "Creazione virtualenv", 20)
        if python_info is None:
            venv_ready = False
            self._append_error(errors, "venv")
            self._log_line("  Skip — nessun Python 3.11+ disponibile per creare il virtualenv", "warn")
        elif not venv_py.exists():
            ok = self._cmd([cfg.python_path, "-m", "venv", str(venv_dir)])
            venv_ready = ok and venv_py.exists()
            if venv_ready:
                self._log_line("  ✓ Virtualenv creato", "ok")
            else:
                self._append_error(errors, "venv")
                self._log_line("  ✗ Virtualenv non disponibile", "err")
        else:
            venv_ready = True
            self._log_line("  ✓ Virtualenv esistente", "ok")
        if venv_ready:
            ok = self._cmd([str(venv_py), "-m", "pip", "install", "--upgrade",
                            "pip", "setuptools", "wheel"])
            if ok:
                self._log_line("  ✓ pip aggiornato", "ok")
            else:
                self._append_error(errors, "pip upgrade")
                self._log_line("  ✗ Aggiornamento pip fallito", "err")
        else:
            self._log_line("  Skip — pip non aggiornato (venv non disponibile)", "warn")

        # 4. Estrazione
        step(4, "Estrazione pacchetto release", 30)
        if cfg.package_path and Path(cfg.package_path).exists():
            try:
                rel_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(cfg.package_path, "r") as zf:
                    zf.extractall(rel_dir)
                self._log_line(f"  ✓ Estratto in {rel_dir}", "ok")
            except Exception as e:
                self._log_line(f"  ✗ {e}", "err"); errors.append(str(e))
        else:
            existing = sorted((ep/"releases").iterdir(), reverse=True) \
                       if (ep/"releases").exists() else []
            candidates = [x for x in existing if x != rel_dir]
            if candidates:
                rel_dir = candidates[0]; django_app = rel_dir/"django_app"
                self._log_line(f"  ✓ Release esistente: {rel_dir.name}", "ok")
            else:
                self._log_line("  ✗ Nessun pacchetto disponibile", "err")
                errors.append("Nessun pacchetto")

        # 5. .env
        step(5, "Configurazione .env", 40)
        backup_dir_path = Path(cfg.base_dir) / "shared" / "backups" / cfg.environment
        env_cfg_file = ep / "config" / ".env"
        if env_cfg_file.exists():
            # .env già presente — non sovrascrivere, preserva le modifiche manuali
            env_content = env_cfg_file.read_text(encoding="utf-8")
            self._log_line(f"  ✓ .env esistente mantenuto (non sovrascritto): {env_cfg_file}", "ok")
        else:
            # Prima installazione: genera .env dai parametri wizard
            env_content = cfg.to_env()
            try:
                env_cfg_file.parent.mkdir(parents=True, exist_ok=True)
                env_cfg_file.write_text(env_content, encoding="utf-8")
                self._log_line(f"  ✓ .env creato: {env_cfg_file}", "ok")
            except Exception as e:
                errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")
        # Riallinea DB_DRIVER se il driver nel .env non è installato sul server applicativo
        env_content, driver_note = _realign_db_driver_in_env(env_content)
        if driver_note:
            self._log_line(driver_note, "warn")
            try:
                env_cfg_file.write_text(env_content, encoding="utf-8")
            except Exception:
                pass
        # Aggiunge variabili backup solo se mancanti nel .env (sia nuovo che esistente)
        env_keys = {
            line.split("=", 1)[0].strip()
            for line in env_content.splitlines()
            if line.strip() and not line.strip().startswith("#") and "=" in line
        }
        backup_lines = []
        if "BACKUP_DIR" not in env_keys:
            backup_lines.append(f"BACKUP_DIR={backup_dir_path}")
        if "BACKUP_RETENTION" not in env_keys:
            backup_lines.append("BACKUP_RETENTION=10")
        if backup_lines:
            env_content += f"\n# Backup automatico\n{'\n'.join(backup_lines)}\n"
            try:
                env_cfg_file.write_text(env_content, encoding="utf-8")
                self._log_line(f"  ✓ Variabili backup aggiunte al .env", "ok")
            except: pass
        if django_app.exists():
            try:
                (django_app/".env").write_text(env_content, encoding="utf-8")
                self._log_line(f"  ✓ .env copiato nel release", "ok")
            except: pass

        # 6. pip install
        step(6, "Installazione dipendenze pip", 52)
        req = django_app/"requirements.txt"
        env_vars = {**os.environ, "DJANGO_SETTINGS_MODULE": settings,
                    "PYTHONPATH": str(django_app),
                    "STATIC_ROOT": str(ep / "static"),
                    "MEDIA_ROOT":  str(ep / "media"),
                    "PORTAL_SKIP_RUNTIME_BOOTSTRAP": "1"}
        deps_ready = venv_ready
        if not venv_ready:
            deps_ready = False
            self._log_line("  Skip — venv non disponibile", "warn")
        elif req.exists():
            ok = self._pip_install_with_retry(venv_py, req)
            if ok:
                self._log_line("  ✓ Dipendenze installate", "ok")
            else:
                deps_ready = False
                self._append_error(errors, "pip install")
                self._log_line("  ✗ pip fallito", "err")
        else:
            deps_ready = False
            self._log_line("  requirements.txt non trovato — skip", "warn")
        waitress_ready = deps_ready
        if deps_ready:
            self._log_line("  → Verifica waitress (WSGI server per IIS)…", "dim")
            ok_waitress = self._cmd([str(venv_py), "-m", "pip", "install", "waitress", "--quiet"])
            if ok_waitress:
                self._log_line("  ✓ waitress disponibile", "ok")
            else:
                waitress_ready = False
                self._append_error(errors, "waitress")
                self._log_line("  ✗ waitress non disponibile", "err")
        else:
            waitress_ready = False
            self._log_line("  Skip — verifica waitress non eseguita", "warn")

        # 7. collectstatic
        step(7, "collectstatic", 65)
        collectstatic_ok = False
        if not waitress_ready:
            self._log_line("  Skip — dipendenze Python non disponibili", "warn")
        elif django_app.exists() and (django_app/"manage.py").exists():
            ok = self._cmd([str(venv_py),"manage.py","collectstatic",
                            "--noinput","--clear",f"--settings={settings}"],
                           cwd=django_app, env=env_vars)
            if ok:
                collectstatic_ok = self._verify_collectstatic_output(ep / "static", errors)
            else:
                self._append_error(errors, "collectstatic")
                self._log_line("  ✗ collectstatic fallito", "err")
        else:
            self._log_line("  manage.py non trovato — skip", "warn")

        # 8. migrate selettivo per modulo
        step(8, "Django migrate", 75)
        migrate_ok = False
        database_ready = True
        if cfg.db_trusted or cfg.db_user:
            database_ready = self._create_sql_database(cfg)
            if not database_ready:
                self._append_error(errors, "database access")
                self._log_line("  ✗ Database non pronto: migrate saltato", "err")
        if database_ready and cfg.db_trusted:
            self._configure_sql_login(cfg)
        if not database_ready:
            self._log_line("  Skip — database SQL Server non accessibile", "warn")
        elif not waitress_ready:
            self._log_line("  Skip — dipendenze Python non disponibili", "warn")
        elif django_app.exists() and (django_app/"manage.py").exists():
            selected = getattr(cfg, "selected_modules",
                               [m["key"] for m in MODULE_REGISTRY])
            self._log_line(
                f"  Moduli selezionati: {', '.join(selected)}", "dim")
            ok = self._run_selective_migrate(
                venv_py=venv_py, django_app=django_app,
                env_vars=env_vars, settings=settings,
                selected_module_keys=selected,
            )
            if ok:
                migrate_ok = True
                self._log_line("  ✓ migrate completato", "ok")
            else:
                self._append_error(errors, "migrate")
                self._log_line("  ✗ migrate fallito (verifica DB e log sopra)", "err")
            if ok:
                ok_schema = self._run_ensure_legacy_schema(
                    venv_py=venv_py,
                    django_app=django_app,
                    env_vars=env_vars,
                    settings=settings,
                )
                if not ok_schema:
                    self._append_error(errors, "ensure_legacy_schema")
                    migrate_ok = False
                else:
                    ok_triggers = self._run_apply_sql_triggers(
                        venv_py=venv_py,
                        django_app=django_app,
                        env_vars=env_vars,
                        settings=settings,
                    )
                    if not ok_triggers:
                        self._append_error(errors, "apply_sql_triggers")
                    ok_align = self._run_assenze_tipo_alignment(
                        venv_py=venv_py,
                        django_app=django_app,
                        env_vars=env_vars,
                        settings=settings,
                    )
                    if not ok_align:
                        self._append_error(errors, "allinea_tipo_assenza_flessibilita")
            ok_cc = self._cmd([str(venv_py),"manage.py","createcachetable",
                               f"--settings={settings}"], cwd=django_app, env=env_vars)
            if ok_cc:
                self._log_line("  ✓ createcachetable completato", "ok")
            else:
                self._append_error(errors, "createcachetable")
                self._log_line("  ✗ createcachetable fallito", "warn")
            if migrate_ok:
                self._run_acl_bootstrap_workflow(
                    venv_py=venv_py,
                    django_app=django_app,
                    env_vars=env_vars,
                    settings=settings,
                    include_legacy_import=True,
                    run_uat_seed=bool(getattr(cfg, "acl_seed_uat", True) and cfg.environment == "test"),
                )
            if migrate_ok:
                self._run_seed_pulsanti_descrizioni(
                    venv_py=venv_py,
                    django_app=django_app,
                    env_vars=env_vars,
                    settings=settings,
                )
        else:
            self._log_line("  Skip — django_app non trovato", "warn")

        # 9. Admin
        step(9, "Creazione utente amministratore", 80)
        if not migrate_ok:
            self._log_line("  Skip — migrate non completato", "warn")
        elif cfg.admin_username and cfg.admin_password and django_app.exists():
            self._create_legacy_admin(cfg, venv_py, django_app, env_vars, settings)
        elif not django_app.exists():
            self._log_line("  Skip — nessun package estratto", "warn")
        else:
            self._log_line("  Skip — nessun admin configurato", "warn")

        # 10. Junction current
        step(10, "Attivazione release", 87)
        cur = ep/"current"
        can_activate = rel_dir.exists() and waitress_ready and collectstatic_ok and migrate_ok
        activated_release = False
        if not rel_dir.exists():
            self._log_line("  Skip — nessuna release da attivare", "warn")
        elif not can_activate:
            self._log_line("  Skip — release non attivata per errori nei passaggi precedenti", "warn")
        else:
            try:
                _create_junction(cur, rel_dir)
                activated_release = True
                self._log_line(f"  ✓ current → {rel_dir.name}", "ok")
            except Exception as e:
                self._log_line(f"  ✗ Junction: {e}", "err")
                self._append_error(errors, str(e))

        # 11. IIS
        step(11, "Configurazione IIS", 94)
        if not activated_release:
            self._log_line("  Skip — IIS non aggiornato per evitare di puntare a una release incompleta", "warn")
        else:
            self._check_httpplatformhandler()
            self._write_webconfig(ep, cfg)
            self._log_line("  ✓ web.config scritto", "ok")
            self._configure_iis(cfg)

        # 12. Backup automatico schedulato
        step(12, "Pianificazione backup automatico", 98)
        backup_dir_path = Path(cfg.base_dir) / "shared" / "backups" / cfg.environment
        if not activated_release:
            self._log_line("  Skip — backup schedulato non registrato (release non attivata)", "warn")
        else:
            self._setup_scheduled_backup(cfg, ep, venv_py, settings, backup_dir_path)

    # ── Helper condiviso tra DEV e PROD ──────────────────────────────────────

    def _setup_scheduled_backup(self, cfg, ep, venv_py, settings_module, backup_dir):
        """Registra un Windows Scheduled Task per il backup giornaliero alle 02:00."""
        env_upper = cfg.environment.upper()
        task_name = f"PortaleNovicrom-Backup-{env_upper}"
        # Il task usa sempre current/ per puntare sempre alla release attiva
        django_app_path = ep / "current" / "django_app"
        task_name_ps = _ps_escape(task_name)
        py = _ps_escape(str(venv_py))
        wd = _ps_escape(str(django_app_path))
        bak = _ps_escape(str(backup_dir))
        ps = f"""
$taskName = "{task_name_ps}"
$pyExe    = "{py}"
$workDir  = "{wd}"
$cmdArgs  = "manage.py backup_portale --settings={settings_module}"
$backupDir = "{bak}"

# Crea directory backup se non esiste
if (-not (Test-Path $backupDir)) {{ New-Item -ItemType Directory -Path $backupDir -Force | Out-Null }}

$action   = New-ScheduledTaskAction -Execute $pyExe -Argument $cmdArgs -WorkingDirectory $workDir
$trigger  = New-ScheduledTaskTrigger -Daily -At '02:00'
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "OK $taskName"
"""
        try:
            r = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode == 0 and "OK" in r.stdout:
                self._log_line(f"  ✓ Task '{task_name}' — backup giornaliero alle 02:00", "ok")
                self._log_line(f"  ✓ Salva in: {backup_dir}", "ok")
            else:
                out = (r.stderr or r.stdout)[:300].strip()
                self._log_line(f"  ⚠ Task Scheduler: {out}", "warn")
                self._log_line(
                    f"  → Per pianificarlo manualmente:\n"
                    f"    schtasks /create /tn \"{task_name}\" /tr "
                    f"\"cmd /c cd /d \\\"{django_app_path}\\\" && \\\"{venv_py}\\\" manage.py backup_portale --settings={settings_module}\" "
                    f"/sc DAILY /st 02:00 /rl HIGHEST /f",
                    "warn")
        except Exception as e:
            self._log_line(f"  ⚠ Task Scheduler: {e}", "warn")

    def _create_legacy_admin(self, cfg, venv_py, django_app, env_vars, settings):
        """Crea l'utente admin legacy (e opzionalmente il Django superuser)."""
        admin_script = (
            "import django, os; "
            f"os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{settings}'); "
            "django.setup(); "
            "from core.legacy_models import Ruolo, UtenteLegacy; "
            "from werkzeug.security import generate_password_hash; "
            f"r, _ = Ruolo.objects.get_or_create(nome='admin'); "
            f"u, created = UtenteLegacy.objects.get_or_create("
            f"    nome={repr(cfg.admin_username)},"
            f"    defaults=dict("
            f"        email={repr(cfg.admin_email)},"
            f"        password=generate_password_hash({repr(cfg.admin_password)}),"
            f"        ruolo_id=r.id, attivo=True));"
            f"u.ruolo_id = r.id; u.attivo = True; u.save(); "
            "print('OK legacy admin:', u.nome, '— creato=' + str(created))"
        )
        ok = self._cmd([str(venv_py), "-c", admin_script], cwd=django_app, env=env_vars)
        if ok: self._log_line("  ✓ Utente admin legacy creato", "ok")
        else:  self._log_line("  ✗ Creazione utente legacy fallita (forse esiste già)", "warn")
        if cfg.admin_django_superuser:
            su_env = {**env_vars, "DJANGO_SUPERUSER_PASSWORD": cfg.admin_password}
            ok2 = self._cmd(
                [str(venv_py), "manage.py", "createsuperuser",
                 "--noinput",
                 f"--username={cfg.admin_username}",
                 f"--email={cfg.admin_email or 'admin@localhost'}",
                 f"--settings={settings}"],
                cwd=django_app, env=su_env)
            if ok2: self._log_line("  ✓ Django superuser creato", "ok")
            else:   self._log_line("  ✗ Django superuser fallito (forse esiste già)", "warn")


    def _check_httpplatformhandler(self):
        """Verifica e installa HttpPlatformHandler IIS se mancante."""
        ps_check = (
            "try {"
            "  $m = Get-WebGlobalModule -Name 'httpPlatformHandler' -ErrorAction SilentlyContinue; "
            "  if ($m) { Write-Output 'INSTALLED' } else { Write-Output 'MISSING' }"
            "} catch { Write-Output 'MISSING' }"
        )
        try:
            r = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_check],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
            status = (r.stdout or "").strip()
        except Exception:
            status = "UNKNOWN"

        if status == "INSTALLED":
            self._log_line("  ✓ HttpPlatformHandler IIS presente", "ok")
            return

        self._log_line("  ⚠ HttpPlatformHandler non trovato — tentativo installazione…", "warn")
        # Prova WebPI (Web Platform Installer) CLI
        webpicmd = r"C:\Program Files\Microsoft\Web Platform Installer\WebpiCmd-x64.exe"
        if Path(webpicmd).exists():
            try:
                r = subprocess.run(
                    [webpicmd, "/Install", "/Products:HttpPlatformHandler",
                     "/AcceptEula", "/SuppressReboot"],
                    capture_output=True, text=True, timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode == 0:
                    self._log_line("  ✓ HttpPlatformHandler installato via WebPI", "ok")
                    return
            except Exception:
                pass

        # Istruzioni manuali
        self._log_line(
            "  ⚠ Installare manualmente HttpPlatformHandler:\n"
            "    1. Aprire IIS Manager → Get New Web Platform Components\n"
            "    2. Cercare 'HttpPlatformHandler' e installare\n"
            "    oppure: scaricare da https://www.iis.net/downloads/microsoft/httpplatformhandler\n"
            "    Senza questo modulo, IIS mostrerà errore 500.19", "warn")

    def _write_webconfig(self, ep, cfg):
        venv = ep/"venv"; logs = ep/"logs"
        app  = ep/"current"/"django_app"
        settings = _django_settings(cfg.environment)
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <handlers>
      <add name="httpPlatformHandler" path="*" verb="*"
           modules="httpPlatformHandler" resourceType="Unspecified" requireAccess="Script" />
    </handlers>
    <httpPlatform processPath="{venv}\\Scripts\\python.exe"
        arguments="-m waitress --port=%HTTP_PLATFORM_PORT% --threads=8 config.wsgi:application"
        stdoutLogEnabled="true" stdoutLogFile="{logs}\\waitress_stdout.log"
        startupTimeLimit="120" startupRetryCount="3" requestTimeout="00:04:00">
      <environmentVariables>
        <environmentVariable name="DJANGO_SETTINGS_MODULE" value="{settings}" />
        <environmentVariable name="PYTHONPATH" value="{app}" />
        <environmentVariable name="PYTHONUNBUFFERED" value="1" />
        <environmentVariable name="HTTP_X_FORWARDED_PROTO" value="https" />
      </environmentVariables>
    </httpPlatform>
  </system.webServer>
  <location path="static">
    <system.webServer>
      <handlers><clear /><add name="SF" path="*" verb="GET,HEAD"
          modules="StaticFileModule,DefaultDocumentModule" resourceType="Either" /></handlers>
      <staticContent><clientCache cacheControlMode="UseMaxAge" cacheControlMaxAge="7.00:00:00"/></staticContent>
    </system.webServer>
  </location>
  <location path="media">
    <system.webServer>
      <handlers><clear /><add name="MF" path="*" verb="GET,HEAD"
          modules="StaticFileModule" resourceType="File" /></handlers>
    </system.webServer>
  </location>
</configuration>"""
        (ep/"web.config").write_text(xml, encoding="utf-8")

    def _find_sqlcmd(self):
        for candidate in [
            r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\160\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\150\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\140\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\130\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\120\Tools\Binn\SQLCMD.EXE",
            r"C:\Program Files\Microsoft SQL Server\110\Tools\Binn\SQLCMD.EXE",
        ]:
            if Path(candidate).exists():
                return candidate
        return "sqlcmd"  # fallback al PATH

    def _sqlcmd_auth_args(self, cfg):
        """Restituisce gli argomenti di autenticazione per sqlcmd."""
        if cfg.db_trusted:
            return ["-E"]
        return ["-U", cfg.db_user, "-P", cfg.db_password]

    def _sqlcmd_tls_args(self, cfg):
        """Restituisce gli argomenti TLS per sqlcmd coerenti con DB_TRUST_CERT."""
        if bool(getattr(cfg, "db_trust_cert", True)):
            return ["-C"]
        return []

    def _current_windows_account(self):
        domain = os.environ.get("USERDOMAIN", "").strip()
        user = os.environ.get("USERNAME", "").strip()
        if domain and user:
            return f"{domain}\\{user}"
        return user or "ACCOUNT_WINDOWS"

    def _log_sql_database_access_hint(self, cfg, db):
        db_bracket = _sql_bracket_escape(db)
        if cfg.db_trusted:
            account = self._current_windows_account()
            account_sql = _sql_string_escape(account)
            account_bracket = _sql_bracket_escape(account)
            self._log_line(
                "  -> Rimedi SSMS (Windows Auth):\n"
                f"    USE [master];\n"
                f"    IF DB_ID(N'{_sql_string_escape(db)}') IS NULL CREATE DATABASE [{db_bracket}];\n"
                f"    GO\n"
                f"    USE [master];\n"
                f"    IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{account_sql}') CREATE LOGIN [{account_bracket}] FROM WINDOWS;\n"
                f"    GO\n"
                f"    USE [{db_bracket}];\n"
                f"    IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{account_sql}') CREATE USER [{account_bracket}] FOR LOGIN [{account_bracket}];\n"
                f"    ALTER ROLE db_owner ADD MEMBER [{account_bracket}];",
                "warn",
            )
        else:
            self._log_line(
                f"  -> Verificare in SSMS che il login SQL configurato sia db_owner su [{db_bracket}].",
                "warn",
            )

    def _check_sql_database_access(self, cfg, db):
        ok, err = _try_db_connection(
            cfg.db_driver or _preferred_sql_server_odbc_driver() or "ODBC Driver 18 for SQL Server",
            cfg.db_host or "localhost",
            cfg.db_user,
            cfg.db_password,
            cfg.db_trusted,
            bool(getattr(cfg, "db_trust_cert", True)),
            database=db,
        )
        if ok:
            self._log_line(f"  ✓ Connessione al database [{db}] verificata", "ok")
            return True
        self._log_line(f"  ✗ Connessione al database [{db}] fallita: {err[:500]}", "err")
        self._log_sql_database_access_hint(cfg, db)
        return False

    def _create_sql_database_via_odbc(self, cfg, db):
        if _pyodbc_module is None:
            self._log_line("  ✗ pyodbc non disponibile: impossibile creare il database senza sqlcmd", "err")
            return False

        driver = cfg.db_driver or _preferred_sql_server_odbc_driver() or "ODBC Driver 18 for SQL Server"
        server = cfg.db_host or "localhost"
        tc = "yes" if bool(getattr(cfg, "db_trust_cert", True)) else "no"
        if cfg.db_trusted:
            cs = (
                f"DRIVER={{{driver}}};SERVER={server};DATABASE=master;"
                f"Trusted_Connection=yes;Connection Timeout=5;TrustServerCertificate={tc}"
            )
        else:
            cs = (
                f"DRIVER={{{driver}}};SERVER={server};DATABASE=master;"
                f"UID={cfg.db_user};PWD={cfg.db_password};Connection Timeout=5;TrustServerCertificate={tc}"
            )

        db_bracket = _sql_bracket_escape(db)
        db_quoted = _sql_string_escape(db)
        sql = (
            f"IF DB_ID(N'{db_quoted}') IS NULL "
            f"BEGIN EXEC(N'CREATE DATABASE [{db_bracket}]') END"
        )
        try:
            conn = _pyodbc_module.connect(cs, autocommit=True, timeout=5)
            try:
                cursor = conn.cursor()
                cursor.execute(sql)
                cursor.close()
            finally:
                conn.close()
            self._log_line(f"  ✓ Database [{db}] creato/verificato via ODBC", "ok")
            return self._check_sql_database_access(cfg, db)
        except Exception as exc:
            self._log_line(f"  ✗ Creazione DB via ODBC fallita: {str(exc)[:500]}", "err")
            self._log_sql_database_access_hint(cfg, db)
            return False

    def _create_sql_database(self, cfg):
        """Crea il database SQL Server se non esiste e verifica l'accesso."""
        server = cfg.db_host or "localhost"
        try:
            db = _validate_sql_identifier(cfg.db_name)
        except ValueError as e:
            self._log_line(f"  ✗ {e}", "err")
            return False
        db_bracket = _sql_bracket_escape(db)
        db_quoted  = _sql_string_escape(db)
        create_sql = (
            f"IF DB_ID(N'{db_quoted}') IS NULL "
            f"BEGIN EXEC(N'CREATE DATABASE [{db_bracket}]') END"
        )
        verify_sql = "SELECT 1 AS database_access_ok;"
        sqlcmd = self._find_sqlcmd()
        auth   = self._sqlcmd_auth_args(cfg)
        tls    = self._sqlcmd_tls_args(cfg)
        try:
            create_result = subprocess.run(
                [sqlcmd, "-S", server] + auth + tls + ["-b", "-d", "master", "-Q", create_sql],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            create_out = (create_result.stdout + create_result.stderr).strip()
            if create_result.returncode != 0:
                if _is_ssl_cert_error(create_out):
                    self._log_line("  ! sqlcmd bloccato dal certificato TLS - riprovo via ODBC", "warn")
                    return self._create_sql_database_via_odbc(cfg, db)
                self._log_line(f"  ✗ Creazione DB: {create_out[:500]}", "err")
                self._log_sql_database_access_hint(cfg, db)
                return False

            verify_result = subprocess.run(
                [sqlcmd, "-S", server] + auth + tls + ["-b", "-d", db, "-Q", verify_sql],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            verify_out = (verify_result.stdout + verify_result.stderr).strip()
            if verify_result.returncode == 0:
                self._log_line(f"  ✓ Database [{db}] pronto", "ok")
                return True

            if _is_ssl_cert_error(verify_out):
                self._log_line("  ! sqlcmd bloccato dal certificato TLS - verifico via ODBC", "warn")
                return self._check_sql_database_access(cfg, db)
            self._log_line(f"  ✗ Database [{db}] creato ma non apribile: {verify_out[:500]}", "err")
            self._log_sql_database_access_hint(cfg, db)
            return False
        except FileNotFoundError:
            self._log_line("  ⚠ sqlcmd non trovato — creo/verifico il DB via ODBC", "warn")
            return self._create_sql_database_via_odbc(cfg, db)
        except Exception as e:
            self._log_line(f"  ⚠ Creazione DB: {e}", "warn")
            return self._create_sql_database_via_odbc(cfg, db)

    def _configure_sql_login(self, cfg):
        """Crea il login NT AUTHORITY\\SYSTEM su SQL Server (necessario quando
        il pool IIS gira come LocalSystem con Windows Integrated Auth)."""
        server = cfg.db_host or "localhost"
        try:
            db = _validate_sql_identifier(cfg.db_name)
        except ValueError as e:
            self._log_line(f"  ✗ {e}", "err")
            return
        db_bracket = _sql_bracket_escape(db)
        sql = (
            f"IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'NT AUTHORITY\\SYSTEM') "
            f"BEGIN CREATE LOGIN [NT AUTHORITY\\SYSTEM] FROM WINDOWS END; "
            f"USE [{db_bracket}]; "
            f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'NT AUTHORITY\\SYSTEM') "
            f"BEGIN CREATE USER [NT AUTHORITY\\SYSTEM] FOR LOGIN [NT AUTHORITY\\SYSTEM] END; "
            f"ALTER ROLE db_owner ADD MEMBER [NT AUTHORITY\\SYSTEM];"
        )
        sqlcmd = self._find_sqlcmd()
        tls = self._sqlcmd_tls_args(cfg)
        try:
            r = subprocess.run(
                [sqlcmd, "-S", server, "-E"] + tls + ["-b", "-Q", sql],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                self._log_line("  ✓ Login [NT AUTHORITY\\SYSTEM] configurato su SQL Server", "ok")
            else:
                self._log_line(f"  ⚠ sqlcmd (login NT AUTHORITY\\SYSTEM): {out[:300]}", "warn")
                self._log_line(
                    "  → Eseguire manualmente in SSMS:\n"
                    f"    USE [master]; CREATE LOGIN [NT AUTHORITY\\SYSTEM] FROM WINDOWS;\n"
                    f"    USE [{db_bracket}]; CREATE USER [NT AUTHORITY\\SYSTEM] FOR LOGIN [NT AUTHORITY\\SYSTEM];\n"
                    f"    ALTER ROLE db_owner ADD MEMBER [NT AUTHORITY\\SYSTEM];", "warn")
        except FileNotFoundError:
            self._log_line(
                "  ⚠ sqlcmd non trovato — configurare manualmente NT AUTHORITY\\SYSTEM su SQL Server:\n"
                f"    USE [master]; CREATE LOGIN [NT AUTHORITY\\SYSTEM] FROM WINDOWS;\n"
                f"    USE [{db_bracket}]; CREATE USER [NT AUTHORITY\\SYSTEM] FOR LOGIN [NT AUTHORITY\\SYSTEM];\n"
                f"    ALTER ROLE db_owner ADD MEMBER [NT AUTHORITY\\SYSTEM];", "warn")
        except Exception as e:
            self._log_line(f"  ⚠ Impossibile configurare login SQL: {e}", "warn")

    def _configure_iis(self, cfg):
        ep = cfg.env_path
        ps = f"""
Import-Module WebAdministration -ErrorAction SilentlyContinue
# Sblocca <handlers> a livello server (fix errore 0x80070021 / 500.19)
$appcmd = "$env:windir\\system32\\inetsrv\\appcmd.exe"
if (Test-Path $appcmd) {{ & $appcmd unlock config -section:system.webServer/handlers | Out-Null }}
$p = "{_ps_escape(cfg.app_pool_name)}"; $s = "{_ps_escape(cfg.site_name)}"
$r = "{_ps_escape(str(ep))}"; $port = {cfg.iis_port}; $hh = "{_ps_escape(cfg.iis_hostname)}"
if (-not (Test-Path "IIS:\\AppPools\\$p")) {{ New-WebAppPool -Name $p | Out-Null }}
Set-ItemProperty "IIS:\\AppPools\\$p" managedRuntimeVersion ""
Set-ItemProperty "IIS:\\AppPools\\$p" startMode "AlwaysRunning"
Set-ItemProperty "IIS:\\AppPools\\$p" "processModel.idleTimeout" ([TimeSpan]::Zero)
# Identità LocalSystem: necessario per accedere al venv e ai file Django senza errori 502.3
Set-ItemProperty "IIS:\\AppPools\\$p" "processModel.identityType" 0
if (-not (Test-Path "IIS:\\Sites\\$s")) {{
    New-Website -Name $s -PhysicalPath $r -ApplicationPool $p -Port $port -HostHeader $hh -Force | Out-Null
}} else {{
    Set-ItemProperty "IIS:\\Sites\\$s" physicalPath $r
    Set-ItemProperty "IIS:\\Sites\\$s" applicationPool $p
}}
foreach ($vd in @("static","media")) {{
    $vpath = "$r\\$vd"
    if (-not (Test-Path "IIS:\\Sites\\$s\\$vd")) {{
        New-WebVirtualDirectory -Site $s -Name $vd -PhysicalPath $vpath | Out-Null
    }}
}}
Start-Website -Name $s -ErrorAction SilentlyContinue
Start-WebAppPool -Name $p -ErrorAction SilentlyContinue
"""
        try:
            r = subprocess.run(
                ["powershell","-ExecutionPolicy","Bypass","-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0:
                self._log_line("  ✓ IIS configurato", "ok")
            else:
                self._log_line(f"  ✗ IIS: {(r.stderr or r.stdout)[:300]}", "err")
        except Exception as e:
            self._log_line(f"  ✗ IIS: {e}", "err")


class FinishPage(Page):
    def __init__(self, parent, cfg, on_close=None):
        super().__init__(parent, "Installazione Completata!", "")
        self.cfg = cfg
        self._on_close = on_close
        b = self.body
        frame(b, height=10).pack()

        # Banner stato: mostra esplicitamente se l'installazione è incompleta.
        # Popolato in on_enter() da cfg.install_blocking / install_errors.
        self._status_banner = tk.Label(b, text="", font=(SF,10,"bold"),
                                        bg="white", fg=GRAY600, anchor="w", justify="left",
                                        wraplength=620)
        self._status_banner.pack(fill="x", padx=32, pady=(0,10))

        self._url_lbl = tk.Label(b, text="", font=(SF,15,"bold"),
                                  fg=BRAND, bg="white", cursor="hand2")
        self._url_lbl.pack(padx=32, anchor="w")
        self._url_lbl.bind("<Button-1>", self._open_url)

        frame(b, bg=GRAY100, height=1).pack(fill="x", padx=32, pady=16)

        steps = [
            ("1", "Apri il browser all'URL sopra — verifica la pagina di login"),
            ("2", "Controlla i log in  ENV\\logs\\  per eventuali avvisi"),
            ("3", "Aggiungi credenziali Graph API nel .env se usi SharePoint"),
            ("4", "Primo accesso con le credenziali AD o il superuser Django"),
        ]
        for num, desc in steps:
            row = frame(b)
            row.pack(fill="x", padx=32, pady=3)
            tk.Label(row, text=num, font=(SF,9,"bold"), bg=BRAND, fg="white",
                     width=2, pady=4).pack(side="left", padx=(0,12))
            tk.Label(row, text=desc, font=FN, fg=GRAY600, bg="white").pack(side="left")

        frame(b, height=12).pack()
        # ── Dashboard button ─────────────────────────────────────
        dbtn_row = frame(b)
        dbtn_row.pack(padx=32, anchor="w")
        PrimaryButton(dbtn_row, "📊  Gestisci server (Dashboard)",
                      self._open_dashboard, bg=BRAND_DARK).pack(side="left")
        SecondaryButton(dbtn_row, "🌐  Apri nel browser",
                        self._open_url).pack(side="left", padx=(10, 0))

        frame(b, height=10).pack()
        self._countdown_lbl = tk.Label(b, text="", font=FSM, fg=GRAY400, bg="white")
        self._countdown_lbl.pack(padx=32, anchor="w")
        tk.Label(b, text="Portale Novicrom · Setup Wizard · Costruzioni Novicrom SRL",
                 font=FSM, fg=GRAY400, bg="white").pack(padx=32, anchor="w", pady=(8,0))

    def on_enter(self):
        p = "https" if self.cfg.iis_https else "http"
        h = self.cfg.iis_hostname or "localhost"
        pt = f":{self.cfg.iis_port}" if self.cfg.iis_port not in ("80","443") else ""
        self._url = f"{p}://{h}{pt}/"
        self._url_lbl.configure(text=f"→  {self._url}")

        blocking = list(getattr(self.cfg, "install_blocking", []) or [])
        other_errors = [
            e for e in (getattr(self.cfg, "install_errors", []) or [])
            if e not in blocking
        ]
        # Aggiorna titolo e banner in funzione dello stato reale.
        if blocking:
            self.title_label.configure(text="Installazione Incompleta")
            self._status_banner.configure(
                fg="#b91c1c",
                text=("⚠  Errori bloccanti: release NON attivata, IIS non aggiornato.\n"
                      f"  · {chr(10) + '  · '.join(blocking)}\n"
                      "  Correggi e rilancia il wizard — non aprire l'URL, il portale non è in linea."),
            )
            countdown = 60
        elif other_errors:
            self.title_label.configure(text="Installazione Completata (con avvisi)")
            self._status_banner.configure(
                fg="#92400e",
                text=("⚠  Release attivata ma con avvisi non bloccanti:\n"
                      f"  · {chr(10) + '  · '.join(other_errors)}\n"
                      "  Il portale è in linea; consulta i log per i dettagli."),
            )
            countdown = 30
        else:
            self.title_label.configure(text="Installazione Completata!")
            self._status_banner.configure(text="", fg=GRAY600)
            countdown = 15
        self._start_countdown(countdown)

    def _open_dashboard(self):
        ServerDashboard(parent=self.winfo_toplevel())

    def _start_countdown(self, n):
        if n <= 0:
            self._countdown_lbl.configure(text="Chiusura in corso…")
            if self._on_close:
                try: self._on_close()
                except: pass
            return
        self._countdown_lbl.configure(
            text=f"La finestra si chiuderà automaticamente tra {n} second{'o' if n==1 else 'i'}…")
        self.after(1000, lambda: self._start_countdown(n - 1))

    def _open_url(self, _=None):
        try: os.startfile(self._url)
        except: pass


# ─────────────────────────────────────────────────────────────
# APP PRINCIPALE
# ─────────────────────────────────────────────────────────────

def _detect_repo_root() -> str:
    """Risale alla root del repository quando si gira come script (non exe).
    Quando si gira come exe il sorgente è bundled in sys._MEIPASS → restituisce ''."""
    if getattr(sys, "frozen", False):
        return ""   # exe: sorgente bundled, verrà estratto in _run()
    # script: deployment/setup_wizard.py → parent.parent = root repo
    candidate = Path(__file__).parent.parent
    if (candidate / "django_app").exists():
        return str(candidate)
    return ""


class WizardApp:
    def __init__(self, preselect_env=None):
        self.cfg = Config()
        if preselect_env: self.cfg.environment = preselect_env
        # Per DEV auto-rileva la cartella sorgente dal repo corrente
        if self.cfg.environment == "dev":
            self.cfg.dev_source = _detect_repo_root()
        self._env  = preselect_env
        self._idx  = 0

        self.root = tk.Tk()
        self.root.title("Portale Novicrom — Setup Wizard")
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)
        self.root.configure(bg="white")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        # Centra
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - WIN_W) // 2
        y = (self.root.winfo_screenheight() - WIN_H) // 2 - 20
        self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")

        self._build()
        self._show(0)
        self.root.mainloop()

    def _build(self):
        main = frame(self.root)
        main.pack(fill="both", expand=True)

        self.sidebar = Sidebar(main)
        self.sidebar.pack(side="left", fill="y")

        right = frame(main)
        right.pack(side="left", fill="both", expand=True)

        self.container = frame(right)
        self.container.pack(fill="both", expand=True)

        # Bottom bar
        (self.btn_back, self.btn_cancel,
         self.btn_next, self.btn_finish) = _build_bottom_bar(
            right, self._back, self._cancel, self._next, self._close)

        # Pagine (EnvironmentPage prima di PackagePage: la pagina pacchetto
        # deve conoscere l'ambiente selezionato per mostrare zip o cartella)
        self.pages = [
            WelcomePage(               self.container, self.cfg),          # 0
            EnvironmentPage(           self.container, self.cfg,           # 1
                                        preselect=self._env),
            PackagePage(               self.container, self.cfg),          # 2 — skip DEV
            PythonPage(                self.container, self.cfg),          # 3
            DatabasePage(              self.container, self.cfg),          # 4
            LDAPPage(                  self.container, self.cfg),          # 5
            EmailPage(                 self.container, self.cfg),          # 6
            IISPage(                   self.container, self.cfg),          # 7 — skip DEV
            HttpPlatformHandlerPage(   self.container, self.cfg),          # 8 — skip DEV
            AdminPage(                 self.container, self.cfg),          # 9
            ModulesPage(               self.container, self.cfg),          # 10
            AIPage(                    self.container, self.cfg),          # 11
            SummaryPage(               self.container, self.cfg),          # 12
            InstallPage(               self.container, self.cfg,           # 13
                                        self._on_done),
            FinishPage(                self.container, self.cfg, self._close),  # 14
        ]

    def _show(self, idx):
        for p in self.pages: p.place_forget()
        page = self.pages[idx]
        page.place(x=0, y=0, relwidth=1, relheight=1)
        page.on_enter()
        self.sidebar.set(idx)
        self._idx = idx

        last   = len(self.pages) - 1
        install = last - 1

        # Avanti / Indietro
        self.btn_back.set_enabled(idx > 0)

        if idx == last:      # Pagina finale
            self.btn_next.pack_forget()
            self.btn_finish.pack(side="right")
            self.btn_back.set_enabled(False)
            self.btn_cancel.set_enabled(False)
        elif idx == install: # Installazione
            self.btn_next.pack_forget()
            self.btn_finish.pack_forget()
            self.btn_back.set_enabled(False)
            self.btn_cancel.set_enabled(False)
        else:
            self.btn_finish.pack_forget()
            self.btn_next.pack(side="right")
            lbl = "▶  Installa" if idx == install - 1 else "Avanti  ▶"
            self.btn_next.configure_text(lbl)
            self.btn_back.set_enabled(idx > 0)
            self.btn_cancel.set_enabled(True)

    # Indici pagine da saltare in modalità DEV
    _PACKAGE_PAGE_IDX = 2
    _IIS_PAGE_IDX     = 7
    _HPH_PAGE_IDX     = 8   # HttpPlatformHandlerPage — non ha senso in DEV (no IIS)

    def _skip_for_dev(self, target_idx: int, going_forward: bool = True) -> int:
        """Salta PackagePage (2), IISPage (7) e HttpPlatformHandlerPage (8) in DEV."""
        if self.cfg.environment != "dev":
            return target_idx
        skipped = {self._PACKAGE_PAGE_IDX, self._IIS_PAGE_IDX, self._HPH_PAGE_IDX}
        step = 1 if going_forward else -1
        while target_idx in skipped:
            target_idx += step
        return target_idx

    def _next(self):
        p = self.pages[self._idx]
        if p.validate():
            p.on_leave()
            self._show(self._skip_for_dev(self._idx + 1, going_forward=True))

    def _back(self):
        if self._idx > 0:
            self._show(self._skip_for_dev(self._idx - 1, going_forward=False))

    def _close(self):
        try: self.root.quit()
        except: pass
        try: self.root.destroy()
        except: pass

    def _cancel(self):
        if messagebox.askyesno("Annulla", "Uscire dal wizard?"): self._close()

    def _on_done(self):
        self._show(len(self.pages) - 1)
        # Il countdown e la chiusura automatica sono gestiti da FinishPage._start_countdown()


# ─────────────────────────────────────────────────────────────
# RELEASE MANAGER
# ─────────────────────────────────────────────────────────────

class ReleaseConfig:
    def __init__(self):
        self.mode         = "promote"       # "create" | "promote" | "hotfix-create" | "hotfix-apply"
        # Crea release (DEV)
        self.source_dir   = r"C:\Dev\Portale Novicrom"
        self.output_dir   = ""
        # Promuovi release
        self.package_path = ""
        self.environment  = "test"
        self.acl_seed_uat = True
        self.base_dir     = r"C:\PortaleNovicrom"
        # Hotfix (DEV crea il pacchetto -> server lo applica)
        self.hotfix_files   = []    # file selezionati per il pacchetto (Crea Hotfix)
        self.hotfix_package = ""    # percorso del pacchetto hotfix .zip (Applica Hotfix)
        self.hotfix_manage  = []    # management command opzionali dopo l'applicazione
        self.hotfix_recycle = True  # riciclo App Pool IIS dopo l'applicazione

    @property
    def env_path(self): return Path(self.base_dir) / self.environment

    @property
    def app_pool_name(self): return f"PortaleNovicrom-{self.environment.upper()}"


class ReleaseModeSelector(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Gestione Release",
                         "Scegli l'operazione da eseguire")
        self.cfg = cfg
        b = self.body
        frame(b, height=10).pack()

        opts = [
            ("promote",
             "Promuovi Release  →  TEST / PROD",
             "Prendi un .zip già testato e deployalo su un ambiente server",
             (BLUE_BG, BLUE_BD, "#1d4ed8")),
            ("create",
             "Crea Release  ←  DEV",
             "Pacchettizza il codice sorgente dal PC di sviluppo in un file .zip",
             (GREEN_BG, GREEN_BD, "#166534")),
            ("hotfix-create",
             "Crea Hotfix  ←  DEV",
             "Rileva i file modificati con git e crea un piccolo pacchetto .zip di soli quelli",
             (YELLOW_BG, YELLOW_BD, YELLOW_TX)),
            ("hotfix-apply",
             "Applica Hotfix  →  TEST / PROD",
             "Applica un pacchetto hotfix .zip sul release attivo e ricicla IIS — senza nuova release",
             (YELLOW_BG, YELLOW_BD, YELLOW_TX)),
        ]
        self._sel = CardSelector(b, opts, initial="promote",
                                  on_change=lambda v: setattr(cfg, "mode", v))
        self._sel.pack(fill="x", padx=32)

        frame(b, bg=GRAY100, height=1).pack(fill="x", padx=32, pady=14)

        info = frame(b, bg=GRAY50, highlightthickness=1, highlightbackground=GRAY200)
        info.pack(fill="x", padx=32)
        tk.Label(info,
                 text="Release completa: Crea Release su DEV  →  copia .zip sul server  →  "
                      "Promuovi Release.\nHotfix: Crea Hotfix su DEV (rileva i file con git)  →  "
                      "copia il pacchetto sul server  →  Applica Hotfix.",
                 font=FSM, bg=GRAY50, fg=GRAY500, wraplength=560, justify="left"
                 ).pack(anchor="w", padx=14, pady=10)

    def validate(self):
        self.cfg.mode = self._sel.value
        return True


class ReleaseConfigCreate(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Crea Release",
                         "Pacchettizza il codice sorgente in un file .zip pronto per il deploy")
        self.cfg = cfg
        self._src = tk.StringVar(value=r"C:\Dev\Portale Novicrom")
        self._out = tk.StringVar()
        b = self.body

        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        tk.Label(sec, text="Cartella sorgente (repo git)", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row = frame(sec)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._src, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia  ",
                        lambda: self._src.set(filedialog.askdirectory() or self._src.get())
                        ).pack(side="left", padx=(8,0))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        tk.Label(sec, text="Cartella output (dove salvare il .zip)", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row2 = frame(sec)
        row2.pack(fill="x")
        tk.Entry(row2, textvariable=self._out, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row2, "  Sfoglia  ",
                        lambda: self._out.set(filedialog.askdirectory() or self._out.get())
                        ).pack(side="left", padx=(8,0))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        info = frame(sec, bg=GRAY50, highlightthickness=1, highlightbackground=GRAY200)
        info.pack(fill="x")
        tk.Label(info, text="File esclusi automaticamente:", font=(SF,9,"bold"),
                 bg=GRAY50, fg=GRAY700).pack(anchor="w", padx=14, pady=(10,4))
        tk.Label(info,
                 text=".git  ·  .venv / venv  ·  .env  ·  __pycache__  ·  *.pyc  ·  "
                      "db.sqlite3  ·  media/  ·  logs/  ·  staticfiles/  ·  releases/",
                 font=FMO, bg=GRAY50, fg=GRAY500,
                 wraplength=520, justify="left").pack(anchor="w", padx=14, pady=(0,10))

    def on_enter(self):
        if not self._out.get():
            self._out.set(str(Path(r"C:\PortaleNovicrom") / "shared" / "packages"))

    def validate(self):
        src = self._src.get().strip()
        if not Path(src).exists():
            messagebox.showerror("Errore", "Cartella sorgente non trovata.")
            return False
        self.cfg.source_dir = src
        self.cfg.output_dir = self._out.get().strip() or str(Path(src).parent)
        return True


class ReleaseConfigPromote(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Promuovi Release",
                         "Seleziona il pacchetto .zip e l'ambiente destinazione")
        self.cfg = cfg
        self._pkg  = tk.StringVar()
        self._base = tk.StringVar(value=r"C:\PortaleNovicrom")
        b = self.body

        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        tk.Label(sec, text="File pacchetto .zip", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row = frame(sec)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._pkg, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia  ", self._browse).pack(side="left", padx=(8,0))

        self._pkg_info = tk.Label(sec, text="", font=FSM, fg=GREEN, bg="white")
        self._pkg_info.pack(anchor="w", pady=(3,8))
        self._pkg.trace_add("write", self._on_pkg)

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=(4,12))
        tk.Label(sec, text="Ambiente destinazione", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,6))

        env_opts = [
            ("test", "TEST",
             "Windows Server · SQL Server TEST · IIS porta 8080",
             (YELLOW_BG, YELLOW_BD, YELLOW_TX)),
            ("prod", "PROD",
             "Windows Server · SQL Server PROD · IIS porta 80 · utenti reali",
             (GREEN_BG, GREEN_BD, "#166534")),
        ]
        self._seed_uat = tk.BooleanVar(value=bool(getattr(self.cfg, "acl_seed_uat", True)))
        self._env_sel = CardSelector(sec, env_opts, initial="test", on_change=self._on_env_change)
        self._env_sel.pack(fill="x")
        self._acl_seed_box = frame(
            sec,
            bg=YELLOW_BG,
            highlightthickness=1,
            highlightbackground=YELLOW_BD,
        )
        tk.Checkbutton(
            self._acl_seed_box,
            text="  Esegui seed UAT ACL dopo il bootstrap (solo TEST)",
            variable=self._seed_uat,
            font=(SF, 9, "bold"),
            bg=YELLOW_BG,
            fg=YELLOW_TX,
            activebackground=YELLOW_BG,
            activeforeground=YELLOW_TX,
            selectcolor=YELLOW_BG,
            anchor="w",
            justify="left",
        ).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Label(
            self._acl_seed_box,
            text="Opzione utile in ambiente di test interno; in produzione va lasciata disattiva.",
            font=FSM,
            bg=YELLOW_BG,
            fg=YELLOW_TX,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))
        self._on_env_change(self._env_sel.value)

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)
        tk.Label(sec, text="Directory base server", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row2 = frame(sec)
        row2.pack(fill="x")
        tk.Entry(row2, textvariable=self._base, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row2, "  Sfoglia  ",
                        lambda: self._base.set(filedialog.askdirectory() or self._base.get())
                        ).pack(side="left", padx=(8,0))

        self.sf.show_scrollbar(True)

    def on_enter(self):
        if not self._pkg.get():
            z = find_latest_zip(self._base.get())
            if z: self._pkg.set(z)
        self._on_env_change(self._env_sel.value)

    def _on_env_change(self, value):
        if value == "test":
            self._acl_seed_box.pack(fill="x", pady=(10, 0))
        else:
            self._acl_seed_box.pack_forget()

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Seleziona pacchetto release",
            filetypes=[("Zip files", "*.zip"), ("All", "*.*")])
        if p: self._pkg.set(p)

    def _on_pkg(self, *_):
        val = self._pkg.get().strip()
        if val and Path(val).exists():
            n = Path(val).name
            m = re.search(r"v(\d+\.\d+[\.\d]*)", n)
            ver = m.group(1) if m else "?"
            sz  = round(Path(val).stat().st_size / 1024 / 1024, 1)
            self._pkg_info.configure(text=f"  ✓  {n}   ·   v{ver}   ·   {sz} MB", fg=GREEN)
        else:
            self._pkg_info.configure(text="")

    def validate(self):
        pkg = self._pkg.get().strip()
        if pkg and not Path(pkg).exists():
            messagebox.showerror("Errore", "File non trovato.")
            return False
        self.cfg.package_path = pkg
        self.cfg.environment  = self._env_sel.value
        self.cfg.acl_seed_uat = bool(self._seed_uat.get() and self._env_sel.value == "test")
        self.cfg.base_dir     = self._base.get().strip()
        return bool(self.cfg.base_dir)


def _git_changed_files(repo: str):
    """File modificati/nuovi rilevati da git. Ritorna (lista_relpath, errore)."""
    repo_path = Path(repo)
    if not (repo_path / ".git").exists():
        return [], "La cartella indicata non è un repository git (.git assente)."
    files = []
    try:
        for args in (["diff", "--name-only", "HEAD"],
                     ["ls-files", "--others", "--exclude-standard"]):
            r = subprocess.run(
                ["git", "-C", str(repo_path), *args],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    s = line.strip().replace("\\", "/")
                    if s and s not in files:
                        files.append(s)
            elif not files:
                err = (r.stderr or "").strip()
                return [], f"git: {err[:200]}" if err else "git ha restituito un errore."
    except FileNotFoundError:
        return [], "git non trovato nel PATH di sistema."
    except Exception as e:
        return [], f"Errore git: {e}"
    return sorted(files), ""


def find_latest_hotfix_zip(base_dir):
    d = Path(base_dir) / "shared" / "packages"
    if d.exists():
        zips = sorted(d.glob("hotfix-*.zip"), reverse=True)
        if zips:
            return str(zips[0])
    return ""


class ReleaseConfigHotfixCreate(Page):
    """Crea Hotfix (DEV): rileva i file modificati con git e li impacchetta in un .zip."""

    def __init__(self, parent, cfg):
        super().__init__(parent, "Crea Hotfix",
                         "Rileva i file modificati con git e crea un piccolo pacchetto .zip")
        self.cfg = cfg
        self._src = tk.StringVar(value=cfg.source_dir or r"C:\Dev\Portale Novicrom")
        self._out = tk.StringVar(value=cfg.output_dir or "")
        b = self.body

        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        tk.Label(sec, text="Cartella sorgente (repo git)", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row = frame(sec)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._src, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia  ", self._browse_repo).pack(side="left", padx=(8,0))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        hdr = frame(sec)
        hdr.pack(fill="x")
        tk.Label(hdr, text="File da includere nell'hotfix",
                 font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(side="left")
        SecondaryButton(hdr, "  + Aggiungi file…  ", self._browse_files).pack(side="right")
        SecondaryButton(hdr, "  ⟳ Rileva da git  ",
                        lambda: self._detect_git(silent=False)).pack(side="right", padx=(0,6))

        txt_wrap = frame(sec, highlightthickness=1, highlightbackground=GRAY200)
        txt_wrap.pack(fill="x", pady=(6,0))
        self._files = tk.Text(txt_wrap, font=FMO, height=8, bg=GRAY50, fg=GRAY800,
                              relief="flat", padx=8, pady=6, wrap="none")
        self._files.pack(fill="x")
        self._status = tk.Label(sec, text="", font=FSM, fg=GRAY400, bg="white")
        self._status.pack(anchor="w", pady=(3,0))

        warn = frame(sec, bg=YELLOW_BG, highlightthickness=1, highlightbackground=YELLOW_BD)
        warn.pack(fill="x", pady=(10,0))
        tk.Label(warn,
                 text="⚠  L'hotfix è solo per file applicativi (.py, template, .sql, .css/.js). "
                      "Se tra i file compaiono migration o requirements.txt usa Crea Release.",
                 font=FSM, bg=YELLOW_BG, fg=YELLOW_TX,
                 wraplength=520, justify="left").pack(anchor="w", padx=14, pady=10)

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        tk.Label(sec, text="Cartella output (dove salvare il pacchetto hotfix)",
                 font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row2 = frame(sec)
        row2.pack(fill="x")
        tk.Entry(row2, textvariable=self._out, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row2, "  Sfoglia  ",
                        lambda: self._out.set(filedialog.askdirectory() or self._out.get())
                        ).pack(side="left", padx=(8,0))

        self.sf.show_scrollbar(True)

    def on_enter(self):
        if not self._out.get():
            self._out.set(str(Path(r"C:\PortaleNovicrom") / "shared" / "packages"))
        src = self._src.get().strip()
        if not self._parsed_files() and src and Path(src).exists():
            self._detect_git(silent=True)

    def _browse_repo(self):
        d = filedialog.askdirectory()
        if d:
            self._src.set(d)
            self._detect_git(silent=True)

    def _detect_git(self, silent=True):
        repo = self._src.get().strip()
        if not repo or not Path(repo).exists():
            if not silent:
                messagebox.showerror("Errore", "Cartella repo non trovata.")
            return
        files, err = _git_changed_files(repo)
        if err:
            self._status.configure(text=err, fg="#b45309")
            if not silent:
                messagebox.showwarning("git", err)
            return
        if not files:
            self._status.configure(text="Nessuna modifica rilevata da git.", fg=GRAY400)
            return
        existing = {l.strip() for l in self._files.get("1.0", "end").splitlines() if l.strip()}
        added = 0
        for f in files:
            if f not in existing:
                self._files.insert("end", f + "\n")
                existing.add(f)
                added += 1
        self._status.configure(
            text=f"{len(files)} file rilevati da git · {added} aggiunti all'elenco.", fg=GREEN)

    def _browse_files(self):
        repo = self._src.get().strip()
        init = repo if repo and Path(repo).exists() else None
        paths = filedialog.askopenfilenames(
            title="Seleziona i file da includere", initialdir=init)
        if not paths:
            return
        existing = {l.strip() for l in self._files.get("1.0", "end").splitlines() if l.strip()}
        for p in paths:
            rel = p
            if repo:
                try:
                    rel = str(Path(p).resolve().relative_to(Path(repo).resolve()))
                except Exception:
                    rel = p
            rel = rel.replace("\\", "/")
            if rel not in existing:
                self._files.insert("end", rel + "\n")
                existing.add(rel)

    def _parsed_files(self):
        out = []
        for line in self._files.get("1.0", "end").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s.replace("\\", "/"))
        return out

    def validate(self):
        src = self._src.get().strip()
        if not Path(src).exists():
            messagebox.showerror("Errore", "Cartella sorgente non trovata.")
            return False
        files = self._parsed_files()
        if not files:
            messagebox.showerror(
                "Errore",
                "Nessun file da includere. Usa 'Rileva da git' o aggiungi i file manualmente.")
            return False
        self.cfg.source_dir   = src
        self.cfg.output_dir   = self._out.get().strip() or str(Path(src).parent)
        self.cfg.hotfix_files = files
        return True


class ReleaseConfigHotfixApply(Page):
    """Applica Hotfix (server): estrae un pacchetto hotfix .zip nel release attivo."""

    def __init__(self, parent, cfg):
        super().__init__(parent, "Applica Hotfix",
                         "Applica un pacchetto hotfix .zip sul release attivo")
        self.cfg = cfg
        self._pkg     = tk.StringVar()
        self._base    = tk.StringVar(value=cfg.base_dir or r"C:\PortaleNovicrom")
        self._manage  = tk.StringVar()
        self._recycle = tk.BooleanVar(value=True)
        b = self.body

        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        warn = frame(sec, bg=YELLOW_BG, highlightthickness=1, highlightbackground=YELLOW_BD)
        warn.pack(fill="x")
        tk.Label(warn,
                 text="⚠  L'hotfix sovrascrive i file nel release attivo (current\\): "
                      "non crea una nuova release e non aggiorna la junction. "
                      "Per migration, dipendenze o nuovi statici usa Promuovi Release.",
                 font=FSM, bg=YELLOW_BG, fg=YELLOW_TX,
                 wraplength=520, justify="left").pack(anchor="w", padx=14, pady=10)

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        tk.Label(sec, text="Pacchetto hotfix .zip", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row = frame(sec)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._pkg, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia  ", self._browse).pack(side="left", padx=(8,0))
        self._pkg_info = tk.Label(sec, text="", font=FSM, fg=GREEN, bg="white")
        self._pkg_info.pack(anchor="w", pady=(3,8))
        self._pkg.trace_add("write", self._on_pkg)

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=(4,12))

        tk.Label(sec, text="Ambiente destinazione", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,6))
        env_opts = [
            ("test", "TEST",
             "Windows Server · SQL Server TEST · IIS porta 8080",
             (YELLOW_BG, YELLOW_BD, YELLOW_TX)),
            ("prod", "PROD",
             "Windows Server · SQL Server PROD · IIS porta 80 · utenti reali",
             (GREEN_BG, GREEN_BD, "#166534")),
        ]
        self._env_sel = CardSelector(sec, env_opts, initial="test")
        self._env_sel.pack(fill="x")

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        tk.Label(sec, text="Management command Django dopo l'applicazione "
                           "(opzionale, separati da virgola)",
                 font=(SF,9,"bold"), fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        tk.Entry(sec, textvariable=self._manage, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(fill="x", ipady=7, ipadx=8)
        tk.Label(sec, text="Esempio:  apply_sql_triggers, collectstatic --noinput",
                 font=FSM, fg=GRAY400, bg="white").pack(anchor="w", pady=(3,0))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        tk.Checkbutton(sec,
                       text="  Riavvia l'App Pool IIS al termine",
                       variable=self._recycle, font=(SF,9,"bold"),
                       bg="white", fg=GRAY700, activebackground="white",
                       selectcolor="white", anchor="w").pack(anchor="w")

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        tk.Label(sec, text="Directory base server", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row2 = frame(sec)
        row2.pack(fill="x")
        tk.Entry(row2, textvariable=self._base, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row2, "  Sfoglia  ",
                        lambda: self._base.set(filedialog.askdirectory() or self._base.get())
                        ).pack(side="left", padx=(8,0))

        self.sf.show_scrollbar(True)

    def on_enter(self):
        if not self._pkg.get():
            z = find_latest_hotfix_zip(self._base.get())
            if z:
                self._pkg.set(z)

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Seleziona pacchetto hotfix",
            filetypes=[("Zip files", "*.zip"), ("All", "*.*")])
        if p:
            self._pkg.set(p)

    def _on_pkg(self, *_):
        val = self._pkg.get().strip()
        if val and Path(val).exists():
            n  = Path(val).name
            sz = round(Path(val).stat().st_size / 1024, 1)
            self._pkg_info.configure(text=f"  ✓  {n}   ·   {sz} KB", fg=GREEN)
        else:
            self._pkg_info.configure(text="")

    def validate(self):
        pkg = self._pkg.get().strip()
        if not pkg or not Path(pkg).exists():
            messagebox.showerror("Errore", "Seleziona un pacchetto hotfix .zip valido.")
            return False
        base = self._base.get().strip()
        if not base:
            messagebox.showerror("Errore", "Directory base server obbligatoria.")
            return False
        self.cfg.hotfix_package = pkg
        self.cfg.environment    = self._env_sel.value
        self.cfg.base_dir       = base
        self.cfg.hotfix_manage  = [c.strip() for c in self._manage.get().split(",") if c.strip()]
        self.cfg.hotfix_recycle = bool(self._recycle.get())
        return True


class ReleaseRunPage(Page):
    """Pagina di esecuzione con log per Crea / Promuovi release."""

    def __init__(self, parent, cfg, on_done):
        super().__init__(parent, "Esecuzione in corso",
                         "Non chiudere la finestra durante il processo")
        self.cfg = cfg; self._on_done = on_done; self._started = False
        self._log_file = None; self._log_path = None
        b = self.body
        frame(b, height=8).pack()

        self._step_var = tk.StringVar(value="Inizializzazione…")
        tk.Label(b, textvariable=self._step_var,
                 font=(SF,10,"bold"), fg=BRAND, bg="white").pack(anchor="w", padx=32)

        frame(b, height=6).pack()
        self._pb_frame = frame(b, bg=GRAY100, height=8)
        self._pb_frame.pack(fill="x", padx=32)
        self._pb_fill = frame(self._pb_frame, bg=BRAND, height=8)
        self._pb_fill.place(x=0, y=0, relheight=1, width=0)
        self._pb_pct = tk.StringVar(value="0%")
        tk.Label(b, textvariable=self._pb_pct, font=FSM,
                 fg=GRAY400, bg="white").pack(anchor="e", padx=32, pady=(3,8))

        wrap = frame(b, bg=CODE_BG)
        wrap.pack(fill="both", expand=True, padx=32, pady=(0,4))
        sb = tk.Scrollbar(wrap); sb.pack(side="right", fill="y")
        self._log = tk.Text(wrap, font=FMO, bg=CODE_BG, fg=CODE_FG,
                             relief="flat", state="disabled",
                             yscrollcommand=sb.set, padx=12, pady=8, spacing1=1)
        self._log.pack(fill="both", expand=True)
        sb.config(command=self._log.yview)
        self._log.tag_configure("ok",   foreground="#7ee787")
        self._log.tag_configure("err",  foreground="#f85149")
        self._log.tag_configure("warn", foreground="#fbbf24")
        self._log.tag_configure("step", foreground="#58a6ff",
                                 font=("Consolas",9,"bold"))
        self._log.tag_configure("dim",  foreground="#484f58")

    def on_enter(self):
        if not self._started:
            self._started = True
            self._open_log_file()
            threading.Thread(target=self._dispatch, daemon=True).start()

    def _open_log_file(self):
        try:
            if getattr(sys, 'frozen', False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).parent
            log_dir = base / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            op = self.cfg.mode if self.cfg.mode in (
                "create", "promote", "hotfix-create", "hotfix-apply") else "promote"
            self._log_path = log_dir / f"release_{op.replace('-', '_')}_{ts}.log"
            self._log_file = open(self._log_path, "w", encoding="utf-8")
            self._log_file.write(f"Portale Novicrom — Release Manager ({op})\n")
            self._log_file.write(f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            if self.cfg.mode in ("promote", "hotfix-apply"):
                self._log_file.write(f"Ambiente: {self.cfg.environment.upper()}\n")
            self._log_file.write("=" * 60 + "\n\n")
            self._log_file.flush()
        except Exception:
            self._log_file = None

    def _log_line(self, text, tag=""):
        if self._log_file:
            try:
                self._log_file.write(text + "\n")
                self._log_file.flush()
            except Exception:
                pass
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", text+"\n", tag)
            self._log.see("end")
            self._log.configure(state="disabled")
        self._log.after(0, _do)

    def _set_progress(self, pct, label=""):
        def _do():
            self._step_var.set(label or self._step_var.get())
            self._pb_pct.set(f"{pct}%")
            self._pb_frame.update_idletasks()
            w = self._pb_frame.winfo_width()
            self._pb_fill.place(width=int(w * pct / 100))
        self._log.after(0, _do)

    @staticmethod
    def _append_error(errors, entry):
        if entry and entry not in errors:
            errors.append(entry)

    def _cmd(self, cmd, cwd=None, env=None):
        self._log_line(f"  $ {' '.join(str(c) for c in cmd)}", "dim")
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    tag = "err" if any(x in line.lower()
                                       for x in ("error","fatal","traceback")) else ""
                    self._log_line(f"    {line}", tag)
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            self._log_line(f"  ERRORE: {e}", "err"); return False

    def _run_ensure_legacy_schema(self, *, venv_py, django_app, env_vars, settings) -> bool:
        self._log_line("  -> Schema legacy/runtime SQL Server", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "ensure_legacy_schema", f"--settings={settings}"],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  Schema legacy/runtime allineato", "ok")
        else:
            self._log_line("  ensure_legacy_schema fallito", "err")
        return ok

    def _dispatch(self):
        """Wrapper crash-safe: garantisce che _on_done sia sempre chiamato."""
        try:
            if self.cfg.mode == "create":
                self._run_create()
            elif self.cfg.mode == "hotfix-create":
                self._run_hotfix_create()
            elif self.cfg.mode == "hotfix-apply":
                self._run_hotfix_apply()
            else:
                self._run_promote()
        except Exception as e:
            self._log_line(f"\n✗ Errore critico imprevisto: {e}", "err")
            self._log_line(traceback.format_exc(), "err")
            if self._log_file:
                try: self._log_file.close()
                except: pass
            self._log.after(800, self._on_done)

    # ── Crea Release ─────────────────────────────────────────

    def _run_create(self):
        cfg = self.cfg
        src     = Path(cfg.source_dir)
        out_dir = Path(cfg.output_dir)

        # Versioning centralizzato: VERSION -> app_version.py -> fallback legacy
        ver = _read_release_version(src, APP_VERSION)

        tag      = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_name = f"portale-novicrom-v{ver}-{tag}.zip"
        out_path = out_dir / out_name

        EXCLUDE_DIRS  = {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
                         "staticfiles", "node_modules", ".mypy_cache", ".ruff_cache",
                         "htmlcov", "dist", "build", "releases", ".tmp_py",
                         "media", "logs", "backup", "backups", "dump", "dumps"}
        EXCLUDE_EXTS  = {".pyc", ".pyo", ".pyd", ".log", ".sqlite3", ".db",
                         ".bak", ".tmp", ".temp", ".orig", ".dmp"}
        EXCLUDE_FILES = {".env", "db.sqlite3", "DIPENDENTI.csv"}

        N = 3; errors = []

        def step(n, title, pct):
            self._set_progress(pct, f"[{n}/{N}] {title}")
            self._log_line(f"\n── {title} {'─'*(44-len(title))}", "step")

        step(1, "Preparazione", 5)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            self._log_line(f"  Versione rilevata: v{ver}", "ok")
            self._log_line(f"  Output: {out_path}", "ok")
        except Exception as e:
            errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")

        step(2, f"Creazione {out_name}", 15)
        file_count = 0
        try:
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for root, dirs, files in os.walk(src):
                    dirs[:] = [d for d in dirs
                                if d not in EXCLUDE_DIRS and not d.startswith(".")]
                    rel_root = Path(root).relative_to(src)
                    for fname in files:
                        if fname in EXCLUDE_FILES: continue
                        if Path(fname).suffix in EXCLUDE_EXTS: continue
                        if fname.startswith("~$"): continue
                        zf.write(Path(root) / fname, rel_root / fname)
                        file_count += 1
                        if file_count % 100 == 0:
                            self._set_progress(min(15 + int(file_count / 8), 90))
            sz = round(out_path.stat().st_size / 1024 / 1024, 1)
            self._log_line(f"  ✓ {file_count} file · {sz} MB", "ok")
        except Exception as e:
            errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")

        step(3, "Verifica integrità zip", 95)
        try:
            with zipfile.ZipFile(out_path, "r") as zf:
                bad = zf.testzip()
            if bad:
                errors.append(f"zip corrotto: {bad}")
                self._log_line(f"  ✗ File corrotto: {bad}", "err")
            else:
                self._log_line("  ✓ Zip integro", "ok")
                self._log_line(f"  ✓ Salvato: {out_path}", "ok")
                cfg.output_dir = str(out_path)   # riusa in DonePage
        except Exception as e:
            errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")

        self._set_progress(100, "Release creata!")
        self._log_line("\n" + "─"*50, "step")
        if errors:
            self._log_line(f"  Completato con {len(errors)} errori:", "warn")
            for e in errors: self._log_line(f"  · {e}", "warn")
        else:
            self._log_line(f"  {out_name} pronta per il deploy!", "ok")
            self._log_line("  Copia il .zip in  shared\\packages\\  sul server e usa Promuovi Release.", "ok")
        self._log_line("─"*50, "step")
        if self._log_path:
            self._log_line(f"  Log salvato in: {self._log_path}", "dim")
        if self._log_file:
            try: self._log_file.close()
            except: pass
        self._log.after(800, self._on_done)

    def _pip_install_with_retry(self, venv_py, req_file):
        """pip install con retry (speculare a InstallPage). Adatta pyodbc pin per Python 3.14+."""
        try:
            content = req_file.read_text(encoding="utf-8")
            if "pyodbc==5.2.0" in content:
                self._log_line("  → Adattamento pyodbc==5.2.0 → pyodbc>=5.2.0 (Python 3.14 compat)", "dim")
                content = content.replace("pyodbc==5.2.0", "pyodbc>=5.2.0")
                req_file.write_text(content, encoding="utf-8")
        except Exception as e:
            self._log_line(f"  ⚠ Errore durante la modifica requirements.txt: {e}", "warn")
        ok = self._cmd([str(venv_py), "-m", "pip", "install", "-r", str(req_file)])
        if ok:
            return True
        self._log_line("  ⚠ Tentando con --only-binary :all: (solo wheel precompilate)...", "warn")
        ok = self._cmd([str(venv_py), "-m", "pip", "install", "-r", str(req_file), "--only-binary", ":all:"])
        if ok:
            return True
        self._log_line("  ⚠ Su Windows con Python 3.12+, pyodbc richiede Microsoft Visual C++ 14.0 Build Tools:", "warn")
        self._log_line("    https://visualstudio.microsoft.com/visual-cpp-build-tools/", "warn")
        return False

    def _verify_collectstatic_output(self, static_root: Path, errors: list[str]) -> bool:
        missing_assets = _missing_static_assets(static_root)
        if not missing_assets:
            self._log_line("  ✓ Statici condivisi verificati", "ok")
            return True
        self._append_error(errors, "collectstatic: asset statici mancanti")
        self._log_line("  ✗ collectstatic completato ma alcuni asset attesi non esistono", "err")
        for label, path in missing_assets:
            self._log_line(f"    - {label}: {path}", "err")
        return False

    def _run_selective_migrate(
        self, *, venv_py, django_app, env_vars, settings,
        selected_module_keys: list[str],
    ) -> bool:
        """Stessa logica di InstallPage._run_selective_migrate (non c'è ereditarietà)."""
        selected = set(selected_module_keys)
        all_ok = True
        for app_label in _DJANGO_BUILTIN_MIGRATE_LABELS:
            ok = self._cmd(
                [str(venv_py), "manage.py", "migrate", app_label,
                 f"--settings={settings}", "--noinput"],
                cwd=django_app, env=env_vars,
            )
            if not ok:
                self._log_line(f"  ✗ migrate {app_label} fallito", "err")
                all_ok = False
        for m in MODULE_REGISTRY:
            if not m["required"] or not m["has_migrations"]:
                continue
            ok = self._cmd(
                [str(venv_py), "manage.py", "migrate", m["app_label"],
                 f"--settings={settings}", "--noinput"],
                cwd=django_app, env=env_vars,
            )
            if ok:
                self._log_line(f"  ✓ {m['label']}", "ok")
            else:
                self._log_line(f"  ✗ migrate {m['app_label']} fallito", "err")
                all_ok = False
        for m in MODULE_REGISTRY:
            if m["required"] or not m["has_migrations"]:
                continue
            if m["key"] not in selected:
                self._log_line(f"  —  {m['label']} (non selezionato — skip)", "dim")
                continue
            ok = self._cmd(
                [str(venv_py), "manage.py", "migrate", m["app_label"],
                 f"--settings={settings}", "--noinput"],
                cwd=django_app, env=env_vars,
            )
            if ok:
                self._log_line(f"  ✓ {m['label']}", "ok")
            else:
                self._log_line(f"  ✗ migrate {m['app_label']} fallito", "err")
                all_ok = False

        # 4. Safety-net: applica QUALSIASI migrazione residua (app non presenti nel
        # MODULE_REGISTRY o aggiunte dopo). Senza questo, un'app in INSTALLED_APPS ma
        # assente dal registry resta senza tabelle → 500 in prod.
        ok = self._cmd(
            [str(venv_py), "manage.py", "migrate",
             f"--settings={settings}", "--noinput"],
            cwd=django_app, env=env_vars,
        )
        if ok:
            self._log_line("  ✓ migrazioni residue (safety-net globale)", "ok")
        else:
            self._log_line("  ✗ migrate globale (safety-net) fallito", "err")
            all_ok = False

        return all_ok

    def _run_assenze_tipo_alignment(self, *, venv_py, django_app, env_vars, settings) -> bool:
        self._log_line("  -> Assenze SQL Server: allineamento tipo_assenza legacy", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "allinea_tipo_assenza_flessibilita", f"--settings={settings}"],
            cwd=django_app, env=env_vars,
        )
        if ok:
            self._log_line("  ✓ CK_assenze_tipo riallineato a Flessibilità", "ok")
        else:
            self._log_line("  ✗ Riallineamento CK_assenze_tipo fallito", "err")
        return ok

    def _run_apply_sql_triggers(self, *, venv_py, django_app, env_vars, settings) -> bool:
        self._log_line("  -> Trigger SQL automazioni", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "apply_sql_triggers", f"--settings={settings}"],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  Trigger SQL automazioni applicati", "ok")
        else:
            self._log_line("  apply_sql_triggers fallito (non bloccante)", "warn")
        return ok

    def _run_seed_pulsanti_descrizioni(self, *, venv_py, django_app, env_vars, settings):
        """Popola le descrizioni dei pulsanti via seed. Non bloccante."""
        self._log_line("  -> Seed descrizioni pulsanti", "dim")
        ok = self._cmd(
            [str(venv_py), "manage.py", "seed_pulsanti_descrizioni", f"--settings={settings}"],
            cwd=django_app,
            env=env_vars,
        )
        if ok:
            self._log_line("  ✓ Seed pulsanti descrizioni completato", "ok")
        else:
            self._log_line("  ✗ Seed pulsanti descrizioni fallito (non bloccante)", "warn")

    def _run_acl_bootstrap_workflow(
        self, *, venv_py, django_app, env_vars, settings,
        include_legacy_import=True, run_uat_seed=False,
    ):
        self._log_line("  -> ACL v2 audit pre-migrazione (--dry-run)", "dim")
        ok_pre = self._cmd(
            [str(venv_py), "manage.py", "bootstrap_acl_v2", "--dry-run", f"--settings={settings}"],
            cwd=django_app, env=env_vars,
        )
        if ok_pre:
            self._log_line("  ✓ ACL v2 dry-run pre completato", "ok")
        else:
            self._log_line("  ✗ ACL v2 dry-run pre fallito (non bloccante)", "warn")

        apply_cmd = [str(venv_py), "manage.py", "bootstrap_acl_v2"]
        if include_legacy_import:
            apply_cmd.append("--import-legacy")
        apply_cmd.extend(["--apply", f"--settings={settings}"])
        ok_apply = self._cmd(apply_cmd, cwd=django_app, env=env_vars)
        if ok_apply:
            self._log_line("  ✓ ACL v2 bootstrap apply completato", "ok")
        else:
            self._log_line("  ✗ ACL v2 bootstrap apply fallito (non bloccante)", "warn")

        self._log_line("  -> ACL v2 audit post-migrazione (--dry-run)", "dim")
        ok_post = self._cmd(
            [str(venv_py), "manage.py", "bootstrap_acl_v2", "--dry-run", f"--settings={settings}"],
            cwd=django_app, env=env_vars,
        )
        if ok_post:
            self._log_line("  ✓ ACL v2 dry-run post completato", "ok")
        else:
            self._log_line("  ✗ ACL v2 dry-run post fallito (non bloccante)", "warn")

        if run_uat_seed:
            self._log_line("  -> Seed ACL v2 UAT (--reset) [solo TEST]", "dim")
            ok_seed = self._cmd(
                [str(venv_py), "manage.py", "seed_acl_uat", "--reset", f"--settings={settings}"],
                cwd=django_app, env=env_vars,
            )
            if ok_seed:
                self._log_line("  ✓ Seed ACL v2 UAT completato", "ok")
            else:
                self._log_line("  ✗ Seed ACL v2 UAT fallito (non bloccante)", "warn")

    # ── Promuovi Release ─────────────────────────────────────

    def _run_promote(self):
        cfg = self.cfg
        ep  = cfg.env_path

        venv_py = ep / "venv" / "Scripts" / "python.exe"
        if not venv_py.exists():
            self._log_line(f"  ✗ Virtualenv non trovato: {venv_py}", "err")
            self._log_line("  Esegui prima il Setup Wizard (prima installazione).", "warn")
            self._set_progress(100, "Errore — venv mancante")
            if self._log_path:
                self._log_line(f"  Log salvato in: {self._log_path}", "dim")
            if self._log_file:
                try: self._log_file.close()
                except: pass
            self._log.after(800, self._on_done)
            return

        tag        = datetime.now().strftime("%Y%m%d_%H%M%S")
        rel_dir    = ep / "releases" / tag
        django_app = rel_dir / "django_app"
        settings   = _django_settings(cfg.environment)
        N = 7; errors = []

        def step(n, title, pct):
            self._set_progress(pct, f"[{n}/{N}] {title}")
            self._log_line(f"\n── {title} {'─'*(44-len(title))}", "step")

        # 1. Estrazione
        step(1, "Estrazione pacchetto", 8)
        if cfg.package_path and Path(cfg.package_path).exists():
            try:
                rel_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(cfg.package_path, "r") as zf:
                    zf.extractall(rel_dir)
                self._log_line(f"  ✓ Estratto in {rel_dir}", "ok")
            except Exception as e:
                errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")
        else:
            self._log_line("  ✗ Nessun pacchetto specificato", "err")
            errors.append("pacchetto mancante")

        # 2. Copia .env
        step(2, "Copia configurazione .env", 20)
        env_src = ep / "config" / ".env"
        if env_src.exists() and django_app.exists():
            try:
                env_content = env_src.read_text(encoding="utf-8")
                env_content, driver_note = _realign_db_driver_in_env(env_content)
                if driver_note:
                    self._log_line(driver_note, "warn")
                    try:
                        env_src.write_text(env_content, encoding="utf-8")
                    except Exception:
                        pass
                current_env = ep / "current" / "django_app" / ".env"
                if current_env.exists():
                    current_content = current_env.read_text(encoding="utf-8")
                    drift_keys = _env_drift_keys(env_content, current_content)
                    if drift_keys:
                        keys_label = ", ".join(drift_keys)
                        self._append_error(errors, "config .env non allineato")
                        self._log_line("  ERRORE: .env attivo diverso da config\\.env; deploy interrotto", "err")
                        self._log_line(f"  Persistente : {env_src}", "warn")
                        self._log_line(f"  Attivo      : {current_env}", "warn")
                        self._log_line(f"  Chiavi      : {keys_label}", "warn")
                        self._log_line("  Allinea le modifiche desiderate in config\\.env e riprova.", "warn")
                        try:
                            shutil.rmtree(rel_dir, ignore_errors=True)
                        except Exception:
                            pass
                        self._set_progress(100, "Errore - .env non allineato")
                        if self._log_path:
                            self._log_line(f"  Log salvato in: {self._log_path}", "dim")
                        if self._log_file:
                            try: self._log_file.close()
                            except: pass
                        self._log.after(800, self._on_done)
                        return
                (django_app / ".env").write_text(env_content, encoding="utf-8")
                self._log_line(f"  ✓ .env copiato da {env_src}", "ok")
            except Exception as e:
                errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")
        elif not env_src.exists():
            self._log_line(f"  ✗ .env non trovato: {env_src}", "err")
            self._log_line("  Esegui prima il Setup Wizard per configurare l'ambiente.", "warn")
            errors.append(".env mancante")

        # 3. pip install
        step(3, "Aggiornamento dipendenze pip", 32)
        req = django_app / "requirements.txt"
        deps_ready = True
        if req.exists():
            ok = self._pip_install_with_retry(venv_py, req)
            if ok:
                self._log_line("  ✓ Dipendenze aggiornate", "ok")
            else:
                deps_ready = False
                self._append_error(errors, "pip install")
                self._log_line("  ✗ pip fallito", "err")
        else:
            deps_ready = False
            self._log_line("  requirements.txt non trovato — skip", "warn")

        # 4. collectstatic
        step(4, "collectstatic", 50)
        env_vars = {**os.environ,
                    "DJANGO_SETTINGS_MODULE": settings,
                    "PYTHONPATH": str(django_app),
                    "STATIC_ROOT": str(ep / "static"),
                    "MEDIA_ROOT": str(ep / "media"),
                    "PORTAL_SKIP_RUNTIME_BOOTSTRAP": "1"}
        collectstatic_ok = False
        if not deps_ready:
            self._log_line("  Skip — dipendenze Python non disponibili", "warn")
        elif (django_app / "manage.py").exists():
            ok = self._cmd([str(venv_py), "manage.py", "collectstatic",
                             "--noinput", "--clear", f"--settings={settings}"],
                            cwd=django_app, env=env_vars)
            if ok:
                collectstatic_ok = self._verify_collectstatic_output(ep / "static", errors)
            else:
                self._append_error(errors, "collectstatic")
                self._log_line("  ✗ collectstatic fallito", "err")

        # 5. migrate selettivo per modulo
        step(5, "Django migrate", 65)
        migrate_ok = False
        if not deps_ready:
            self._log_line("  Skip — dipendenze Python non disponibili", "warn")
        elif (django_app / "manage.py").exists():
            selected = getattr(cfg, "selected_modules",
                               [m["key"] for m in MODULE_REGISTRY])
            self._log_line(
                f"  Moduli selezionati: {', '.join(selected)}", "dim")
            ok = self._run_selective_migrate(
                venv_py=venv_py, django_app=django_app,
                env_vars=env_vars, settings=settings,
                selected_module_keys=selected,
            )
            if ok:
                migrate_ok = True
                self._log_line("  ✓ migrate completato", "ok")
            else:
                self._append_error(errors, "migrate")
                self._log_line("  ✗ migrate fallito (verifica DB e log sopra)", "err")
            if ok:
                ok_schema = self._run_ensure_legacy_schema(
                    venv_py=venv_py,
                    django_app=django_app,
                    env_vars=env_vars,
                    settings=settings,
                )
                if not ok_schema:
                    self._append_error(errors, "ensure_legacy_schema")
                    migrate_ok = False
                else:
                    ok_triggers = self._run_apply_sql_triggers(
                        venv_py=venv_py,
                        django_app=django_app,
                        env_vars=env_vars,
                        settings=settings,
                    )
                    if not ok_triggers:
                        self._append_error(errors, "apply_sql_triggers")
                    ok_align = self._run_assenze_tipo_alignment(
                        venv_py=venv_py,
                        django_app=django_app,
                        env_vars=env_vars,
                        settings=settings,
                    )
                    if not ok_align:
                        self._append_error(errors, "allinea_tipo_assenza_flessibilita")
            ok_cc = self._cmd([str(venv_py), "manage.py", "createcachetable",
                               f"--settings={settings}"], cwd=django_app, env=env_vars)
            if ok_cc:
                self._log_line("  ✓ createcachetable completato", "ok")
            else:
                self._append_error(errors, "createcachetable")
                self._log_line("  ✗ createcachetable fallito", "warn")
            if migrate_ok:
                self._run_acl_bootstrap_workflow(
                    venv_py=venv_py,
                    django_app=django_app,
                    env_vars=env_vars,
                    settings=settings,
                    include_legacy_import=True,
                    run_uat_seed=bool(getattr(cfg, "acl_seed_uat", True) and cfg.environment == "test"),
                )
                self._run_seed_pulsanti_descrizioni(
                    venv_py=venv_py,
                    django_app=django_app,
                    env_vars=env_vars,
                    settings=settings,
                )

        # 6. Attivazione junction
        step(6, "Attivazione release", 80)
        cur = ep / "current"
        prev_file = ep / "run" / "previous_release.txt"
        activated_release = False
        can_activate = rel_dir.exists() and deps_ready and collectstatic_ok and migrate_ok
        if cur.exists() or cur.is_symlink():
            try:
                prev_target = str(cur.resolve())
                prev_file.parent.mkdir(parents=True, exist_ok=True)
                prev_file.write_text(prev_target, encoding="utf-8")
                self._log_line(f"  ✓ Release precedente salvata: {prev_target}", "ok")
            except: pass
        if not can_activate:
            self._log_line("  Skip — release non attivata per errori nei passaggi precedenti", "warn")
        else:
            try:
                _create_junction(cur, rel_dir)
                activated_release = True
                self._log_line(f"  ✓ current → {rel_dir.name}", "ok")
            except Exception as e:
                self._append_error(errors, str(e))
                self._log_line(f"  ✗ Junction: {e}", "err")

        # 7. IIS recycle
        step(7, "Riavvio App Pool IIS", 93)
        site_name = f"PortaleNovicrom-{cfg.environment.upper()}"
        if not activated_release:
            self._log_line("  Skip — App Pool IIS non riavviato (release non attivata)", "warn")
        else:
            ps = (f"Restart-WebAppPool -Name '{cfg.app_pool_name}' -ErrorAction SilentlyContinue; "
                  f"Start-Website -Name '{site_name}' -ErrorAction SilentlyContinue")
            try:
                r = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode == 0:
                    self._log_line(f"  ✓ App Pool {cfg.app_pool_name} riciclato", "ok")
                else:
                    self._append_error(errors, "iis recycle")
                    self._log_line(f"  ✗ IIS: {(r.stderr or r.stdout)[:200]}", "err")
            except Exception as e:
                self._append_error(errors, "iis recycle")
                self._log_line(f"  ✗ IIS recycle: {e}", "err")

        self._set_progress(100, "Deploy completato!")
        self._log_line("\n" + "─"*50, "step")
        if errors:
            self._log_line(f"  Completato con {len(errors)} errori/avvisi:", "warn")
            for e in errors: self._log_line(f"  · {e}", "warn")
        else:
            self._log_line(f"  Release {cfg.environment.upper()} attivata!", "ok")
        self._log_line("─"*50, "step")
        if self._log_path:
            self._log_line(f"  Log salvato in: {self._log_path}", "dim")
        if self._log_file:
            try: self._log_file.close()
            except: pass
        self._log.after(800, self._on_done)

    # ── Crea Hotfix (DEV) ────────────────────────────────────

    def _run_hotfix_create(self):
        cfg = self.cfg
        src     = Path(cfg.source_dir)
        out_dir = Path(cfg.output_dir)
        ver = _read_release_version(src, APP_VERSION)
        tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_name = f"hotfix-v{ver}-{tag}.zip"
        out_path = out_dir / out_name
        files = list(cfg.hotfix_files)
        N = 3; errors = []

        def step(n, title, pct):
            self._set_progress(pct, f"[{n}/{N}] {title}")
            self._log_line(f"\n── {title} {'─'*(44-len(title))}", "step")

        step(1, "Preparazione", 8)
        self._log_line(f"  Versione rilevata    : v{ver}", "ok")
        self._log_line(f"  File da impacchettare: {len(files)}", "dim")
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            self._log_line(f"  Output: {out_path}", "ok")
        except Exception as e:
            errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")

        step(2, f"Creazione {out_name}", 30)
        added = skipped = 0
        try:
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for rel in files:
                    rel_norm = rel.replace("/", os.sep)
                    fp = src / rel_norm
                    if not fp.exists():
                        self._log_line(f"  [MANCANTE] {rel}", "warn")
                        skipped += 1
                        continue
                    if "migrations" in rel.split("/") or rel.endswith("requirements.txt"):
                        self._log_line(
                            f"  ⚠ {rel} — migration/dipendenza in un hotfix: valuta Crea Release",
                            "warn")
                    zf.write(fp, rel.replace("\\", "/"))
                    self._log_line(f"  ✓ {rel}", "ok")
                    added += 1
            if added == 0:
                errors.append("nessun file incluso")
                self._log_line("  ✗ Nessun file incluso nel pacchetto", "err")
            else:
                sz = round(out_path.stat().st_size / 1024, 1)
                self._log_line(f"  ✓ {added} file · {sz} KB · {skipped} non trovati", "ok")
        except Exception as e:
            errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")

        step(3, "Verifica integrità zip", 92)
        if out_path.exists():
            try:
                with zipfile.ZipFile(out_path, "r") as zf:
                    bad = zf.testzip()
                if bad:
                    errors.append(f"zip corrotto: {bad}")
                    self._log_line(f"  ✗ File corrotto: {bad}", "err")
                else:
                    self._log_line("  ✓ Pacchetto integro", "ok")
                    cfg.output_dir = str(out_path)
            except Exception as e:
                errors.append(str(e)); self._log_line(f"  ✗ {e}", "err")

        self._set_progress(100, "Hotfix creato!")
        self._finish_hotfix(errors)

    # ── Applica Hotfix (server) ──────────────────────────────

    def _run_hotfix_apply(self):
        cfg = self.cfg
        ep  = cfg.env_path
        current    = ep / "current"
        venv_py    = ep / "venv" / "Scripts" / "python.exe"
        django_app = current / "django_app"
        settings   = _django_settings(cfg.environment)
        pkg = Path(cfg.hotfix_package)
        N = 3; errors = []

        def step(n, title, pct):
            self._set_progress(pct, f"[{n}/{N}] {title}")
            self._log_line(f"\n── {title} {'─'*(44-len(title))}", "step")

        self._log_line(f"  Ambiente      : {cfg.environment.upper()}", "dim")
        self._log_line(f"  Release attivo: {current}", "dim")
        self._log_line(f"  Pacchetto     : {pkg}", "dim")

        if not current.exists():
            self._log_line(f"  ✗ Release attiva non trovata: {current}", "err")
            self._log_line("  Esegui prima Promuovi Release per attivare un release.", "warn")
            self._set_progress(100, "Errore — release attiva mancante")
            self._finish_hotfix(["release attiva mancante"])
            return
        if not pkg.exists():
            self._log_line(f"  ✗ Pacchetto hotfix non trovato: {pkg}", "err")
            self._set_progress(100, "Errore — pacchetto mancante")
            self._finish_hotfix(["pacchetto mancante"])
            return

        # 1. Applicazione file
        step(1, "Applicazione file hotfix", 12)
        applied = 0
        current_resolved = str(current.resolve())
        try:
            with zipfile.ZipFile(pkg, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    name = member.filename
                    dest = (current / name).resolve()
                    if not str(dest).startswith(current_resolved):
                        self._append_error(errors, f"percorso non valido: {name}")
                        self._log_line(f"  ✗ Percorso fuori da current\\ ignorato: {name}", "err")
                        continue
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as srcf, open(dest, "wb") as dstf:
                            shutil.copyfileobj(srcf, dstf)
                        self._log_line(f"  ✓ {name}", "ok")
                        applied += 1
                    except Exception as e:
                        self._append_error(errors, f"scrittura {name}")
                        self._log_line(f"  ✗ {name}: {e}", "err")
            self._log_line(f"  {applied} file applicati nel release attivo.", "dim")
            if applied == 0:
                self._append_error(errors, "nessun file applicato")
        except Exception as e:
            self._append_error(errors, str(e))
            self._log_line(f"  ✗ Estrazione hotfix fallita: {e}", "err")

        # 2. Management command Django
        step(2, "Management command Django", 50)
        manage = list(cfg.hotfix_manage)
        if not manage:
            self._log_line("  Nessun comando da eseguire — saltato.", "dim")
        elif not venv_py.exists():
            self._log_line(f"  ✗ Virtualenv non trovato: {venv_py}", "err")
            self._append_error(errors, "venv mancante")
        elif not (django_app / "manage.py").exists():
            self._log_line(f"  ✗ manage.py non trovato in {django_app}", "err")
            self._append_error(errors, "manage.py mancante")
        else:
            env_vars = {**os.environ,
                        "DJANGO_SETTINGS_MODULE": settings,
                        "PYTHONPATH": str(django_app),
                        "STATIC_ROOT": str(ep / "static"),
                        "MEDIA_ROOT": str(ep / "media"),
                        "PORTAL_SKIP_RUNTIME_BOOTSTRAP": "1"}
            for cmd in manage:
                parts = cmd.split()
                full  = [str(venv_py), "manage.py", *parts, f"--settings={settings}"]
                ok = self._cmd(full, cwd=django_app, env=env_vars)
                if ok:
                    self._log_line(f"  ✓ {cmd}", "ok")
                else:
                    self._append_error(errors, f"manage {parts[0]}")
                    self._log_line(f"  ✗ {cmd} fallito", "err")

        # 3. Riciclo App Pool IIS
        step(3, "Riavvio App Pool IIS", 85)
        if not cfg.hotfix_recycle:
            self._log_line("  Skip — riciclo IIS disattivato.", "dim")
        else:
            site_name = f"PortaleNovicrom-{cfg.environment.upper()}"
            ps = (f"Restart-WebAppPool -Name '{cfg.app_pool_name}' -ErrorAction SilentlyContinue; "
                  f"Start-Website -Name '{site_name}' -ErrorAction SilentlyContinue")
            try:
                r = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode == 0:
                    self._log_line(f"  ✓ App Pool {cfg.app_pool_name} riciclato", "ok")
                else:
                    self._append_error(errors, "iis recycle")
                    self._log_line(f"  ✗ IIS: {(r.stderr or r.stdout)[:200]}", "err")
            except Exception as e:
                self._append_error(errors, "iis recycle")
                self._log_line(f"  ✗ IIS recycle: {e}", "err")

        self._set_progress(100, "Hotfix applicato!")
        self._finish_hotfix(errors)

    def _finish_hotfix(self, errors):
        create = self.cfg.mode == "hotfix-create"
        self._log_line("\n" + "─"*50, "step")
        if errors:
            self._log_line(f"  Completato con {len(errors)} errori/avvisi:", "warn")
            for e in errors: self._log_line(f"  · {e}", "warn")
        elif create:
            self._log_line("  Pacchetto hotfix creato!", "ok")
            self._log_line("  Copialo sul server e usa  Applica Hotfix.", "ok")
        else:
            self._log_line(f"  Hotfix applicato su {self.cfg.environment.upper()}!", "ok")
        self._log_line("─"*50, "step")
        if self._log_path:
            self._log_line(f"  Log salvato in: {self._log_path}", "dim")
        if self._log_file:
            try: self._log_file.close()
            except: pass
        self._log.after(800, self._on_done)


class ReleaseDonePage(Page):
    def __init__(self, parent, cfg, on_close=None):
        super().__init__(parent, "Operazione completata!", "")
        self.cfg = cfg
        self._on_close = on_close
        b = self.body
        frame(b, height=16).pack()

        self._msg = tk.Label(b, text="", font=(SF,13,"bold"),
                              fg=BRAND, bg="white", wraplength=560, justify="left")
        self._msg.pack(padx=32, anchor="w")
        frame(b, bg=GRAY100, height=1).pack(fill="x", padx=32, pady=16)
        self._hints = frame(b)
        self._hints.pack(fill="x", padx=32)
        frame(b, height=16).pack()
        self._countdown_lbl = tk.Label(b, text="", font=FSM, fg=GRAY400, bg="white")
        self._countdown_lbl.pack(padx=32, anchor="w")
        tk.Label(b, text="Portale Novicrom · Gestione Release · Costruzioni Novicrom SRL",
                 font=FSM, fg=GRAY400, bg="white").pack(padx=32, anchor="w", pady=(4,0))

    def on_enter(self):
        for w in self._hints.winfo_children(): w.destroy()
        if self.cfg.mode == "create":
            self._msg.configure(text=f"Release salvata in:\n{self.cfg.output_dir}")
            hints = [
                "Copia il .zip nella cartella  shared\\packages\\  del server TEST",
                "Apri Gestione Release sul server → Promuovi Release → TEST",
                "Dopo la validazione, ripeti → Promuovi Release → PROD (stesso .zip)",
            ]
        elif self.cfg.mode == "hotfix-create":
            self._msg.configure(text=f"Pacchetto hotfix salvato in:\n{self.cfg.output_dir}")
            hints = [
                "Copia il pacchetto hotfix sul server (rete, OneDrive, USB…)",
                "Apri Gestione Release sul server → Applica Hotfix",
                "Verifica che le modifiche siano già committate per il prossimo .zip di release",
            ]
        elif self.cfg.mode == "hotfix-apply":
            self._msg.configure(text=f"Hotfix applicato su {self.cfg.environment.upper()}!")
            hints = [
                "Verifica subito i file modificati nel browser",
                "Controlla i log in  ENV\\logs\\  per eventuali avvisi",
                "L'hotfix non aggiorna la junction: resterà attivo fino al prossimo deploy",
            ]
        else:
            self._msg.configure(text=f"Release deployata su {self.cfg.environment.upper()}!")
            hints = [
                "Verifica il portale nel browser",
                "Controlla i log in  ENV\\logs\\  per eventuali avvisi",
                "In caso di problemi: esegui  rollback-release.ps1  per ripristinare",
            ]
        for i, hint in enumerate(hints, 1):
            row = frame(self._hints)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=str(i), font=(SF,9,"bold"), bg=BRAND, fg="white",
                     width=2, pady=4).pack(side="left", padx=(0,12))
            tk.Label(row, text=hint, font=FN, fg=GRAY600, bg="white").pack(side="left")
        self._start_countdown(20)

    def _start_countdown(self, n):
        if n <= 0:
            self._countdown_lbl.configure(text="Chiusura in corso…")
            if self._on_close:
                try: self._on_close()
                except: pass
            return
        self._countdown_lbl.configure(
            text=f"La finestra si chiuderà automaticamente tra {n} second{'o' if n==1 else 'i'}…")
        self.after(1000, lambda: self._start_countdown(n - 1))


class ReleaseApp:
    """App standalone per gestione release (Crea o Promuovi)."""

    def __init__(self, initial_mode=None):
        self.cfg  = ReleaseConfig()
        self._idx = 0
        if initial_mode:
            self.cfg.mode = initial_mode

        self.root = tk.Tk()
        self.root.title("Portale Novicrom — Gestione Release")
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)
        self.root.configure(bg="white")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - WIN_W) // 2
        y = (self.root.winfo_screenheight() - WIN_H) // 2 - 20
        self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")

        self._build()
        # Se la modalità è già preselezionata salta la schermata di scelta
        self._show(1 if initial_mode else 0)
        self.root.mainloop()

    def _build(self):
        main = frame(self.root)
        main.pack(fill="both", expand=True)

        self.sidebar = Sidebar(main, steps=STEPS_RELEASE, subtitle="Gestione Release")
        self.sidebar.pack(side="left", fill="y")

        right = frame(main)
        right.pack(side="left", fill="both", expand=True)
        self.container = frame(right)
        self.container.pack(fill="both", expand=True)

        (self.btn_back, self.btn_cancel,
         self.btn_next, self.btn_finish) = _build_bottom_bar(
            right, self._back, self._cancel, self._next, self._close)

        self._p_mode      = ReleaseModeSelector(self.container, self.cfg)
        self._p_create    = ReleaseConfigCreate(self.container, self.cfg)
        self._p_promote   = ReleaseConfigPromote(self.container, self.cfg)
        self._p_hf_create = ReleaseConfigHotfixCreate(self.container, self.cfg)
        self._p_hf_apply  = ReleaseConfigHotfixApply(self.container, self.cfg)
        self._p_run       = ReleaseRunPage(self.container, self.cfg, self._on_done)
        self._p_done      = ReleaseDonePage(self.container, self.cfg, self._close)

    def _config_page(self):
        return {"create":        self._p_create,
                "hotfix-create": self._p_hf_create,
                "hotfix-apply":  self._p_hf_apply}.get(self.cfg.mode, self._p_promote)

    def _all_pages(self):
        return [self._p_mode, self._p_create, self._p_promote,
                self._p_hf_create, self._p_hf_apply, self._p_run, self._p_done]

    def _show(self, idx):
        for p in self._all_pages(): p.place_forget()

        if idx == 0:
            page = self._p_mode
        elif idx == 1:
            page = self._config_page()
        elif idx == 2:
            page = self._p_run
        else:
            page = self._p_done

        page.place(x=0, y=0, relwidth=1, relheight=1)
        page.on_enter()
        self.sidebar.set(idx)
        self._idx = idx

        if idx == 3:            # Done
            self.btn_next.pack_forget()
            self.btn_finish.pack(side="right")
            self.btn_back.set_enabled(False)
            self.btn_cancel.set_enabled(False)
        elif idx == 2:          # Run
            self.btn_next.pack_forget()
            self.btn_finish.pack_forget()
            self.btn_back.set_enabled(False)
            self.btn_cancel.set_enabled(False)
        else:
            self.btn_finish.pack_forget()
            self.btn_next.pack(side="right")
            self.btn_next.configure_text("▶  Esegui" if idx == 1 else "Avanti  ▶")
            self.btn_back.set_enabled(idx > 0)
            self.btn_cancel.set_enabled(True)

    def _next(self):
        p = self._p_mode if self._idx == 0 else self._config_page()
        if p.validate():
            p.on_leave()
            self._show(self._idx + 1)

    def _back(self):
        if self._idx > 0: self._show(self._idx - 1)

    def _close(self):
        try: self.root.quit()
        except: pass
        try: self.root.destroy()
        except: pass

    def _cancel(self):
        if messagebox.askyesno("Annulla", "Uscire da Gestione Release?"): self._close()

    def _on_done(self):
        self._show(3)
        # Il countdown e la chiusura automatica sono gestiti da ReleaseDonePage._start_countdown()


# ─────────────────────────────────────────────────────────────
# UNINSTALL
# ─────────────────────────────────────────────────────────────

class UninstallConfigPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Disinstalla ambiente",
                         "Rimuove il sito IIS e l'App Pool dell'ambiente selezionato")
        self.cfg = cfg
        self._base = tk.StringVar(value=r"C:\PortaleNovicrom")
        self._delete_files = tk.BooleanVar(value=False)
        b = self.body

        frame(b, height=8).pack()
        sec = frame(b)
        sec.pack(fill="x", padx=32)

        tk.Label(sec, text="Ambiente da disinstallare", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,8))

        env_opts = [
            ("test", "TEST",
             "Rimuove PortaleNovicrom-TEST site e App Pool",
             (YELLOW_BG, YELLOW_BD, YELLOW_TX)),
            ("prod", "PROD",
             "Rimuove PortaleNovicrom-PROD site e App Pool",
             (GREEN_BG, GREEN_BD, "#166534")),
        ]
        self._env_sel = CardSelector(sec, env_opts, initial="test")
        self._env_sel.pack(fill="x")

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        tk.Label(sec, text="Directory base server", font=(SF,9,"bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0,4))
        row = frame(sec)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._base, font=FMO,
                 relief="flat", bg=GRAY50, fg=GRAY800,
                 highlightthickness=1, highlightbackground=GRAY200,
                 highlightcolor=BRAND).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)
        SecondaryButton(row, "  Sfoglia  ",
                        lambda: self._base.set(filedialog.askdirectory() or self._base.get())
                        ).pack(side="left", padx=(8,0))

        frame(sec, bg=GRAY100, height=1).pack(fill="x", pady=12)

        chk_row = frame(sec)
        chk_row.pack(fill="x")
        tk.Checkbutton(chk_row,
                       text="  Elimina anche i file dell'ambiente  (releases, venv, static, media, logs)",
                       variable=self._delete_files,
                       font=FN, bg="white", fg=GRAY700,
                       activebackground="white", selectcolor="white").pack(anchor="w")

        warn = frame(sec, bg=YELLOW_BG, highlightthickness=1, highlightbackground=YELLOW_BD)
        warn.pack(fill="x", pady=(12,0))
        tk.Label(warn,
                 text="⚠   L'eliminazione dei file è irreversibile. Il database non viene toccato.",
                 font=FSM, bg=YELLOW_BG, fg=YELLOW_TX).pack(anchor="w", padx=14, pady=10)

    def validate(self):
        self.cfg.environment   = self._env_sel.value
        self.cfg.base_dir      = self._base.get().strip()
        self.cfg.delete_files  = self._delete_files.get()
        return bool(self.cfg.base_dir)


class UninstallConfirmPage(Page):
    def __init__(self, parent, cfg):
        super().__init__(parent, "Conferma disinstallazione", "")
        self.cfg = cfg
        b = self.body
        frame(b, height=8).pack()
        self._txt = tk.Text(b, font=FMO, bg=CODE_BG, fg=CODE_FG,
                             relief="flat", state="disabled",
                             padx=14, pady=10, spacing1=2, cursor="arrow")
        self._txt.pack(fill="both", expand=True, padx=32)
        self._txt.tag_configure("h",  foreground="#58a6ff", font=("Consolas",9,"bold"))
        self._txt.tag_configure("v",  foreground="#f85149")
        self._txt.tag_configure("ok", foreground="#7ee787")
        self._txt.tag_configure("dim",foreground="#8b949e")

    def on_enter(self):
        cfg = self.cfg
        ep  = Path(cfg.base_dir) / cfg.environment
        t   = self._txt
        t.configure(state="normal"); t.delete("1.0", "end")

        def h(s): t.insert("end", f"\n  {s}\n", "h")
        def rv(k, v): t.insert("end", f"  {k:<28}", "dim"); t.insert("end", f"{v}\n", "v")
        def ok(s):    t.insert("end", f"  {s}\n", "ok")

        h("── Verrà rimosso ───────────────────────────────")
        rv("Sito IIS:",      f"PortaleNovicrom-{cfg.environment.upper()}")
        rv("App Pool:",      f"PortaleNovicrom-{cfg.environment.upper()}")
        if cfg.delete_files:
            rv("Directory:", str(ep))

        h("── NON verrà toccato ───────────────────────────")
        ok("  Il database SQL Server")
        ok("  IIS (gli altri siti continuano a funzionare)")
        if not cfg.delete_files:
            ok(f"  I file in {ep}")

        h("── Consiglio ────────────────────────────────────")
        t.insert("end", "  Esegui un backup del database SQL Server prima di procedere\n", "dim")
        t.insert("end", "  se prevedi di reinstallare o migrare l'installazione.\n", "dim")

        t.insert("end", "\n")
        t.configure(state="disabled")


class UninstallRunPage(Page):
    def __init__(self, parent, cfg, on_done):
        super().__init__(parent, "Disinstallazione in corso", "")
        self.cfg = cfg; self._on_done = on_done; self._started = False
        self._log_file = None; self._log_path = None
        b = self.body
        frame(b, height=8).pack()

        self._step_var = tk.StringVar(value="Inizializzazione…")
        tk.Label(b, textvariable=self._step_var,
                 font=(SF,10,"bold"), fg=BRAND, bg="white").pack(anchor="w", padx=32)

        frame(b, height=6).pack()
        self._pb_frame = frame(b, bg=GRAY100, height=8)
        self._pb_frame.pack(fill="x", padx=32)
        self._pb_fill = frame(self._pb_frame, bg=RED, height=8)
        self._pb_fill.place(x=0, y=0, relheight=1, width=0)
        self._pb_pct = tk.StringVar(value="0%")
        tk.Label(b, textvariable=self._pb_pct, font=FSM,
                 fg=GRAY400, bg="white").pack(anchor="e", padx=32, pady=(3,8))

        wrap = frame(b, bg=CODE_BG)
        wrap.pack(fill="both", expand=True, padx=32, pady=(0,4))
        sb = tk.Scrollbar(wrap); sb.pack(side="right", fill="y")
        self._log = tk.Text(wrap, font=FMO, bg=CODE_BG, fg=CODE_FG,
                             relief="flat", state="disabled",
                             yscrollcommand=sb.set, padx=12, pady=8, spacing1=1)
        self._log.pack(fill="both", expand=True)
        sb.config(command=self._log.yview)
        self._log.tag_configure("ok",   foreground="#7ee787")
        self._log.tag_configure("err",  foreground="#f85149")
        self._log.tag_configure("warn", foreground="#fbbf24")
        self._log.tag_configure("step", foreground="#58a6ff", font=("Consolas",9,"bold"))
        self._log.tag_configure("dim",  foreground="#484f58")

    def on_enter(self):
        if not self._started:
            self._started = True
            self._open_log_file()
            threading.Thread(target=self._run, daemon=True).start()

    def _open_log_file(self):
        try:
            if getattr(sys, 'frozen', False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).parent
            log_dir = base / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_path = log_dir / f"uninstall_{self.cfg.environment}_{ts}.log"
            f = open(self._log_path, "w", encoding="utf-8")
            try:
                f.write(f"Portale Novicrom — Disinstallazione\n")
                f.write(f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                f.write(f"Ambiente: {self.cfg.environment.upper()}\n")
                f.write("=" * 60 + "\n\n")
                f.flush()
            except Exception:
                f.close()
                raise
            self._log_file = f
        except Exception:
            self._log_file = None

    def _log_line(self, text, tag=""):
        if self._log_file:
            try: self._log_file.write(text + "\n"); self._log_file.flush()
            except: pass
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", text+"\n", tag)
            self._log.see("end"); self._log.configure(state="disabled")
        self._log.after(0, _do)

    def _set_progress(self, pct, label=""):
        def _do():
            self._step_var.set(label or self._step_var.get())
            self._pb_pct.set(f"{pct}%")
            self._pb_frame.update_idletasks()
            w = self._pb_frame.winfo_width()
            self._pb_fill.place(width=int(w * pct / 100))
        self._log.after(0, _do)

    def _run(self):
        """Wrapper crash-safe: garantisce che _on_done sia sempre chiamato."""
        try:
            self._run_impl()
        except Exception as e:
            self._log_line(f"\n✗ Errore critico imprevisto: {e}", "err")
            self._log_line(traceback.format_exc(), "err")
            if self._log_file:
                try: self._log_file.close()
                except: pass
            self._log.after(800, self._on_done)

    def _run_impl(self):
        cfg  = self.cfg
        env  = cfg.environment.upper()
        site = f"PortaleNovicrom-{env}"
        pool = f"PortaleNovicrom-{env}"
        ep   = Path(cfg.base_dir) / cfg.environment
        errors = []

        def step(title, pct):
            self._set_progress(pct, title)
            self._log_line(f"\n── {title} {'─'*(44-len(title))}", "step")

        # 0. Backup pre-disinstallazione (non bloccante)
        step("Backup pre-disinstallazione", 5)
        self._run_pre_uninstall_backup(cfg, ep)

        # 1. Ferma e rimuovi sito IIS
        step("Rimozione sito IIS", 20)
        ps_site = f"""
Import-Module WebAdministration -ErrorAction SilentlyContinue
if (Test-Path 'IIS:\\Sites\\{site}') {{
    Stop-Website  -Name '{site}' -ErrorAction SilentlyContinue
    Remove-Website -Name '{site}'
    Write-Host 'OK sito rimosso'
}} else {{
    Write-Host 'SKIP sito non trovato'
}}
"""
        try:
            r = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_site],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW)
            out = (r.stdout + r.stderr).strip()
            if "OK" in out:
                self._log_line(f"  ✓ Sito IIS {site} rimosso", "ok")
            elif "SKIP" in out:
                self._log_line(f"  — Sito IIS {site} non trovato (già rimosso?)", "warn")
            else:
                self._log_line(f"  ✗ {out[:200]}", "err"); errors.append("sito IIS")
        except Exception as e:
            self._log_line(f"  ✗ {e}", "err"); errors.append(str(e))

        # 2. Ferma e rimuovi App Pool
        step("Rimozione App Pool", 55)
        ps_pool = f"""
Import-Module WebAdministration -ErrorAction SilentlyContinue
if (Test-Path 'IIS:\\AppPools\\{pool}') {{
    Stop-WebAppPool    -Name '{pool}' -ErrorAction SilentlyContinue
    Remove-WebAppPool  -Name '{pool}'
    Write-Host 'OK pool rimosso'
}} else {{
    Write-Host 'SKIP pool non trovato'
}}
"""
        try:
            r = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_pool],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW)
            out = (r.stdout + r.stderr).strip()
            if "OK" in out:
                self._log_line(f"  ✓ App Pool {pool} rimosso", "ok")
            elif "SKIP" in out:
                self._log_line(f"  — App Pool {pool} non trovato (già rimosso?)", "warn")
            else:
                self._log_line(f"  ✗ {out[:200]}", "err"); errors.append("App Pool")
        except Exception as e:
            self._log_line(f"  ✗ {e}", "err"); errors.append(str(e))

        # 3. Elimina file (opzionale)
        if getattr(cfg, 'delete_files', False):
            step("Eliminazione file ambiente", 78)
            if ep.exists():
                try:
                    # Rimuovi prima la junction current (rmdir /s fallisce sulle junction)
                    cur = ep / "current"
                    if cur.exists() or cur.is_symlink():
                        subprocess.run(["cmd", "/c", f"rmdir \"{cur}\""],
                                       capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                        self._log_line("  ✓ Junction current rimossa", "ok")
                    shutil.rmtree(ep)
                    self._log_line(f"  ✓ Directory {ep} eliminata", "ok")
                except Exception as e:
                    self._log_line(f"  ✗ {e}", "err"); errors.append(str(e))
            else:
                self._log_line(f"  — Directory {ep} non trovata", "warn")
        else:
            self._log_line("\n  File lasciati intatti.", "dim")

        self._set_progress(100, "Disinstallazione completata")
        self._log_line("\n" + "─"*50, "step")
        if errors:
            self._log_line(f"  Completato con {len(errors)} errori:", "warn")
            for e in errors: self._log_line(f"  · {e}", "warn")
        else:
            self._log_line(f"  Ambiente {env} rimosso da IIS.", "ok")
            self._log_line("  IIS e gli altri siti non sono stati toccati.", "ok")
        self._log_line("─"*50, "step")
        if self._log_path:
            self._log_line(f"  Log salvato in: {self._log_path}", "dim")
        if self._log_file:
            try: self._log_file.close()
            except: pass
        self._log.after(800, self._on_done)

    def _run_pre_uninstall_backup(self, cfg, ep):
        """Esegue backup-environment.ps1 prima di rimuovere l'ambiente (non bloccante)."""
        scripts_dir = Path(cfg.base_dir) / "shared" / "scripts"
        script      = scripts_dir / "backup-environment.ps1"

        if not script.exists():
            self._log_line("  ⚠ backup-environment.ps1 non trovato — backup saltato", "warn")
            self._log_line(f"    (atteso in: {scripts_dir})", "dim")
            return

        self._log_line(f"  → Eseguendo {script.name} per {cfg.environment.upper()}…", "dim")
        try:
            r = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Environment", cfg.environment],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=180, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                self._log_line("  ✓ Backup pre-disinstallazione completato", "ok")
                # Mostra la directory di destinazione dall'output dello script
                for line in out.splitlines():
                    if "Destinazione" in line or "completato" in line.lower():
                        self._log_line(f"    {line.strip()}", "dim")
            else:
                self._log_line(f"  ⚠ Backup completato con avvisi (continuo)", "warn")
                if out:
                    self._log_line(f"    {out[:300]}", "dim")
        except subprocess.TimeoutExpired:
            self._log_line("  ⚠ Backup timeout (>3 min) — continuo con la disinstallazione", "warn")
        except Exception as e:
            self._log_line(f"  ⚠ Backup fallito: {e} — continuo", "warn")


class UninstallDonePage(Page):
    def __init__(self, parent, cfg, on_close=None):
        super().__init__(parent, "Disinstallazione completata", "")
        self.cfg = cfg
        self._on_close = on_close
        b = self.body
        frame(b, height=16).pack()
        self._msg = tk.Label(b, text="", font=(SF,13,"bold"),
                              fg=GRAY700, bg="white", wraplength=560, justify="left")
        self._msg.pack(padx=32, anchor="w")
        frame(b, bg=GRAY100, height=1).pack(fill="x", padx=32, pady=16)
        self._hints = frame(b)
        self._hints.pack(fill="x", padx=32)
        frame(b, height=16).pack()
        self._countdown_lbl = tk.Label(b, text="", font=FSM, fg=GRAY400, bg="white")
        self._countdown_lbl.pack(padx=32, anchor="w")
        tk.Label(b, text="Portale Novicrom · Costruzioni Novicrom SRL",
                 font=FSM, fg=GRAY400, bg="white").pack(padx=32, anchor="w", pady=(4,0))

    def on_enter(self):
        for w in self._hints.winfo_children(): w.destroy()
        env = self.cfg.environment.upper()
        self._msg.configure(text=f"Ambiente {env} rimosso da IIS.")
        hints = [
            f"Il sito PortaleNovicrom-{env} e l'App Pool sono stati eliminati",
            "IIS è ancora attivo — gli altri siti non sono stati toccati",
            "Il database SQL Server non è stato modificato",
        ]
        for i, hint in enumerate(hints, 1):
            row = frame(self._hints)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=str(i), font=(SF,9,"bold"), bg=GRAY700, fg="white",
                     width=2, pady=4).pack(side="left", padx=(0,12))
            tk.Label(row, text=hint, font=FN, fg=GRAY600, bg="white").pack(side="left")
        self._start_countdown(15)

    def _start_countdown(self, n):
        if n <= 0:
            self._countdown_lbl.configure(text="Chiusura in corso…")
            if self._on_close:
                try: self._on_close()
                except: pass
            return
        self._countdown_lbl.configure(
            text=f"La finestra si chiuderà automaticamente tra {n} second{'o' if n==1 else 'i'}…")
        self.after(1000, lambda: self._start_countdown(n - 1))


class UninstallApp:
    def __init__(self, initial_env=None):
        self.cfg  = Config()
        self._idx = 0
        if initial_env:
            self.cfg.environment = initial_env
        self.cfg.delete_files = False

        self.root = tk.Tk()
        self.root.title("Portale Novicrom — Disinstalla")
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)
        self.root.configure(bg="white")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - WIN_W) // 2
        y = (self.root.winfo_screenheight() - WIN_H) // 2 - 20
        self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
        self._build()
        self._show(0)
        self.root.mainloop()

    def _build(self):
        main = frame(self.root)
        main.pack(fill="both", expand=True)
        self.sidebar = Sidebar(main, steps=STEPS_UNINSTALL, subtitle="Disinstalla")
        self.sidebar.pack(side="left", fill="y")

        right = frame(main)
        right.pack(side="left", fill="both", expand=True)
        self.container = frame(right)
        self.container.pack(fill="both", expand=True)

        (self.btn_back, self.btn_cancel,
         self.btn_next, self.btn_finish) = _build_bottom_bar(
            right, self._back, self._cancel, self._next, self._close,
            next_bg=RED, finish_bg=GRAY700)

        self._p_config  = UninstallConfigPage(self.container, self.cfg)
        self._p_confirm = UninstallConfirmPage(self.container, self.cfg)
        self._p_run     = UninstallRunPage(self.container, self.cfg, self._on_done)
        self._p_done    = UninstallDonePage(self.container, self.cfg, self._close)
        self._pages     = [self._p_config, self._p_confirm, self._p_run, self._p_done]

    def _show(self, idx):
        for p in self._pages: p.place_forget()
        self._pages[idx].place(x=0, y=0, relwidth=1, relheight=1)
        self._pages[idx].on_enter()
        self.sidebar.set(idx)
        self._idx = idx

        if idx == 3:        # Done
            self.btn_next.pack_forget()
            self.btn_finish.pack(side="right")
            self.btn_back.set_enabled(False)
            self.btn_cancel.set_enabled(False)
        elif idx == 2:      # Run
            self.btn_next.pack_forget()
            self.btn_finish.pack_forget()
            self.btn_back.set_enabled(False)
            self.btn_cancel.set_enabled(False)
        else:
            self.btn_finish.pack_forget()
            self.btn_next.pack(side="right")
            lbl = "⚠  Disinstalla" if idx == 1 else "Avanti  ▶"
            self.btn_next.configure_text(lbl)
            self.btn_back.set_enabled(idx > 0)
            self.btn_cancel.set_enabled(True)

    def _next(self):
        if self._pages[self._idx].validate():
            self._pages[self._idx].on_leave()
            self._show(self._idx + 1)

    def _back(self):
        if self._idx > 0: self._show(self._idx - 1)

    def _close(self):
        try: self.root.quit()
        except: pass
        try: self.root.destroy()
        except: pass

    def _cancel(self):
        if messagebox.askyesno("Annulla", "Uscire?"): self._close()

    def _on_done(self):
        self._show(3)
        # Il countdown e la chiusura automatica sono gestiti da UninstallDonePage._start_countdown()


# ─────────────────────────────────────────────────────────────
# SERVER DASHBOARD — pannello di controllo offline
# ─────────────────────────────────────────────────────────────

class ServerDashboard:
    """Dashboard offline per gestire i siti IIS di Portale Novicrom.

    Può essere aperto standalone (parent=None, crea tk.Tk) oppure
    come finestra sopra il wizard (parent=Toplevel, crea tk.Toplevel).
    """

    BASE_DIR  = r"C:\PortaleNovicrom"
    ENVS      = ["test", "prod"]
    REFRESH_MS = 5000   # auto-refresh ogni 5 secondi

    # Servizi Windows rilevanti per l'hosting del portale (pattern -like).
    SERVICE_PATTERNS = [
        "W3SVC", "WAS", "AppHostSvc", "IISADMIN",
        "MSSQL*", "SQLAgent*", "SQLSERVERAGENT", "SQLBrowser",
        "SQLTELEMETRY*", "MsDtsServer*", "SQLWriter",
    ]
    _SVC_STATUS = {
        "Running":      ("▶ In servizio", GREEN),
        "Stopped":      ("■ Arrestato",   RED),
        "StartPending": ("… Avvio",       YELLOW_TX),
        "StopPending":  ("… Arresto",     YELLOW_TX),
        "Paused":       ("⏸ In pausa",    YELLOW_TX),
    }
    _SVC_STARTTYPE = {
        "Automatic": ("Automatico",  GRAY700),
        "Manual":    ("Manuale",     GRAY600),
        "Disabled":  ("Disattivato", RED),
        "Boot":      ("Boot",        GRAY600),
        "System":    ("System",      GRAY600),
    }

    def __init__(self, parent=None):
        self._standalone = (parent is None)
        if self._standalone:
            self.root = tk.Tk()
        else:
            self.root = tk.Toplevel(parent)
        self.root.title("Portale Novicrom — Server Dashboard")
        self.root.configure(bg="white")
        self.root.resizable(True, True)

        W, H = 920, 880
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{max(0,(sh-H)//2 - 20)}")
        self.root.minsize(860, 780)

        self._selected_env = tk.StringVar(value="test")
        self._status_data: dict = {}
        self._after_id = None
        self._admin_mode = is_admin()
        self._terminal_proc = None
        self._terminal_running = False
        self._terminal_lock = threading.Lock()
        # 4-tupla: (etichetta con emoji rischio 🟢/🟡/🔴 in stile RUNBOOK_COMANDI.md,
        # comando, descrizione breve, placeholder file o None). Il placeholder
        # "<file>" viene sostituito dal pulsante "Sfoglia file..." nel terminale.
        self._terminal_presets = [
            # Test & quality gate
            ("🟢 Test · Django check", "manage.py check --settings=config.settings.prod",
             "System check (config/modelli)", None),
            ("🟢 Test · Stato migrations", "manage.py showmigrations --settings=config.settings.prod",
             "Mostra lo stato delle migrazioni per app", None),
            ("🟡 Test · Migrate", "manage.py migrate --settings=config.settings.prod --noinput",
             "Applica le migrazioni pendenti", None),
            ("🟡 Test · Collectstatic dry-run", "manage.py collectstatic --dry-run --noinput --clear --settings=config.settings.prod -v 0",
             "Anteprima raccolta static (nessuna scrittura)", None),
            ("🟢 Test · Migrazioni mancanti", "manage.py makemigrations --check --settings=config.settings.prod",
             "Verifica che non manchino migrazioni da generare", None),
            ("🟢 Test · Secret hygiene check", "manage.py secret_hygiene_check --settings=config.settings.prod",
             "Scansiona i file Git per segreti/path sensibili hardcoded", None),
            ("🟢 Test · Valida deploy", "manage.py validate_deployment --format json --settings=config.settings.prod",
             "Valida la configurazione di deploy", None),
            # ACL v2
            ("🟢 ACL · Bootstrap dry-run", "manage.py bootstrap_acl_v2 --dry-run --settings=config.settings.prod",
             "Anteprima bootstrap permessi/binding canonici ACL v2", None),
            ("🟡 ACL · Bootstrap apply legacy", "manage.py bootstrap_acl_v2 --import-legacy --apply --settings=config.settings.prod",
             "Applica il bootstrap ACL v2 importando i grant legacy", None),
            ("🟢 ACL · Route non gated", "manage.py acl_fallback_report --only-unbound --settings=config.settings.prod",
             "Route senza binding canonico (debito ACL)", None),
            ("🟢 ACL · Copertura canonica", "manage.py acl_coverage_report --max-missing 222 --settings=config.settings.prod",
             "Copertura ACL canonica sulle route registrate", None),
            ("🟢 ACL · Diagnosi route", "manage.py acl_diagnose --settings=config.settings.prod",
             "Diagnosi accesso route (canonico vs legacy)", None),
            ("🟢 ACL · Prontezza modalità strict", "manage.py acl_strict_readiness --settings=config.settings.prod",
             "Verifica prontezza per ACL_STRICT_CANONICAL=True", None),
            # AI / RAG
            ("🟢 AI/RAG · Ricostruisci indice SGI", "manage.py index_sgi_documents --settings=config.settings.prod",
             "Ricostruisce l'indice RAG + warm embeddings del corpus SGI", None),
            ("🟢 AI/RAG · Valuta recall RAG", "manage.py ai_eval --rag --settings=config.settings.prod",
             "Valuta recall@k del RAG su golden query", None),
            ("🟢 AI/RAG · Warmup Ollama", "manage.py warmup_ollama --settings=config.settings.prod",
             "Pre-carica il modello chat Ollama (evita cold-start)", None),
            ("🟢 AI/RAG · Health-check AI", "manage.py monitoring_ai_alert --settings=config.settings.prod",
             "Health-check AI (Ollama/TEI) + alert email su degrado", None),
            # Presa Visione / corpus SGI
            ("🟢 SGI · Import da share (dry-run)", "manage.py import_sgi_da_share --settings=config.settings.prod",
             "Dry-run: scandisce la share SGI e mostra cosa importerebbe", None),
            ("🟡 SGI · Import da share (apply)", "manage.py import_sgi_da_share --apply --settings=config.settings.prod",
             "Scrive: registra documenti + revisioni correnti nel DB", None),
            # MOD.128 MPQ
            ("🟢 MPQ · Import MOD.128 (dry-run)", "manage.py import_mod128 --pdf <file> --settings=config.settings.prod",
             "Dry-run: importa il MOD.128 dal PDF nei modelli MPQ", "<file>"),
            ("🟢 MPQ · Propaga timbri (dry-run)", "manage.py mpq_propaga_timbri --dry-run --settings=config.settings.prod",
             "Anteprima: sospende/riattiva i timbri collegati alle abilitazioni", None),
            # Skill Matrix MOD.187
            ("🟢 Skill Matrix · Report match asset", "manage.py skm_asset_match_report --settings=config.settings.prod",
             "Report match competenza↔macchina → asset (sola lettura)", None),
            ("🟡 Skill Matrix · Sincronizza catalogo", "manage.py skm_seed_catalogo --settings=config.settings.prod",
             "Sincronizza il catalogo competenze dagli asset live", None),
            # Reminder / digest (schedulati — utile per test manuale)
            ("🟡 Reminder · Scadenze DPI", "manage.py send_dpi_expiry_reminders --settings=config.settings.prod",
             "Digest DPI scaduti/in scadenza", None),
            ("🟡 Reminder · Scadenze formazione", "manage.py send_training_expiry_reminders --settings=config.settings.prod",
             "Reminder corsi formazione in scadenza", None),
            ("🟡 Reminder · SLA ticket", "manage.py send_sla_reminders --settings=config.settings.prod",
             "Reminder ticket con SLA scaduto", None),
            # Import dati (con file)
            ("🟢 Import · Dipendenti da Excel (dry-run)", "manage.py import_dipendenti_xlsx <file> --dry-run --settings=config.settings.prod",
             "Anagrafica dipendenti da Excel — anteprima senza scrivere", "<file>"),
            ("🟡 Import · Cedolini (dry-run)", "manage.py import_cedolini <file> --dry-run --settings=config.settings.prod",
             "Saldi ferie/ROL/ex-festività da XLSX — anteprima", "<file>"),
            ("🟢 Import · SMS storico · converti CSV→JSON", "manage.py converti_sms_storico --file <file> --out %TEMP%\\sms_storico.json --settings=config.settings.prod",
             "Suggestion Corner: converte il «Registro SMS» storico nel JSON per l'import (sola lettura anagrafica)", "<file>"),
            ("🟡 Import · SMS storico (dry-run)", "manage.py import_suggestion_corner_legacy --file <file> --settings=config.settings.prod",
             "Suggestion Corner: importa i record storici dal JSON — anteprima (aggiungi --apply per scrivere)", "<file>"),
            # Manutenzione / GDPR
            ("🟢 Manutenzione · Audit media", "manage.py media_audit --settings=config.settings.prod",
             "Segnala file sensibili in MEDIA_ROOT (servito senza auth)", None),
            ("🟢 Manutenzione · Reparti orfani", "manage.py report_reparti_orfani --settings=config.settings.prod",
             "Elenca i dipendenti con reparto legacy orfano", None),
            ("🟡 Manutenzione · Backup portale", "manage.py backup_portale --settings=config.settings.prod",
             "Backup DB + config + file del portale", None),
            # Sincronizzazioni sorgenti esterne
            ("🟡 Sync · LDAP utenti", "manage.py sync_ldap_users --settings=config.settings.prod",
             "Importa utenti da LDAP/AD → legacy + auth_user + gruppi", None),
            # Utility varie
            ("🟡 Utility · Seed descrizioni pulsanti", "manage.py seed_pulsanti_descrizioni --settings=config.settings.prod",
             "Popola le descrizioni dei pulsanti/help contestuale", None),
            ("🟡 Automazioni · Migra django-q", "manage.py migrate django_q --noinput --settings=config.settings.prod",
             "Applica le migrazioni della coda django-q2", None),
            ("🟡 Automazioni · Registra schedule", "manage.py setup_q_schedules --settings=config.settings.prod",
             "Registra/aggiorna gli Schedule django-q2 (reminder/digest)", None),
        ]
        # Servizi Windows — widget refs (impostati in _build)
        self._svc_rows: dict = {}
        self._svc_container: tk.Frame | None = None
        self._svc_scroll: "ScrollableFrame | None" = None
        self._svc_summary_lbl: tk.Label | None = None
        # Automazioni django-q — widget refs (impostati in _build)
        self._q_status_lbl: tk.Label | None = None
        self._q_log_txt: tk.Text | None = None
        self._q_start_btn: "SecondaryButton | None" = None
        self._q_stop_btn: "SecondaryButton | None" = None
        # Pagina scrollabile + sezioni target dei blocchi di navigazione
        self._page_canvas: "tk.Canvas | None" = None
        self._page_sb: "tk.Scrollbar | None" = None
        self._page_content: "tk.Frame | None" = None
        self._page_win = None
        self._sec_status = self._sec_svc = self._sec_ctrl = None
        self._sec_q = self._sec_ai = self._sec_log = self._sec_term = None

        self._build()
        self._refresh()
        if self._standalone:
            self.root.mainloop()

    def _build(self):
        # ── Header ───────────────────────────────────────────────
        hdr = frame(self.root, bg=BRAND_DARK, height=56)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="Portale Novicrom", font=(SF, 13, "bold"),
                 bg=BRAND_DARK, fg="white").pack(side="left", padx=20, pady=14)
        tk.Label(hdr, text="Server Dashboard", font=(SF, 9),
                 bg=BRAND_DARK, fg="#bfdbfe").pack(side="left")

        # ── Env tabs ─────────────────────────────────────────────
        tab_row = frame(self.root, bg=GRAY50,
                        highlightthickness=1, highlightbackground=GRAY200)
        tab_row.pack(fill="x")
        self._tab_btns = {}
        for env in self.ENVS:
            btn = tk.Label(tab_row, text=env.upper(), font=(SF, 9, "bold"),
                           bg=GRAY50, fg=GRAY600, cursor="hand2",
                           padx=18, pady=8)
            btn.pack(side="left")
            btn.bind("<Button-1>", lambda e, v=env: self._select_env(v))
            self._tab_btns[env] = btn

        # ── Main area (pagina scrollabile) ───────────────────────
        page_wrap = frame(self.root, bg="white")
        page_wrap.pack(fill="both", expand=True)
        self._page_canvas = tk.Canvas(page_wrap, bg="white",
                                      highlightthickness=0, bd=0)
        self._page_sb = tk.Scrollbar(page_wrap, orient="vertical",
                                     command=self._page_canvas.yview)
        self._page_canvas.configure(yscrollcommand=self._page_sb.set)
        self._page_sb.pack(side="right", fill="y")
        self._page_canvas.pack(side="left", fill="both", expand=True)
        self._page_content = frame(self._page_canvas, bg="white")
        self._page_win = self._page_canvas.create_window(
            (0, 0), window=self._page_content, anchor="nw")
        self._page_content.bind("<Configure>", self._on_page_content_config)
        self._page_canvas.bind("<Configure>", self._on_page_canvas_config)

        main = frame(self._page_content, bg="white")
        main.pack(fill="both", expand=True, padx=24, pady=16)

        # ── Pannello di controllo (blocchi di navigazione) ───────
        self._build_nav_blocks(main)

        # Status panel
        status_frame = frame(main, bg=GRAY50,
                              highlightthickness=1, highlightbackground=GRAY200)
        status_frame.pack(fill="x")
        self._sec_status = status_frame
        tk.Label(status_frame, text="Stato servizi", font=(SF, 9, "bold"),
                 bg=GRAY50, fg=GRAY600).pack(anchor="w", padx=14, pady=(10, 6))

        grid = frame(status_frame, bg=GRAY50)
        grid.pack(fill="x", padx=14, pady=(0, 10))
        for col, lbl in enumerate(["Componente", "Stato", "URL / Note"]):
            tk.Label(grid, text=lbl, font=(SF, 8, "bold"), fg=GRAY400,
                     bg=GRAY50, width=18 if col == 0 else 12,
                     anchor="w").grid(row=0, column=col, sticky="w")
        self._rows: list[tuple] = []
        for r_idx, (comp, _) in enumerate([("Sito IIS", ""), ("App Pool", ""), ("URL", "")], 1):
            lbl_comp = tk.Label(grid, text=comp, font=FSM, fg=GRAY700, bg=GRAY50,
                                width=18, anchor="w")
            lbl_comp.grid(row=r_idx, column=0, sticky="w", pady=2)
            lbl_val  = tk.Label(grid, text="—", font=FSM, fg=GRAY500, bg=GRAY50,
                                width=12, anchor="w")
            lbl_val.grid(row=r_idx, column=1, sticky="w")
            lbl_note = tk.Label(grid, text="", font=FSM, fg=BRAND, bg=GRAY50,
                                cursor="hand2", anchor="w")
            lbl_note.grid(row=r_idx, column=2, sticky="w")
            self._rows.append((lbl_comp, lbl_val, lbl_note))

        # ── Servizi Windows ──────────────────────────────────────
        frame(main, height=14).pack()
        svc_card = frame(main, bg=GRAY50,
                         highlightthickness=1, highlightbackground=GRAY200)
        svc_card.pack(fill="x")
        self._sec_svc = svc_card

        svc_head = frame(svc_card, bg=GRAY50)
        svc_head.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(svc_head, text="Servizi Windows", font=(SF, 9, "bold"),
                 bg=GRAY50, fg=GRAY600).pack(side="left")
        self._svc_summary_lbl = tk.Label(svc_head, text="—", font=FSM,
                                         bg=GRAY50, fg=GRAY400)
        self._svc_summary_lbl.pack(side="right")

        svc_hdr = frame(svc_card, bg=GRAY50)
        svc_hdr.pack(fill="x", padx=14)
        for txt, w in (("Servizio", 32), ("Stato", 14), ("Avvio", 13), ("Gestione", 10)):
            tk.Label(svc_hdr, text=txt, font=(SF, 8, "bold"), fg=GRAY400,
                     bg=GRAY50, width=w, anchor="w").pack(side="left")

        svc_list = ScrollableFrame(svc_card, bg=GRAY50, height=132)
        svc_list.pack(fill="x", padx=14, pady=(2, 4))
        svc_list.pack_propagate(False)
        self._svc_container = svc_list.inner
        self._svc_scroll = svc_list
        tk.Label(self._svc_container, text="Rilevamento servizi in corso…",
                 font=FSM, fg=GRAY400, bg=GRAY50).pack(anchor="w", pady=6)

        svc_note = (
            "Avvio/arresto/riavvio e modifica del tipo di avvio agiscono sui servizi reali del server."
            if self._admin_mode
            else "Gestione servizi disabilitata: avvia il setup come Amministratore per agire sui servizi."
        )
        tk.Label(svc_card, text=svc_note, font=FSM,
                 fg=GRAY500 if self._admin_mode else YELLOW_TX,
                 bg=GRAY50, wraplength=820, justify="left").pack(anchor="w", padx=14, pady=(0, 10))

        # ── Control buttons ──────────────────────────────────────
        frame(main, height=14).pack()
        ctrl = frame(main, bg="white")
        ctrl.pack(fill="x")
        self._sec_ctrl = ctrl
        tk.Label(ctrl, text="Controlli", font=(SF, 9, "bold"),
                 fg=GRAY600, bg="white").pack(anchor="w", pady=(0, 8))
        btn_row = frame(ctrl, bg="white")
        btn_row.pack(anchor="w")

        self._btn_start   = PrimaryButton(btn_row, "▶  Avvia",    lambda: self._iis_action("start"),   bg=GREEN)
        self._btn_stop    = PrimaryButton(btn_row, "■  Ferma",    lambda: self._iis_action("stop"),    bg=RED)
        self._btn_restart = PrimaryButton(btn_row, "↺  Riavvia",  lambda: self._iis_action("restart"))
        self._btn_recycle = SecondaryButton(btn_row, "♻  Ricicla Pool", lambda: self._iis_action("recycle"))
        self._btn_browser = SecondaryButton(btn_row, "🌐  Apri browser", self._open_browser)
        self._btn_reset_password = SecondaryButton(btn_row, "🔑  Reset password live", self._open_live_password_reset)
        for b in (self._btn_start, self._btn_stop, self._btn_restart,
                  self._btn_recycle, self._btn_browser, self._btn_reset_password):
            b.pack(side="left", padx=(0, 8))
        if not self._admin_mode:
            self._btn_reset_password.set_enabled(False)

        admin_note = (
            "Reset password live disponibile: aggiorna subito un account locale sull'ambiente attivo."
            if self._admin_mode
            else "Reset password live disponibile solo se il setup e avviato come Administrator."
        )
        admin_note_fg = GRAY500 if self._admin_mode else YELLOW_TX
        tk.Label(ctrl, text=admin_note, font=FSM, fg=admin_note_fg, bg="white").pack(anchor="w", pady=(8, 0))

        # ── Automazioni django-q ─────────────────────────────────
        frame(main, height=14).pack()
        q_card = frame(main, bg=GRAY50, highlightthickness=1, highlightbackground=GRAY200)
        q_card.pack(fill="x")
        self._sec_q = q_card

        q_head_row = frame(q_card, bg=GRAY50)
        q_head_row.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(q_head_row, text="Automazioni (django-q)", font=(SF, 9, "bold"),
                 bg=GRAY50, fg=GRAY600).pack(side="left")
        self._q_status_lbl = tk.Label(q_head_row, text="—", font=FSM,
                                      bg=GRAY50, fg=GRAY400)
        self._q_status_lbl.pack(side="right")

        q_btn_row = frame(q_card, bg=GRAY50)
        q_btn_row.pack(anchor="w", padx=14, pady=(0, 8))
        SecondaryButton(
            q_btn_row, "🗄  Migra django-q",
            lambda: self._q_run_manage(
                "manage.py migrate django_q --noinput --settings=config.settings.prod"
            ),
        ).pack(side="left", padx=(0, 8))
        SecondaryButton(
            q_btn_row, "📅  Registra schedule",
            lambda: self._q_run_manage(
                "manage.py setup_q_schedules --settings=config.settings.prod"
            ),
        ).pack(side="left", padx=(0, 8))
        SecondaryButton(
            q_btn_row, "📋  Installa task",
            self._q_install_task,
        ).pack(side="left", padx=(0, 8))
        self._q_start_btn = SecondaryButton(q_btn_row, "▶  Avvia qcluster",
                                            self._q_start_task)
        self._q_start_btn.pack(side="left", padx=(0, 8))
        self._q_stop_btn = SecondaryButton(q_btn_row, "■  Ferma qcluster",
                                           self._q_stop_task)
        self._q_stop_btn.pack(side="left", padx=(0, 8))

        q_log_wrap = frame(q_card, bg=CODE_BG,
                           highlightthickness=1, highlightbackground=GRAY700)
        q_log_wrap.pack(fill="x", padx=14, pady=(0, 10))
        self._q_log_txt = tk.Text(
            q_log_wrap, bg=CODE_BG, fg=CODE_FG, font=FMO,
            relief="flat", state="disabled", wrap="none", height=4,
        )
        q_log_sb = tk.Scrollbar(q_log_wrap, command=self._q_log_txt.yview)
        self._q_log_txt.configure(yscrollcommand=q_log_sb.set)
        q_log_sb.pack(side="right", fill="y")
        self._q_log_txt.pack(fill="both", expand=True, padx=8, pady=6)

        # ── Assistente AI (Ollama + RAG) ─────────────────────────
        frame(main, height=14).pack()
        ai_card = frame(main, bg=GRAY50, highlightthickness=1, highlightbackground=GRAY200)
        ai_card.pack(fill="x")
        self._sec_ai = ai_card

        ai_head = frame(ai_card, bg=GRAY50)
        ai_head.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(ai_head, text="Assistente AI (Ollama + RAG)", font=(SF, 9, "bold"),
                 bg=GRAY50, fg=GRAY600).pack(side="left")
        self._ai_status_lbl = tk.Label(ai_head, text="— (premi Verifica)", font=FSM,
                                       bg=GRAY50, fg=GRAY400)
        self._ai_status_lbl.pack(side="right")

        ai_btn_row = frame(ai_card, bg=GRAY50)
        ai_btn_row.pack(anchor="w", padx=14, pady=(0, 8))
        SecondaryButton(ai_btn_row, "🔎  Verifica", self._ai_verify).pack(side="left", padx=(0, 8))
        SecondaryButton(ai_btn_row, "🧠  Re-index SGI", self._ai_reindex).pack(side="left", padx=(0, 8))
        SecondaryButton(ai_btn_row, "✎  Modifica config AI", self._ai_edit_config).pack(side="left", padx=(0, 8))

        ai_log_wrap = frame(ai_card, bg=CODE_BG, highlightthickness=1, highlightbackground=GRAY700)
        ai_log_wrap.pack(fill="x", padx=14, pady=(0, 10))
        self._ai_log_txt = tk.Text(ai_log_wrap, bg=CODE_BG, fg=CODE_FG, font=FMO,
                                   relief="flat", state="disabled", wrap="none", height=4)
        self._ai_log_txt.tag_configure("meta", foreground="#58a6ff")
        self._ai_log_txt.tag_configure("error", foreground="#f87171")
        self._ai_log_txt.tag_configure("ok", foreground="#7ee787")
        ai_log_sb = tk.Scrollbar(ai_log_wrap, command=self._ai_log_txt.yview)
        self._ai_log_txt.configure(yscrollcommand=ai_log_sb.set)
        ai_log_sb.pack(side="right", fill="y")
        self._ai_log_txt.pack(fill="both", expand=True, padx=8, pady=6)

        # ── Log viewer ──────────────────────────────────────────
        frame(main, height=14).pack()
        log_title = tk.Label(main, text="Log recente (waitress)", font=(SF, 9, "bold"),
                             fg=GRAY600, bg="white")
        log_title.pack(anchor="w")
        self._sec_log = log_title
        frame(main, height=4).pack()
        log_frame = frame(main, bg=CODE_BG,
                          highlightthickness=1, highlightbackground=GRAY700)
        log_frame.pack(fill="both", expand=True)
        self._log_txt = tk.Text(log_frame, bg=CODE_BG, fg=CODE_FG,
                                 font=FMO, relief="flat", state="disabled",
                                 wrap="none", height=10)
        sb = tk.Scrollbar(log_frame, command=self._log_txt.yview)
        self._log_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_txt.pack(fill="both", expand=True, padx=8, pady=6)

        # Terminale ambiente
        frame(main, height=14).pack()
        term_head = frame(main, bg="white")
        term_head.pack(fill="x")
        self._sec_term = term_head
        tk.Label(term_head, text="Terminale ambiente", font=(SF, 9, "bold"),
                 fg=GRAY600, bg="white").pack(side="left")
        self._terminal_context_lbl = tk.Label(term_head, text="", font=FSM,
                                              fg=GRAY400, bg="white")
        self._terminal_context_lbl.pack(side="right")

        term_cmd_row = frame(main, bg="white")
        term_cmd_row.pack(fill="x", pady=(5, 4))
        preset_values = [label for label, _cmd, _desc, _file in self._terminal_presets]
        self._terminal_preset_var = tk.StringVar(value=preset_values[0])
        self._terminal_preset = ttk.Combobox(
            term_cmd_row,
            textvariable=self._terminal_preset_var,
            values=preset_values,
            state="readonly",
            width=32,
            font=FSM,
        )
        self._terminal_preset.pack(side="left", padx=(0, 8))
        self._terminal_preset.bind("<<ComboboxSelected>>", self._on_terminal_preset)

        self._terminal_cmd_var = tk.StringVar(value=self._terminal_presets[0][1])
        self._terminal_entry = tk.Entry(
            term_cmd_row,
            textvariable=self._terminal_cmd_var,
            font=FMO,
            relief="flat",
            bg=GRAY50,
            fg=GRAY800,
            insertbackground=BRAND,
            highlightthickness=1,
            highlightbackground=GRAY200,
            highlightcolor=BRAND,
        )
        self._terminal_entry.pack(side="left", fill="x", expand=True, ipady=6, ipadx=8)
        self._terminal_entry.bind("<Return>", lambda _e: self._run_terminal_command())
        self._terminal_file_btn = SecondaryButton(term_cmd_row, "📎  Sfoglia file…", self._browse_terminal_file)
        self._terminal_file_btn.pack(side="left", padx=(8, 0))
        self._terminal_file_btn.set_enabled(False)
        self._terminal_run_btn = PrimaryButton(term_cmd_row, "Esegui", self._run_terminal_command)
        self._terminal_run_btn.pack(side="left", padx=(8, 0))
        self._terminal_stop_btn = SecondaryButton(term_cmd_row, "Stop", self._stop_terminal_command)
        self._terminal_stop_btn.pack(side="left", padx=(8, 0))
        self._terminal_stop_btn.set_enabled(False)

        self._terminal_file_token = None
        self._terminal_desc_lbl = tk.Label(main, text="", font=FSM, fg=GRAY500,
                                           bg="white", anchor="w", justify="left",
                                           wraplength=820)
        self._terminal_desc_lbl.pack(fill="x", pady=(0, 6))
        self._on_terminal_preset()

        terminal_frame = frame(main, bg=CODE_BG,
                               highlightthickness=1, highlightbackground=GRAY700)
        terminal_frame.pack(fill="both", expand=True)
        self._terminal_txt = tk.Text(
            terminal_frame,
            bg=CODE_BG,
            fg=CODE_FG,
            font=FMO,
            relief="flat",
            state="disabled",
            wrap="none",
            height=8,
        )
        self._terminal_txt.tag_configure("meta", foreground="#58a6ff")
        self._terminal_txt.tag_configure("error", foreground="#f87171")
        self._terminal_txt.tag_configure("ok", foreground="#7ee787")
        term_sb_y = tk.Scrollbar(terminal_frame, command=self._terminal_txt.yview)
        term_sb_x = tk.Scrollbar(terminal_frame, command=self._terminal_txt.xview, orient="horizontal")
        self._terminal_txt.configure(yscrollcommand=term_sb_y.set, xscrollcommand=term_sb_x.set)
        term_sb_y.pack(side="right", fill="y")
        term_sb_x.pack(side="bottom", fill="x")
        self._terminal_txt.pack(fill="both", expand=True, padx=8, pady=6)
        self._append_terminal(
            "Console pronta. I comandi manage.py usano il virtualenv dell'ambiente selezionato.\n",
            "meta",
        )

        # ── Footer ──────────────────────────────────────────────
        ftr = frame(self.root, bg=GRAY50,
                    highlightthickness=1, highlightbackground=GRAY100)
        ftr.pack(fill="x", side="bottom")
        self._refresh_lbl = tk.Label(ftr, text="", font=FSM, fg=GRAY400, bg=GRAY50)
        self._refresh_lbl.pack(side="left", padx=14, pady=6)
        SecondaryButton(ftr, "🗑  Pulisci release vecchie", self._clean_old_releases).pack(side="right", padx=(0, 8), pady=4)
        SecondaryButton(ftr, "🔄  Aggiorna ora", self._refresh).pack(side="right", padx=14, pady=4)

        # La rotella del mouse scorre la pagina (o l'elenco servizi se è sotto
        # il puntatore). Bind impostato per ultimo così prevale su quello
        # globale dello ScrollableFrame dei servizi.
        self.root.bind_all("<MouseWheel>", self._on_page_wheel)

        self._select_env(self._selected_env.get())

    # ── Navigazione a blocchi + scroll pagina ────────────────────
    def _build_nav_blocks(self, parent):
        """Griglia di blocchi cliccabili che portano alle sezioni sottostanti."""
        blocks = [
            ("🌐", "Stato servizi IIS", "Sito, App Pool e URL dell'ambiente",  "_sec_status", BRAND),
            ("🪟", "Servizi Windows",   "IIS e SQL Server: avvio/arresto",     "_sec_svc",    BRAND_DARK),
            ("🎛", "Controlli IIS",     "Avvia, ferma, riavvia, ricicla pool", "_sec_ctrl",   GREEN),
            ("⚙",  "Automazioni",       "django-q: schedule, qcluster, task",  "_sec_q",      ORANGE),
            ("🧠", "Assistente AI",     "Ollama + RAG: verifica, re-index",    "_sec_ai",     "#7c3aed"),
            ("📜", "Log waitress",      "Output recente del runtime",          "_sec_log",    GRAY600),
            ("💻", "Terminale",         "Comandi manage.py nell'ambiente",     "_sec_term",   GRAY700),
        ]
        head = frame(parent, bg="white")
        head.pack(fill="x")
        tk.Label(head, text="Pannello di controllo", font=(SF, 11, "bold"),
                 fg=GRAY900, bg="white").pack(side="left")
        tk.Label(head, text="Scegli un'area da gestire", font=FSM,
                 fg=GRAY500, bg="white").pack(side="left", padx=(10, 0))

        grid = frame(parent, bg="white")
        grid.pack(fill="x", pady=(10, 0))
        cols = 4
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1, uniform="navcol")
        for i, (icon, title, sub, target, accent) in enumerate(blocks):
            r, c = divmod(i, cols)
            tile = self._make_nav_tile(grid, icon, title, sub, target, accent)
            tile.grid(row=r, column=c, sticky="nsew",
                      padx=(0 if c == 0 else 8, 0),
                      pady=(0 if r == 0 else 8, 0))
        frame(parent, bg=GRAY100, height=1).pack(fill="x", pady=(14, 0))

    def _make_nav_tile(self, parent, icon, title, subtitle, target_attr, accent):
        """Crea una card cliccabile che scorre alla sezione `target_attr`."""
        tile = tk.Frame(parent, bg=GRAY50, cursor="hand2",
                        highlightthickness=1, highlightbackground=GRAY200)
        tk.Frame(tile, bg=accent, width=4).pack(side="left", fill="y")
        body = tk.Frame(tile, bg=GRAY50)
        body.pack(side="left", fill="both", expand=True, padx=10, pady=8)
        top = tk.Frame(body, bg=GRAY50)
        top.pack(fill="x")
        ico = tk.Label(top, text=icon, font=(SF, 13), bg=GRAY50, fg=accent)
        ico.pack(side="left")
        ttl = tk.Label(top, text=title, font=(SF, 10, "bold"),
                       bg=GRAY50, fg=GRAY800, anchor="w")
        ttl.pack(side="left", padx=(8, 0))
        sub = tk.Label(body, text=subtitle, font=FSM, bg=GRAY50, fg=GRAY500,
                       anchor="w", justify="left", wraplength=175)
        sub.pack(fill="x", pady=(3, 0))

        hot = (tile, body, top, ico, ttl, sub)

        def on_enter(_e=None):
            for w in hot:
                w.configure(bg="white")
            tile.configure(highlightbackground=accent)

        def on_leave(_e=None):
            for w in hot:
                w.configure(bg=GRAY50)
            tile.configure(highlightbackground=GRAY200)

        def on_click(_e=None):
            self._scroll_to(getattr(self, target_attr, None))

        for w in hot:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)
        return tile

    def _scroll_to(self, widget):
        """Scorre la pagina così che `widget` sia in cima all'area visibile."""
        cv = self._page_canvas
        if cv is None or widget is None or self._page_content is None:
            return
        try:
            if not widget.winfo_exists():
                return
            cv.update_idletasks()
            bbox = cv.bbox("all")
            if not bbox:
                return
            total = bbox[3] - bbox[1]
            if total <= 0:
                return
            offset = widget.winfo_rooty() - self._page_content.winfo_rooty()
            frac = max(0.0, min(1.0, (offset - 12) / total))
            cv.yview_moveto(frac)
        except tk.TclError:
            pass

    def _on_page_content_config(self, _e=None):
        cv = self._page_canvas
        if cv is None:
            return
        cv.configure(scrollregion=cv.bbox("all"))

    def _on_page_canvas_config(self, e):
        if self._page_canvas is not None and self._page_win is not None:
            self._page_canvas.itemconfig(self._page_win, width=e.width)

    def _on_page_wheel(self, e):
        cv = getattr(self, "_page_canvas", None)
        if cv is None:
            return
        try:
            if not cv.winfo_exists():
                return
            # Se il puntatore è sull'elenco servizi (con barra attiva), scorri quello
            svc = self._svc_scroll
            if svc is not None and svc.sb.winfo_ismapped():
                node = self.root.winfo_containing(e.x_root, e.y_root)
                while node is not None:
                    if node is svc.canvas:
                        svc.canvas.yview_scroll(-1 * (e.delta // 120), "units")
                        return
                    node = getattr(node, "master", None)
            cv.yview_scroll(-1 * (e.delta // 120), "units")
        except tk.TclError:
            pass

    def _select_env(self, env):
        self._selected_env.set(env)
        for e, btn in self._tab_btns.items():
            btn.configure(bg=BRAND if e == env else GRAY50,
                          fg="white" if e == env else GRAY600)
        if hasattr(self, "_terminal_context_lbl"):
            self._update_terminal_context()
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._refresh()

    def _refresh(self):
        env = self._selected_env.get()
        threading.Thread(target=self._fetch_status, args=(env,), daemon=True).start()

    def _fetch_status(self, env):
        site_name = f"PortaleNovicrom-{env.upper()}"
        pool_name = f"PortaleNovicrom-{env.upper()}"
        ep = Path(self.BASE_DIR) / env

        ps = f"""
Import-Module WebAdministration -ErrorAction SilentlyContinue
$site = Get-Website -Name '{site_name}' -ErrorAction SilentlyContinue
$pool = Get-WebAppPool -Name '{pool_name}' -ErrorAction SilentlyContinue
$sState = if ($site) {{ $site.State }} else {{ 'NotFound' }}
$pState = if ($pool) {{ $pool.State }} else {{ 'NotFound' }}
$port   = if ($site) {{ ($site.Bindings.Collection | Select-Object -First 1).bindingInformation.Split(':')[1] }} else {{ '' }}
Write-Output "$sState|$pState|$port"
"""
        try:
            r = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
            parts = (r.stdout or "").strip().split("|")
            site_state = parts[0] if len(parts) > 0 else "Unknown"
            pool_state = parts[1] if len(parts) > 1 else "Unknown"
            port       = parts[2].strip() if len(parts) > 2 else ""
        except Exception:
            site_state = pool_state = "Error"
            port = ""

        # Log tail
        log_path = ep / "logs" / "waitress_stdout.log"
        log_lines = ""
        try:
            if log_path.exists():
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                    log_lines = "".join(all_lines[-40:])
        except Exception:
            log_lines = ""

        url = f"http://localhost:{port}/" if port else f"http://localhost/"
        self.root.after(0, lambda: self._update_ui(site_state, pool_state, url, log_lines))

        # Stato task qcluster e log
        q_task = f"QCluster_{env.upper()}"
        q_ps = f"""
$t = Get-ScheduledTask -TaskName '{q_task}' -TaskPath '\\PortaleNovicrom\\' -ErrorAction SilentlyContinue
if ($t) {{
    $i = Get-ScheduledTaskInfo -TaskName '{q_task}' -TaskPath '\\PortaleNovicrom\\' -ErrorAction SilentlyContinue
    $lastRun = if ($i.LastRunTime) {{ $i.LastRunTime.ToString('dd/MM HH:mm') }} else {{ 'mai' }}
    Write-Output "$($t.State)|$lastRun|$($i.LastTaskResult)"
}} else {{
    Write-Output "NotFound||"
}}
"""
        try:
            qr = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", q_ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
            qp = (qr.stdout or "").strip().split("|")
            q_state   = qp[0] if len(qp) > 0 else "Unknown"
            q_lastrun = qp[1] if len(qp) > 1 else ""
            q_result  = qp[2].strip() if len(qp) > 2 else ""
        except Exception:
            q_state = q_lastrun = q_result = ""

        q_log_path = ep / "logs" / "qcluster.log"
        q_log_tail = ""
        try:
            if q_log_path.exists():
                with open(q_log_path, encoding="utf-8", errors="replace") as f:
                    q_log_tail = "".join(f.readlines()[-20:])
        except Exception:
            q_log_tail = ""

        self.root.after(0, lambda s=q_state, r=q_lastrun, x=q_result, l=q_log_tail:
                        self._q_update_status(s, r, x, l))

        # Servizi Windows rilevanti (IIS, SQL Server, …)
        pat_list = ",".join("'" + p + "'" for p in self.SERVICE_PATTERNS)
        svc_ps = (
            "$pat = @(" + pat_list + ")\n"
            "Get-Service -ErrorAction SilentlyContinue | Where-Object {\n"
            "  $n = $_.Name\n"
            "  ($pat | Where-Object { $n -like $_ }).Count -gt 0\n"
            "} | Sort-Object DisplayName | ForEach-Object {\n"
            "  $_.Name + [char]9 + $_.DisplayName + [char]9 + "
            "$_.Status + [char]9 + $_.StartType\n"
            "}\n"
        )
        services = []
        try:
            sr = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", svc_ps],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in (sr.stdout or "").splitlines():
                parts = line.rstrip("\r").split("\t")
                if len(parts) >= 4 and parts[0].strip():
                    services.append((parts[0].strip(), parts[1].strip(),
                                     parts[2].strip(), parts[3].strip()))
        except Exception:
            services = []
        self.root.after(0, lambda sv=services: self._update_services(sv))

    def _update_ui(self, site_state, pool_state, url, log_lines):
        state_map = {
            "Started": ("▶ Avviato", GREEN),
            "Stopped": ("■ Fermato", RED),
            "NotFound": ("✗ Non trovato", GRAY400),
            "Starting": ("… Avvio", YELLOW_TX),
            "Stopping": ("… Arresto", YELLOW_TX),
        }
        s_text, s_fg = state_map.get(site_state, (site_state, GRAY500))
        p_text, p_fg = state_map.get(pool_state, (pool_state, GRAY500))

        self._rows[0][1].configure(text=s_text, fg=s_fg)
        self._rows[1][1].configure(text=p_text, fg=p_fg)
        self._rows[2][1].configure(text="")
        self._rows[2][2].configure(text=url, fg=BRAND, cursor="hand2")
        self._rows[2][2].bind("<Button-1>", lambda e: self._open_browser())
        self._url = url

        self._log_txt.configure(state="normal")
        self._log_txt.delete("1.0", "end")
        self._log_txt.insert("end", log_lines or "(nessun log disponibile)")
        self._log_txt.see("end")
        self._log_txt.configure(state="disabled")

        now = datetime.now().strftime("%H:%M:%S")
        self._refresh_lbl.configure(text=f"Aggiornato alle {now}")
        self._after_id = self.root.after(self.REFRESH_MS, self._refresh)

    def _iis_action(self, action):
        env = self._selected_env.get()
        site = f"PortaleNovicrom-{env.upper()}"
        pool = f"PortaleNovicrom-{env.upper()}"
        ps_map = {
            "start":   f"Import-Module WebAdministration; Start-Website '{site}'; Start-WebAppPool '{pool}'",
            "stop":    f"Import-Module WebAdministration; Stop-Website '{site}'; Stop-WebAppPool '{pool}'",
            "restart": f"Import-Module WebAdministration; Stop-Website '{site}' -ErrorAction SilentlyContinue; "
                       f"Stop-WebAppPool '{pool}' -ErrorAction SilentlyContinue; "
                       f"Start-WebAppPool '{pool}'; Start-Website '{site}'",
            "recycle": f"Import-Module WebAdministration; Restart-WebAppPool '{pool}'",
        }
        ps = ps_map.get(action, "")
        if not ps:
            return
        def _run():
            try:
                subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
            self.root.after(1500, self._refresh)
        threading.Thread(target=_run, daemon=True).start()

    # ── Servizi Windows ──────────────────────────────────────────
    def _svc_mini_btn(self, parent, text, fg, command):
        """Pulsantino inline per la gestione di un servizio."""
        lbl = tk.Label(parent, text=text, font=(SF, 8, "bold"), fg=fg,
                       bg=GRAY100, padx=8, pady=3, cursor="hand2")
        lbl._enabled = True
        lbl._fg = fg
        lbl.bind("<Button-1>",
                 lambda e: command(lbl) if getattr(lbl, "_enabled", True) else None)
        lbl.bind("<Enter>",
                 lambda e: lbl.configure(bg=GRAY200) if lbl._enabled else None)
        lbl.bind("<Leave>",
                 lambda e: lbl.configure(bg=GRAY100 if lbl._enabled else GRAY50))
        return lbl

    def _svc_set_enabled(self, lbl, enabled):
        lbl._enabled = bool(enabled)
        lbl.configure(fg=lbl._fg if enabled else GRAY400,
                      bg=GRAY100 if enabled else GRAY50,
                      cursor="hand2" if enabled else "arrow")

    def _build_service_row(self, name, display, status, starttype):
        row = frame(self._svc_container, bg=GRAY50)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=(display or name), font=FSM, fg=GRAY700, bg=GRAY50,
                 width=32, anchor="w").pack(side="left")
        status_lbl = tk.Label(row, text="—", font=FSM, fg=GRAY500, bg=GRAY50,
                              width=14, anchor="w")
        status_lbl.pack(side="left")
        start_lbl = tk.Label(row, text="—", font=FSM, fg=GRAY500, bg=GRAY50,
                             width=13, anchor="w")
        start_lbl.pack(side="left")
        actions = frame(row, bg=GRAY50)
        actions.pack(side="left")
        btns = {}
        for key, txt, fg in (("start", "▶ Avvia", GREEN),
                             ("stop", "■ Ferma", RED),
                             ("restart", "↺ Riavvia", BRAND)):
            b = self._svc_mini_btn(
                actions, txt, fg,
                lambda _w, k=key, n=name: self._service_action(n, k))
            b.pack(side="left", padx=(0, 6))
            btns[key] = b
        type_btn = self._svc_mini_btn(
            actions, "⚙ Tipo avvio", GRAY600,
            lambda w, n=name: self._svc_starttype_menu(n, w))
        type_btn.pack(side="left", padx=(0, 6))
        btns["type"] = type_btn
        self._svc_rows[name] = {"status": status_lbl, "start": start_lbl,
                                "btns": btns}

    def _apply_service_state(self, row, status, starttype):
        s_text, s_fg = self._SVC_STATUS.get(status, (status or "—", GRAY500))
        t_text, t_fg = self._SVC_STARTTYPE.get(starttype, (starttype or "—", GRAY500))
        row["status"].configure(text=s_text, fg=s_fg)
        row["start"].configure(text=t_text, fg=t_fg)
        running  = (status == "Running")
        disabled = (starttype == "Disabled")
        admin    = self._admin_mode
        self._svc_set_enabled(row["btns"]["start"],   admin and not running and not disabled)
        self._svc_set_enabled(row["btns"]["stop"],    admin and running)
        self._svc_set_enabled(row["btns"]["restart"], admin and running)
        self._svc_set_enabled(row["btns"]["type"],    admin)

    def _update_services(self, services):
        """Aggiorna la lista servizi; ricostruisce le righe se l'elenco cambia."""
        if self._svc_container is None:
            return
        if not services and self._svc_rows:
            return  # errore transitorio: mantieni l'elenco precedente
        names = [s[0] for s in services]
        if set(names) != set(self._svc_rows.keys()):
            for child in self._svc_container.winfo_children():
                child.destroy()
            self._svc_rows.clear()
            if not services:
                tk.Label(self._svc_container, text="Nessun servizio rilevato.",
                         font=FSM, fg=GRAY400, bg=GRAY50).pack(anchor="w", pady=6)
            for name, display, status, starttype in services:
                self._build_service_row(name, display, status, starttype)

        running = 0
        for name, display, status, starttype in services:
            row = self._svc_rows.get(name)
            if row:
                self._apply_service_state(row, status, starttype)
            if status == "Running":
                running += 1
        if self._svc_summary_lbl is not None:
            self._svc_summary_lbl.configure(
                text=f"{len(services)} servizi · {running} in servizio")

        if self._svc_scroll is not None:
            self._svc_scroll.inner.update_idletasks()
            need = (self._svc_scroll.inner.winfo_reqheight()
                    > self._svc_scroll.canvas.winfo_height())
            self._svc_scroll.show_scrollbar(need)

    def _svc_starttype_menu(self, name, widget):
        """Menu contestuale per cambiare il tipo di avvio di un servizio."""
        if not self._admin_mode:
            return
        m = tk.Menu(self.root, tearoff=0)
        for label, val in (("Automatico", "Automatic"),
                           ("Manuale", "Manual"),
                           ("Disattivato", "Disabled")):
            m.add_command(label=label,
                          command=lambda v=val, n=name: self._set_service_starttype(n, v))
        try:
            m.tk_popup(widget.winfo_pointerx(), widget.winfo_pointery())
        finally:
            m.grab_release()

    def _service_action(self, name, action):
        if not self._admin_mode:
            messagebox.showwarning(
                "Gestione servizi",
                "Avvia il setup come Amministratore per gestire i servizi Windows.")
            return
        safe = name.replace("'", "''")
        ps_map = {
            "start":   f"Start-Service -Name '{safe}' -ErrorAction Stop",
            "stop":    f"Stop-Service -Name '{safe}' -Force -ErrorAction Stop",
            "restart": f"Restart-Service -Name '{safe}' -Force -ErrorAction Stop",
        }
        ps = ps_map.get(action)
        if ps:
            self._run_service_ps(name, action, ps)

    def _set_service_starttype(self, name, starttype):
        if not self._admin_mode:
            return
        safe = name.replace("'", "''")
        ps = f"Set-Service -Name '{safe}' -StartupType {starttype} -ErrorAction Stop"
        self._run_service_ps(name, f"tipo avvio → {starttype}", ps)

    def _run_service_ps(self, name, action, ps):
        """Esegue un comando PowerShell di gestione servizio in background."""
        def _run():
            err = ""
            try:
                r = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=45,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode != 0 or (r.stderr or "").strip():
                    err = (r.stderr or r.stdout or "Errore sconosciuto").strip()
            except Exception as exc:
                err = str(exc)
            if err:
                self.root.after(0, lambda: messagebox.showerror(
                    "Gestione servizi",
                    f"Operazione '{action}' sul servizio {name} non riuscita:\n\n"
                    f"{err[:400]}"))
            self.root.after(900, self._refresh)
        threading.Thread(target=_run, daemon=True).start()

    def _clean_old_releases(self):
        """Elimina release vecchie mantenendo solo le ultime 3 + quella attiva."""
        env = self._selected_env.get()
        rel_dir = Path(self.BASE_DIR) / env / "releases"
        cur_link = Path(self.BASE_DIR) / env / "current"
        if not rel_dir.exists():
            messagebox.showinfo("Cleaner", "Nessuna cartella releases trovata.")
            return
        # Rileva target della junction corrente
        try:
            active = str(cur_link.resolve()) if (cur_link.exists() or cur_link.is_symlink()) else ""
        except Exception:
            active = ""
        releases = sorted(rel_dir.iterdir(), key=lambda p: p.name)
        to_keep = 3
        to_delete = [r for r in releases if str(r) != active][:-to_keep] if len(releases) > to_keep else []
        if not to_delete:
            messagebox.showinfo("Cleaner", "Nulla da eliminare — sono presenti ≤ 3 release.")
            return
        names = "\n".join(r.name for r in to_delete)
        if not messagebox.askyesno("Cleaner",
                f"Eliminare {len(to_delete)} release vecchie?\n\n{names}"):
            return
        errors = []
        for r in to_delete:
            try:
                shutil.rmtree(str(r))
            except Exception as e:
                errors.append(f"{r.name}: {e}")
        if errors:
            messagebox.showwarning("Cleaner", "Alcuni errori:\n" + "\n".join(errors))
        else:
            messagebox.showinfo("Cleaner", f"✓ Eliminate {len(to_delete)} release vecchie.")

    def _open_browser(self):
        try:
            os.startfile(getattr(self, "_url", "http://localhost/"))
        except Exception:
            pass

    def _env_root(self, env=None) -> Path:
        return Path(self.BASE_DIR) / (env or self._selected_env.get())

    def _resolve_env_django_app(self, env=None) -> Path | None:
        env_root = self._env_root(env)
        candidates = [
            env_root / "current" / "django_app",
            env_root / "django_app",
        ]
        releases_dir = env_root / "releases"
        try:
            if releases_dir.exists():
                releases = sorted(
                    (p for p in releases_dir.iterdir() if p.is_dir()),
                    key=lambda p: p.name,
                    reverse=True,
                )
                candidates.extend(p / "django_app" for p in releases)
        except Exception:
            pass
        for candidate in candidates:
            if (candidate / "manage.py").exists():
                return candidate
        return None

    def _update_terminal_context(self):
        env = self._selected_env.get()
        django_app = self._resolve_env_django_app(env)
        if django_app:
            text = f"{env.upper()} - {django_app}"
            fg = GRAY400
        else:
            text = f"{env.upper()} - release corrente non trovata"
            fg = RED
        self._terminal_context_lbl.configure(text=text, fg=fg)

    def _on_terminal_preset(self, _event=None):
        selected = self._terminal_preset_var.get()
        for label, command, description, file_token in self._terminal_presets:
            if label == selected:
                self._terminal_cmd_var.set(command)
                self._terminal_desc_lbl.configure(text=description)
                self._terminal_file_token = file_token
                self._terminal_file_btn.set_enabled(file_token is not None)
                break
        self._terminal_entry.focus_set()
        self._terminal_entry.icursor("end")

    def _browse_terminal_file(self):
        token = self._terminal_file_token
        if not token:
            return
        path = filedialog.askopenfilename()
        if not path:
            return
        command = self._terminal_cmd_var.get()
        quoted = f'"{path}"' if " " in path else path
        self._terminal_cmd_var.set(command.replace(token, quoted))
        self._terminal_entry.focus_set()
        self._terminal_entry.icursor("end")

    def _append_terminal(self, text, tag=None):
        if not hasattr(self, "_terminal_txt"):
            return
        self._terminal_txt.configure(state="normal")
        if tag:
            self._terminal_txt.insert("end", text, tag)
        else:
            self._terminal_txt.insert("end", text)
        self._terminal_txt.see("end")
        self._terminal_txt.configure(state="disabled")

    def _set_terminal_running(self, running: bool):
        self._terminal_run_btn.configure_text("In esecuzione..." if running else "Esegui")
        self._terminal_stop_btn.set_enabled(running)
        state = "disabled" if running else "normal"
        self._terminal_entry.configure(state=state)
        self._terminal_preset.configure(state="disabled" if running else "readonly")
        self._terminal_file_btn.set_enabled(False if running else self._terminal_file_token is not None)

    def _split_terminal_command(self, command: str) -> list[str]:
        try:
            parts = shlex.split(command, posix=False)
        except ValueError:
            parts = command.split()
        cleaned = []
        for part in parts:
            if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
                cleaned.append(part[1:-1])
            else:
                cleaned.append(part)
        return cleaned

    def _terminal_command_argv(self, command: str, venv_py: Path) -> tuple[list[str], bool]:
        stripped = command.strip()
        lower = stripped.lower()
        if lower == "manage.py" or lower.startswith("manage.py "):
            parts = self._split_terminal_command(stripped)
            return [str(venv_py), *parts], True
        if lower == "python" or lower.startswith("python ") or lower.startswith("py "):
            parts = self._split_terminal_command(stripped)
            if parts and parts[0].lower() in {"python", "py"}:
                parts = parts[1:]
            return [str(venv_py), *parts], True
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", stripped], False

    def _terminal_env_vars(self, env: str, django_app: Path) -> dict:
        env_root = self._env_root(env)
        venv_scripts = env_root / "venv" / "Scripts"
        env_vars = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": _django_settings(env),
            "PYTHONPATH": str(django_app),
            "PORTAL_SKIP_RUNTIME_BOOTSTRAP": "1",
            "STATIC_ROOT": str(env_root / "static"),
            "MEDIA_ROOT": str(env_root / "media"),
        }
        env_vars["PATH"] = f"{venv_scripts};{env_vars.get('PATH', '')}"
        return env_vars

    def _run_terminal_command(self):
        with self._terminal_lock:
            if self._terminal_running:
                self._append_terminal("\nUn comando e gia in esecuzione. Usa Stop o attendi il termine.\n", "error")
                return

        command = self._terminal_cmd_var.get().strip()
        if not command:
            return
        env = self._selected_env.get()
        env_root = self._env_root(env)
        django_app = self._resolve_env_django_app(env)
        venv_py = env_root / "venv" / "Scripts" / "python.exe"
        if not django_app:
            self._append_terminal(f"\n[{env.upper()}] Release corrente non trovata: manca current\\django_app.\n", "error")
            return

        argv, needs_venv = self._terminal_command_argv(command, venv_py)
        if needs_venv and not venv_py.exists():
            self._append_terminal(f"\n[{env.upper()}] Virtualenv non trovato: {venv_py}\n", "error")
            return

        if env == "prod":
            if not messagebox.askyesno(
                "Conferma comando PROD",
                f"Eseguire questo comando su PROD?\n\n{command}",
            ):
                return

        self._append_terminal(f"\n[{env.upper()}] {django_app}\n$ {command}\n", "meta")
        self._set_terminal_running(True)
        with self._terminal_lock:
            self._terminal_running = True
        threading.Thread(
            target=self._run_terminal_thread,
            args=(env, django_app, argv),
            daemon=True,
        ).start()

    def _run_terminal_thread(self, env: str, django_app: Path, argv: list[str]):
        env_vars = self._terminal_env_vars(env, django_app)
        proc = None
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(django_app),
                env=env_vars,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            with self._terminal_lock:
                self._terminal_proc = proc
            if proc.stdout:
                for line in proc.stdout:
                    self.root.after(0, lambda value=line: self._append_terminal(value))
            return_code = proc.wait()
            tag = "ok" if return_code == 0 else "error"
            self.root.after(0, lambda rc=return_code, t=tag: self._append_terminal(f"\n[exit {rc}]\n", t))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._append_terminal(f"\nErrore terminale: {e}\n", "error"))
        finally:
            with self._terminal_lock:
                self._terminal_proc = None
                self._terminal_running = False
            self.root.after(0, lambda: self._set_terminal_running(False))

    def _stop_terminal_command(self):
        with self._terminal_lock:
            proc = self._terminal_proc
        if proc is None:
            return
        if not messagebox.askyesno("Terminale", "Interrompere il comando in esecuzione?"):
            return
        try:
            proc.terminate()
            self._append_terminal("\n[stop richiesto]\n", "meta")
        except Exception as exc:
            self._append_terminal(f"\nStop non riuscito: {exc}\n", "error")

    # ── Assistente AI (Ollama + RAG) ─────────────────────────────

    def _ai_settings_flag(self, env: str) -> str:
        return f"--settings={_django_settings(env)}"

    def _ai_active_env_path(self, env: str):
        da = self._resolve_env_django_app(env)
        return (da / ".env") if da else None

    def _ai_persistent_env_path(self, env: str) -> Path:
        """.env da editare: preferisce il persistente config\\.env, altrimenti l'attivo."""
        cfg_env = self._env_root(env) / "config" / ".env"
        if cfg_env.exists():
            return cfg_env
        active = self._ai_active_env_path(env)
        return active if active else cfg_env

    def _ai_read_config(self, env: str) -> dict:
        path = self._ai_active_env_path(env)
        if not path or not path.exists():
            return {}
        try:
            return _env_key_values(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {}

    def _ai_log(self, text, tag=None):
        if not hasattr(self, "_ai_log_txt"):
            return
        self._ai_log_txt.configure(state="normal")
        if tag:
            self._ai_log_txt.insert("end", text, tag)
        else:
            self._ai_log_txt.insert("end", text)
        self._ai_log_txt.see("end")
        self._ai_log_txt.configure(state="disabled")

    def _ai_verify(self):
        env = self._selected_env.get()
        cfg = self._ai_read_config(env)
        if not cfg:
            self._ai_status_lbl.configure(text="✗ .env non trovato", fg=RED)
            self._ai_log(f"\n[{env.upper()}] .env attivo non trovato (release corrente?).\n", "error")
            return
        self._ai_log(f"\n[{env.upper()}] Verifica AI in corso...\n", "meta")
        threading.Thread(target=self._ai_verify_thread, args=(env, cfg), daemon=True).start()

    def _ai_verify_thread(self, env, cfg):
        import urllib.request
        import json as _json

        def _get_json(url, timeout=10):
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _json.loads(r.read().decode("utf-8", "replace"))

        def _post_json(url, payload, timeout=20):
            data = _json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _json.loads(r.read().decode("utf-8", "replace"))

        lines = []
        ok_all = True
        base = (cfg.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        chat = cfg.get("OLLAMA_CHAT_MODEL") or "qwen2.5:14b-instruct"
        try:
            tags = _get_json(f"{base}/api/tags")
            names = [m.get("name", "") for m in (tags.get("models") or [])]
            have = any(n == chat or n.split(":")[0] == chat.split(":")[0] for n in names)
            lines.append(f"Ollama {base}: {len(names)} modelli; chat '{chat}' {'OK' if have else 'ASSENTE'}")
            ok_all = ok_all and have
        except Exception as exc:
            lines.append(f"Ollama {base}: IRRAGGIUNGIBILE ({exc})")
            ok_all = False

        backend = (cfg.get("RAG_EMBED_BACKEND") or "ollama").strip().lower()
        emb_on = (cfg.get("OLLAMA_EMBED_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")
        if emb_on and backend == "openai":
            tei = (cfg.get("RAG_EMBED_OPENAI_BASE_URL") or "").rstrip("/")
            model = cfg.get("RAG_EMBED_OPENAI_MODEL") or ""
            if not tei or not model:
                lines.append("TEI: config incompleta (BASE_URL/MODEL)")
                ok_all = False
            else:
                try:
                    resp = _post_json(f"{tei}/v1/embeddings", {"model": model, "input": ["ping"]})
                    dim = len((resp.get("data") or [{}])[0].get("embedding") or [])
                    warn = "" if dim in (0, 1024) else f" (atteso 1024, trovato {dim})"
                    lines.append(f"TEI {tei}: OK, dim={dim}{warn}")
                except Exception as exc:
                    lines.append(f"TEI {tei}: NON RISPONDE ({exc})")
                    ok_all = False
        elif emb_on and backend == "ollama":
            lines.append("Embeddings: backend Ollama nativo (modello caricato in Ollama)")
        else:
            lines.append("Embeddings: disattivati (BM25-only)")

        summary = "✔ tutto ok" if ok_all else "✗ problemi rilevati"
        col = GREEN if ok_all else RED

        def _apply():
            self._ai_status_lbl.configure(text=summary, fg=col)
            for ln in lines:
                self._ai_log("  " + ln + "\n", "ok" if ok_all else None)

        self.root.after(0, _apply)

    def _ai_reindex(self):
        env = self._selected_env.get()
        self._ai_log(f"\n[{env.upper()}] Re-index SGI -> terminale integrato.\n", "meta")
        self._q_run_manage(f"manage.py index_sgi_documents --json {self._ai_settings_flag(env)}")

    def _ai_edit_config(self):
        env = self._selected_env.get()
        target = self._ai_persistent_env_path(env)
        current = self._ai_read_config(env)

        emb_on = (current.get("OLLAMA_EMBED_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")
        backend0 = (current.get("RAG_EMBED_BACKEND") or "ollama").strip().lower()
        if not emb_on:
            backend0 = "off"
        elif backend0 == "openai":
            backend0 = "tei"
        else:
            backend0 = "ollama"

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Config AI — {env.upper()}")
        dlg.configure(bg="white")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("580x540")

        pad = frame(dlg, bg="white")
        pad.pack(fill="both", expand=True, padx=18, pady=14)
        tk.Label(pad, text=f"Scrive in:  {target}", font=FSM, fg=GRAY500, bg="white",
                 wraplength=540, justify="left").pack(anchor="w", pady=(0, 8))

        v_base = tk.StringVar(value=current.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
        v_chat = tk.StringVar(value=current.get("OLLAMA_CHAT_MODEL", "qwen2.5:14b-instruct"))
        v_emb = tk.StringVar(value=current.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
        v_tbase = tk.StringVar(value=current.get("RAG_EMBED_OPENAI_BASE_URL", "http://127.0.0.1:8081"))
        v_tmod = tk.StringVar(value=current.get("RAG_EMBED_OPENAI_MODEL", "BAAI/bge-m3"))
        v_back = tk.StringVar(value=backend0)

        FieldGroup(pad, "OLLAMA_BASE_URL", v_base, mono=True).pack(fill="x", pady=(0, 6))
        FieldGroup(pad, "OLLAMA_CHAT_MODEL", v_chat, mono=True).pack(fill="x", pady=(0, 10))

        tk.Label(pad, text="BACKEND EMBEDDINGS", font=(SF, 8, "bold"),
                 fg=GRAY500, bg="white").pack(anchor="w")
        radio_row = frame(pad, bg="white")
        radio_row.pack(fill="x", pady=(2, 6))

        frm_o = frame(pad, bg="white")
        FieldGroup(frm_o, "OLLAMA_EMBED_MODEL", v_emb, mono=True).pack(fill="x", pady=(0, 6))
        frm_t = frame(pad, bg="white")
        FieldGroup(frm_t, "RAG_EMBED_OPENAI_BASE_URL", v_tbase, mono=True).pack(fill="x", pady=(0, 6))
        FieldGroup(frm_t, "RAG_EMBED_OPENAI_MODEL", v_tmod, mono=True).pack(fill="x", pady=(0, 6))

        def _refresh():
            frm_o.pack_forget()
            frm_t.pack_forget()
            if v_back.get() == "ollama":
                frm_o.pack(fill="x", after=radio_row)
            elif v_back.get() == "tei":
                frm_t.pack(fill="x", after=radio_row)

        for val, txt in (("off", "Off (BM25)"), ("ollama", "Ollama"), ("tei", "TEI")):
            tk.Radiobutton(radio_row, text=txt, value=val, variable=v_back, bg="white",
                           activebackground="white", font=FSM,
                           command=_refresh).pack(side="left", padx=(0, 14))
        _refresh()

        tk.Label(pad, text="Dopo il salvataggio: riavvia IIS e, se cambi modello/backend, "
                           "lancia «Re-index SGI». Le chiavi duplicate vengono ripulite.",
                 font=FSM, fg=YELLOW_TX, bg="white", wraplength=540, justify="left").pack(anchor="w", pady=(10, 8))

        def _save():
            backend = v_back.get()
            if backend == "tei" and (not v_tbase.get().strip() or not v_tmod.get().strip()):
                messagebox.showwarning("Config AI", "Con TEI servono endpoint e modello.")
                return
            updates, remove = _ai_build_env_updates(
                backend, v_base.get().strip(), v_chat.get().strip(),
                v_emb.get().strip() or "nomic-embed-text",
                v_tbase.get().strip(), v_tmod.get().strip() or "BAAI/bge-m3",
            )
            # Scrive sia il .env PERSISTENTE (config\.env, durevole tra i deploy) sia
            # l'ATTIVO (current\django_app\.env, usato dal processo in esecuzione e da
            # Verifica): senza l'attivo il salvataggio non ha effetto finche' non gira
            # un deploy, e Verifica/prefill continuerebbero a mostrare il vecchio
            # valore. Scriverli entrambi li tiene allineati (nessun drift).
            persistent = self._ai_persistent_env_path(env)
            active = self._ai_active_env_path(env)
            targets, seen = [], set()
            for t in (persistent, active):
                if t and str(t) not in seen:
                    seen.add(str(t))
                    targets.append(t)
            if env == "prod" and not messagebox.askyesno(
                "Conferma PROD",
                "Scrivere la config AI (PROD) in:\n" + "\n".join(str(t) for t in targets) + " ?"):
                return
            written = []
            for t in targets:
                try:
                    text = t.read_text(encoding="utf-8", errors="replace") if t.exists() else ""
                    t.parent.mkdir(parents=True, exist_ok=True)
                    t.write_text(_apply_env_updates(text, updates, remove), encoding="utf-8")
                    written.append(str(t))
                except Exception as exc:
                    messagebox.showerror("Config AI", f"Scrittura di {t} fallita: {exc}")
                    return
            self._ai_log(
                f"\n[{env.upper()}] Config AI salvata (backend={backend}) in:\n  "
                + "\n  ".join(written)
                + "\nRiavvia IIS per applicare.\n", "ok")
            dlg.destroy()

        btns = frame(pad, bg="white")
        btns.pack(fill="x", side="bottom", pady=(8, 0))
        PrimaryButton(btns, "💾  Salva", _save).pack(side="right")
        SecondaryButton(btns, "Annulla", dlg.destroy).pack(side="right", padx=(0, 8))

    # ── Automazioni django-q ─────────────────────────────────────

    def _q_task_name(self, env: str | None = None) -> str:
        return f"QCluster_{(env or self._selected_env.get()).upper()}"

    def _q_update_status(self, state: str, last_run: str, result: str, log_tail: str):
        """Aggiorna badge stato e log qcluster (main thread)."""
        if not self._q_status_lbl:
            return
        state_map = {
            "Running": ("● In esecuzione", GREEN),
            "Ready":   ("● Pronto (idle)", GRAY500),
            "Stopped": ("○ Fermato", GRAY400),
            "Disabled": ("✗ Disabilitato", YELLOW_TX),
            "NotFound": ("✗ Non installato", RED),
        }
        text, fg = state_map.get(state, (f"— {state}", GRAY400))
        if last_run and state != "NotFound":
            text += f"  (ultima: {last_run})"
        self._q_status_lbl.configure(text=text, fg=fg)

        if self._q_log_txt:
            self._q_log_txt.configure(state="normal")
            self._q_log_txt.delete("1.0", "end")
            self._q_log_txt.insert("end", log_tail or "(nessun log qcluster disponibile)")
            self._q_log_txt.see("end")
            self._q_log_txt.configure(state="disabled")

        if self._q_start_btn:
            self._q_start_btn.set_enabled(state in {"Ready", "Stopped", "NotFound"})
        if self._q_stop_btn:
            self._q_stop_btn.set_enabled(state == "Running")

    def _q_run_manage(self, command: str):
        """Esegue un manage.py nel terminale integrato."""
        self._terminal_cmd_var.set(command)
        self._run_terminal_command()

    def _q_script_source(self, env: str) -> Path | None:
        """Cerca start_qcluster.ps1 nella release corrente."""
        candidates = [
            self._env_root(env) / "current" / "deployment" / "start_qcluster.ps1",
            Path(__file__).parent / "start_qcluster.ps1",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _q_ensure_script(self, env: str) -> Path | None:
        """Copia start_qcluster.ps1 in shared\\scripts\\ e restituisce il path."""
        src = self._q_script_source(env)
        dest_dir = Path(self.BASE_DIR) / "shared" / "scripts"
        dest = dest_dir / "start_qcluster.ps1"
        if src and src != dest:
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dest))
            except Exception as exc:
                messagebox.showwarning(
                    "qcluster — script",
                    f"Impossibile copiare lo script in {dest_dir}:\n{exc}\n\n"
                    "Lo script verrà referenziato dalla posizione attuale.",
                )
                return src
        return dest if dest.exists() else src

    def _q_register_ps(self, env: str, script_path, task_name: str) -> str:
        """Script PowerShell che (ri)registra il task qcluster. Emette OK / ERR:."""
        return f"""
$ErrorActionPreference = 'Stop'
try {{
    $action = New-ScheduledTaskAction `
        -Execute 'powershell.exe' `
        -Argument '-NonInteractive -ExecutionPolicy Bypass -File \"{script_path}\" -Environment {env}'
    $trigger  = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)
    New-Item -Path '\\PortaleNovicrom' -ItemType Directory -ErrorAction SilentlyContinue | Out-Null
    Register-ScheduledTask `
        -TaskName '{task_name}' `
        -TaskPath '\\PortaleNovicrom\\' `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -RunLevel Highest `
        -Force `
        -Description 'django-q2 qcluster NOVICROM HUB {env.upper()}'
    Write-Output 'OK'
}} catch {{
    Write-Output "ERR:$_"
}}
"""

    def _q_install_task(self):
        """Registra il task schedulato \\PortaleNovicrom\\QCluster_<ENV>."""
        env = self._selected_env.get()
        task_name = self._q_task_name(env)
        script_path = self._q_ensure_script(env)
        if not script_path:
            messagebox.showerror(
                "qcluster — Installa task",
                "start_qcluster.ps1 non trovato.\n"
                "Assicurati che la release sia attiva o che lo script esista in "
                "deployment\\start_qcluster.ps1.",
            )
            return

        if not messagebox.askyesno(
            "Installa task qcluster",
            f"Registrare il Task Scheduler:\n"
            f"  Nome: \\PortaleNovicrom\\{task_name}\n"
            f"  Script: {script_path}\n"
            f"  Ambiente: {env.upper()}\n\n"
            f"Il task verrà registrato con trigger 'All'avvio' e livello Highest.\n"
            f"Procedere?",
        ):
            return

        ps = self._q_register_ps(env, script_path, task_name)

        def _run():
            try:
                r = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                out = (r.stdout or "").strip()
                if out.startswith("ERR:"):
                    self.root.after(0, lambda: messagebox.showerror(
                        "qcluster — Installa task", f"Errore registrazione task:\n{out[4:]}"))
                elif "OK" in out:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "qcluster — Installa task",
                        f"✓ Task \\PortaleNovicrom\\{task_name} registrato.\n"
                        "Avvialo con '▶ Avvia qcluster' oppure riavvia il server."))
                    self.root.after(0, self._refresh)
                else:
                    self.root.after(0, lambda: messagebox.showwarning(
                        "qcluster — Installa task", f"Output inatteso:\n{out or r.stderr}"))
            except Exception as exc:
                self.root.after(0, lambda e=exc: messagebox.showerror(
                    "qcluster — Installa task", f"Eccezione:\n{e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _q_start_task(self):
        env = self._selected_env.get()
        task_name = self._q_task_name(env)

        if not self._admin_mode:
            messagebox.showwarning(
                "qcluster — Avvia",
                "Avvio/registrazione del task richiedono privilegi di Administrator.\n"
                "Riavvia Setup Wizard come amministratore.",
            )
            return

        # Avvia il task e verifica che sia davvero in esecuzione. Se non esiste,
        # restituisce NOTASK per proporre l'auto-install.
        ps = f"""
$ErrorActionPreference = 'Stop'
try {{
    $t = Get-ScheduledTask -TaskName '{task_name}' -TaskPath '\\PortaleNovicrom\\' -ErrorAction SilentlyContinue
    if (-not $t) {{ Write-Output 'NOTASK'; return }}
    Start-ScheduledTask -TaskName '{task_name}' -TaskPath '\\PortaleNovicrom\\'
    Start-Sleep -Seconds 3
    $info = Get-ScheduledTaskInfo -TaskName '{task_name}' -TaskPath '\\PortaleNovicrom\\'
    $st = (Get-ScheduledTask -TaskName '{task_name}' -TaskPath '\\PortaleNovicrom\\').State
    if ($st -eq 'Running') {{ Write-Output 'RUNNING' }}
    else {{ Write-Output ("DEAD:" + $st + "|rc=" + $info.LastTaskResult) }}
}} catch {{
    Write-Output "ERR:$_"
}}
"""

        def _run():
            try:
                r = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
                out = (r.stdout or "").strip()
            except Exception as exc:
                out = f"ERR:{exc}"

            if out == "RUNNING":
                self.root.after(0, lambda: messagebox.showinfo(
                    "qcluster — Avvia",
                    f"✓ Task \\PortaleNovicrom\\{task_name} avviato e in esecuzione."))
            elif out == "NOTASK":
                self.root.after(0, lambda: self._q_offer_install_then_start(env, task_name))
            elif out.startswith("DEAD:"):
                detail = out[5:]
                self.root.after(0, lambda d=detail: messagebox.showerror(
                    "qcluster — Avvia",
                    f"Il task è partito ma non è rimasto in esecuzione (stato: {d}).\n\n"
                    "Causa probabile: start_qcluster.ps1 esce subito (path/venv errati, "
                    "errore di avvio del cluster). Controlla logs\\qcluster.log."))
            elif out.startswith("ERR:"):
                self.root.after(0, lambda e=out[4:]: messagebox.showerror(
                    "qcluster — Avvia", f"Errore nell'avvio del task:\n{e}"))
            else:
                self.root.after(0, lambda o=(out or r.stderr): messagebox.showwarning(
                    "qcluster — Avvia", f"Output inatteso:\n{o}"))

            self.root.after(1500, self._refresh)

        threading.Thread(target=_run, daemon=True).start()

    def _q_offer_install_then_start(self, env: str, task_name: str):
        """Il task non esiste: propone di registrarlo al volo e poi riavviare l'azione."""
        if not messagebox.askyesno(
            "qcluster — Avvia",
            f"Il task \\PortaleNovicrom\\{task_name} non è registrato.\n\n"
            "Vuoi registrarlo adesso e poi avviarlo?",
        ):
            return
        script_path = self._q_ensure_script(env)
        if not script_path:
            messagebox.showerror(
                "qcluster — Avvia",
                "start_qcluster.ps1 non trovato: impossibile registrare il task.\n"
                "Assicurati che la release sia attiva o che lo script esista in "
                "deployment\\start_qcluster.ps1.",
            )
            return
        ps = self._q_register_ps(env, script_path, task_name)

        def _run():
            try:
                r = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
                out = (r.stdout or "").strip()
            except Exception as exc:
                out = f"ERR:{exc}"
            if "OK" in out and not out.startswith("ERR:"):
                # Registrato: rilancia l'avvio (che ora troverà il task).
                self.root.after(0, self._q_start_task)
            else:
                msg = out[4:] if out.startswith("ERR:") else (out or "output inatteso")
                self.root.after(0, lambda m=msg: messagebox.showerror(
                    "qcluster — Avvia", f"Registrazione task fallita:\n{m}"))

        threading.Thread(target=_run, daemon=True).start()

    def _q_stop_task(self):
        env = self._selected_env.get()
        task_name = self._q_task_name(env)
        if not self._admin_mode:
            messagebox.showwarning(
                "qcluster — Ferma",
                "Fermare il task richiede privilegi di Administrator.\n"
                "Riavvia Setup Wizard come amministratore.",
            )
            return
        if not messagebox.askyesno(
            "Ferma qcluster",
            f"Fermare il task {task_name}?\n\nI job in corso verranno interrotti.",
        ):
            return
        ps = f"""
$ErrorActionPreference = 'Stop'
try {{
    Stop-ScheduledTask -TaskName '{task_name}' -TaskPath '\\PortaleNovicrom\\'
    Write-Output 'OK'
}} catch {{
    Write-Output "ERR:$_"
}}
"""
        def _run():
            try:
                r = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                out = (r.stdout or "").strip()
            except Exception as exc:
                out = f"ERR:{exc}"
            if out.startswith("ERR:"):
                self.root.after(0, lambda e=out[4:]: messagebox.showerror(
                    "qcluster — Ferma", f"Errore nell'arresto del task:\n{e}"))
            self.root.after(1500, self._refresh)
        threading.Thread(target=_run, daemon=True).start()

    def _open_live_password_reset(self):
        if not self._admin_mode:
            messagebox.showwarning(
                "Privilegi richiesti",
                "Il reset password live e disponibile solo quando Setup Wizard e avviato come Administrator.",
            )
            return

        env = self._selected_env.get()
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Reset password live - {env.upper()}")
        dialog.configure(bg="white")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        W, H = 460, 280
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        dialog.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

        body = frame(dialog, bg="white")
        body.pack(fill="both", expand=True, padx=20, pady=18)

        tk.Label(body, text=f"Ambiente {env.upper()}", font=(SF, 12, "bold"),
                 fg=GRAY700, bg="white").pack(anchor="w")
        tk.Label(
            body,
            text="Aggiorna la password di un account locale legacy e, se esiste, dell'utente Django associato.",
            font=FSM,
            fg=GRAY500,
            bg="white",
            wraplength=410,
            justify="left",
        ).pack(anchor="w", pady=(4, 14))

        username_var = tk.StringVar(value="admin")
        password_var = tk.StringVar()
        confirm_var = tk.StringVar()

        def _field(label_text, variable, *, show=""):
            row = frame(body, bg="white")
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label_text, font=(SF, 9, "bold"),
                     fg=GRAY600, bg="white").pack(anchor="w", pady=(0, 3))
            entry = tk.Entry(
                row,
                textvariable=variable,
                show=show,
                font=FMO,
                relief="flat",
                bg=GRAY50,
                fg=GRAY800,
                highlightthickness=1,
                highlightbackground=GRAY200,
                highlightcolor=BRAND,
            )
            entry.pack(fill="x", ipady=7, ipadx=8)
            return entry

        username_entry = _field("Username locale", username_var)
        password_entry = _field("Nuova password", password_var, show="*")
        confirm_entry = _field("Conferma password", confirm_var, show="*")

        status_var = tk.StringVar(value="")
        tk.Label(body, textvariable=status_var, font=FSM, fg=GRAY500, bg="white",
                 wraplength=410, justify="left").pack(anchor="w", pady=(8, 0))

        actions = frame(body, bg="white")
        actions.pack(fill="x", pady=(18, 0))

        def _set_busy(is_busy: bool):
            state = "disabled" if is_busy else "normal"
            for entry in (username_entry, password_entry, confirm_entry):
                entry.configure(state=state)
            btn_confirm.set_state(not is_busy)
            btn_cancel.set_enabled(not is_busy)

        def _submit():
            identifier = username_var.get().strip()
            password = password_var.get()
            confirm = confirm_var.get()
            if not identifier:
                status_var.set("Inserisci lo username locale da aggiornare.")
                return
            if len(password) < 8:
                status_var.set("La password deve contenere almeno 8 caratteri.")
                return
            if password != confirm:
                status_var.set("Le due password non coincidono.")
                return
            status_var.set(f"Aggiornamento password live in corso su {env.upper()}...")
            _set_busy(True)
            threading.Thread(
                target=self._run_live_password_reset,
                args=(env, identifier, password, dialog, status_var, _set_busy),
                daemon=True,
            ).start()

        btn_confirm = PrimaryButton(actions, "Aggiorna password", _submit)
        btn_confirm.pack(side="right")
        btn_cancel = SecondaryButton(actions, "Annulla", dialog.destroy)
        btn_cancel.pack(side="right", padx=(0, 8))

        username_entry.focus_set()

    def _run_live_password_reset(self, env, identifier, password, dialog, status_var, set_busy):
        env_root = Path(self.BASE_DIR) / env
        django_app = env_root / "current" / "django_app"
        venv_py = env_root / "venv" / "Scripts" / "python.exe"
        settings = _django_settings(env)

        if not django_app.exists() or not (django_app / "manage.py").exists():
            self.root.after(
                0,
                lambda: (
                    set_busy(False),
                    status_var.set("Release corrente non trovata: manca current\\django_app."),
                ),
            )
            return
        if not venv_py.exists():
            self.root.after(
                0,
                lambda: (
                    set_busy(False),
                    status_var.set("Virtualenv dell'ambiente non trovato."),
                ),
            )
            return

        reset_script = f"""
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", {settings!r})

import django
django.setup()

from django.contrib.auth import get_user_model
from django.db.models import Q
from werkzeug.security import generate_password_hash
from core.legacy_models import UtenteLegacy

identifier = {identifier!r}
password = {password!r}

legacy_user = (
    UtenteLegacy.objects.filter(Q(nome__iexact=identifier) | Q(email__iexact=identifier))
    .order_by("id")
    .first()
)
if not legacy_user:
    raise SystemExit(f"Utente locale non trovato: {{identifier}}")

legacy_user.password = generate_password_hash(password)
legacy_user.attivo = True
if hasattr(legacy_user, "deve_cambiare_password"):
    legacy_user.deve_cambiare_password = False
legacy_user.save()

django_user_updated = False
User = get_user_model()
candidate_names = []
for value in (legacy_user.nome, legacy_user.email, identifier):
    if value and value not in candidate_names:
        candidate_names.append(value)

django_user = None
for value in candidate_names:
    django_user = User.objects.filter(username__iexact=value).first()
    if django_user:
        break
if not django_user and legacy_user.email:
    django_user = User.objects.filter(email__iexact=legacy_user.email).first()
if django_user:
    django_user.set_password(password)
    django_user.save()
    django_user_updated = True

axes_reset = False
try:
    from axes.models import AccessAttempt, AccessFailureLog

    for value in candidate_names:
        AccessAttempt.objects.filter(username__iexact=value).delete()
        AccessFailureLog.objects.filter(username__iexact=value).delete()
    axes_reset = True
except Exception:
    pass

print(json.dumps({{
    "legacy_user": legacy_user.nome,
    "legacy_email": legacy_user.email,
    "django_user_updated": django_user_updated,
    "axes_reset": axes_reset,
}}))
"""

        env_vars = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": settings,
            "PYTHONPATH": str(django_app),
            "PORTAL_SKIP_RUNTIME_BOOTSTRAP": "1",
        }

        try:
            result = subprocess.run(
                [str(venv_py), "-c", reset_script],
                cwd=str(django_app),
                env=env_vars,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            self.root.after(
                0,
                lambda: (
                    set_busy(False),
                    status_var.set(f"Reset password non riuscito: {exc}"),
                ),
            )
            return

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        def _finish():
            if result.returncode == 0:
                summary = "Password live aggiornata con successo."
                try:
                    payload = json.loads(stdout or "{}")
                    summary = (
                        f"Utente legacy: {payload.get('legacy_user') or identifier}\n"
                        f"Utente Django sincronizzato: {'si' if payload.get('django_user_updated') else 'no'}\n"
                        f"Reset AXES: {'si' if payload.get('axes_reset') else 'no'}"
                    )
                except Exception:
                    if stdout:
                        summary = stdout
                dialog.destroy()
                messagebox.showinfo(
                    "Reset password live",
                    f"Ambiente {env.upper()}\n\n{summary}",
                )
                self._refresh()
                return

            set_busy(False)
            status_var.set(stderr or stdout or "Reset password non riuscito.")

        self.root.after(0, _finish)


# ─────────────────────────────────────────────────────────────
# LAUNCHER — schermata di avvio con selezione modalità
# ─────────────────────────────────────────────────────────────

class LauncherApp:
    """Finestra di avvio: l'utente sceglie cosa fare prima di entrare nel wizard."""

    def __init__(self):
        self._choice = None

        root = tk.Tk()
        root.title("Portale Novicrom — Setup")
        root.configure(bg="white")
        root.resizable(False, False)

        W, H = 640, 500
        sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
        root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

        # Header
        hdr = frame(root, bg=BRAND, height=64)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="Portale Novicrom", font=(SF, 15, "bold"),
                 bg=BRAND, fg="white").pack(side="left", padx=24, pady=16)
        tk.Label(hdr, text="Setup Wizard", font=(SF, 10),
                 bg=BRAND, fg="#bfdbfe").pack(side="left")

        # Titolo
        frame(root, height=24, bg="white").pack()
        tk.Label(root, text="Cosa vuoi fare?",
                 font=(SF, 13, "bold"), fg=GRAY700, bg="white").pack()
        tk.Label(root, text="Scegli una delle opzioni qui sotto",
                 font=FSM, fg=GRAY400, bg="white").pack(pady=(4, 20))

        # Card options
        cards_data = [
            ("install",
             "🔧  Installa nuovo ambiente",
             "Configura e installa il portale su questo server (primo avvio o nuovo ambiente)",
             BLUE_BG, BLUE_BD, "#1d4ed8"),
            ("dashboard",
             "📊  Gestisci server",
             "Avvia, ferma, riavvia i siti IIS · stato in tempo reale · log · apri nel browser",
             "#f0fdf4", "#86efac", "#166534"),
            ("release",
             "📦  Gestione Release",
             "Crea/promuovi una release completa, oppure crea e applica un hotfix "
             "leggero dei soli file modificati",
             GREEN_BG, GREEN_BD, "#166534"),
            ("uninstall",
             "🗑  Disinstalla ambiente",
             "Rimuove il sito IIS e l'App Pool di un ambiente (TEST o PROD)",
             "#fff1f2", "#fecdd3", "#be123c"),
        ]

        container = frame(root, bg="white")
        container.pack(fill="x", padx=32)

        for value, title, desc, bg, bd, fg in cards_data:
            card = frame(container, bg=bg,
                         highlightthickness=1, highlightbackground=bd)
            card.pack(fill="x", pady=6)
            card.configure(cursor="hand2")

            inner = frame(card, bg=bg)
            inner.pack(fill="x", padx=16, pady=12)
            inner.configure(cursor="hand2")

            tk.Label(inner, text=title, font=(SF, 10, "bold"),
                     bg=bg, fg=fg, cursor="hand2").pack(anchor="w")
            tk.Label(inner, text=desc, font=FSM,
                     bg=bg, fg=GRAY600, wraplength=520,
                     justify="left", cursor="hand2").pack(anchor="w", pady=(2, 0))

            def _pick(v=value, r=root):
                self._choice = v
                r.after(0, r.destroy)

            def _bind_all(parent, fn):
                parent.bind("<Button-1>", lambda e, f=fn: f())
                for child in parent.winfo_children():
                    _bind_all(child, fn)

            _bind_all(card, _pick)

        frame(root, height=10, bg="white").pack()

        # Footer
        ftr = frame(root, bg=GRAY50, highlightthickness=1, highlightbackground=GRAY100)
        ftr.pack(fill="x", side="bottom")
        tk.Label(ftr, text="Portale Novicrom · Costruzioni Novicrom SRL",
                 font=FSM, fg=GRAY400, bg=GRAY50).pack(pady=10)

        root.mainloop()

    def choice(self):
        return self._choice


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def _ensure_admin(msg: str) -> None:
    """Se non admin, chiede se riavviare elevato. Esce se risponde sì."""
    if is_admin():
        return
    try:
        r = tk.Tk(); r.withdraw()
        ans = messagebox.askyesno("Privilegi insufficienti", msg + "\n\nRiavviare come Amministratore?")
        r.destroy()
        if ans: run_as_admin(); sys.exit(0)
    except Exception:
        pass


def main():
    preselect = None
    mode      = None
    args      = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--env" and i+1 < len(args):
            preselect = args[i+1].lower(); i += 2
        elif args[i].startswith("--env="):
            preselect = args[i].split("=",1)[1].lower(); i += 1
        elif args[i] == "--mode" and i+1 < len(args):
            mode = args[i+1].lower(); i += 2
        elif args[i].startswith("--mode="):
            mode = args[i].split("=",1)[1].lower(); i += 1
        else:
            i += 1

    # ── Modalità forzata da riga di comando ──────────────────
    if mode == "uninstall":
        _ensure_admin("La disinstallazione richiede diritti di Amministratore.")
        UninstallApp(); return

    _release_modes = ("create", "promote", "hotfix-create", "hotfix-apply")
    if mode in ("release", *_release_modes):
        ReleaseApp(initial_mode=mode if mode in _release_modes else None); return

    if mode == "dashboard":
        ServerDashboard(); return

    if mode == "install" or preselect:
        if preselect and preselect not in ("dev","test","prod"):
            print(f"Ambiente non valido: {preselect}"); sys.exit(1)
        if preselect in (None, "test", "prod"):
            _ensure_admin("La configurazione IIS (TEST/PROD) richiede diritti di Amministratore.")
        WizardApp(preselect_env=preselect); return

    # ── Nessun argomento → mostra il launcher ────────────────
    # Ogni app (Wizard/Dashboard/Release/Uninstall), una volta chiusa
    # (X, Annulla o fine flusso), ripresenta il menu di scelta: per uscire
    # dal programma bisogna chiudere il launcher stesso.
    while True:
        launcher = LauncherApp()
        choice = launcher.choice()

        if choice is None:
            return  # utente ha chiuso il launcher

        if choice == "install":
            _ensure_admin("La configurazione IIS (TEST/PROD) richiede diritti di Amministratore.")
            WizardApp()

        elif choice == "dashboard":
            ServerDashboard()

        elif choice == "release":
            ReleaseApp()

        elif choice == "uninstall":
            _ensure_admin("La disinstallazione richiede diritti di Amministratore.")
            UninstallApp()

if __name__ == "__main__":
    main()

