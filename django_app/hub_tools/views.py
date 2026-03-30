"""
hub_tools/views.py — Strumenti di gestione BrizioHUB

Views:
  /admin-portale/hub/moduli/           → module manager
  /admin-portale/hub/database/         → DB manager (stats, backup, cleanup, ottimizza, ripristino)
  /admin-portale/hub/homepage-builder/ → Homepage Builder (visual editor)
  /admin-portale/hub/setup-wizard/     → Setup Wizard riconfigura (legge .env corrente)
  /admin-portale/hub/guide/            → Guide e Manuali (lista)
  /admin-portale/hub/guide/<slug>/     → Visualizza guida specifica

Tutte le views richiedono utente staff (is_staff=True).
"""
import json
import os
import shutil
import socket
import tempfile
from datetime import datetime
from pathlib import Path

from django.http import FileResponse, HttpResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_GET, require_POST

from admin_portale.decorators import legacy_admin_required as _staff_required
from config.app_version import build_module_version_env_block, load_app_version

_APP_DIR = Path(__file__).resolve().parent.parent  # django_app/
_TOOLS_DIR = _APP_DIR.parent / "tools"
_ENV_PATH = _APP_DIR / ".env"

# _BACKUP_DIR: usa BACKUP_DIR da settings (impostato dal wizard in produzione),
# con fallback legacy per ambienti non ancora aggiornati.
def _get_backup_dir() -> Path:
    try:
        from django.conf import settings as _s
        d = getattr(_s, "BACKUP_DIR", None)
        if d:
            return Path(d)
    except Exception:
        pass
    return _APP_DIR.parent / "backup" / "db"

_BACKUP_DIR = _get_backup_dir()


def _is_local_sql_host(host: str) -> bool:
    h = (host or "").strip().lower()
    if h in {"", ".", "(local)", "localhost", "127.0.0.1", "::1"}:
        return True
    local_aliases = {
        socket.gethostname().strip().lower(),
        socket.getfqdn().strip().lower(),
    }
    return h in local_aliases

# ── Catalogo Guide e Manuali ──────────────────────────────────────────────────
GUIDES = [
    {
        "slug": "manuale-navigazione",
        "title": "Manuale Navigazione & Permessi",
        "icon": "📖",
        "file": "MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.html",
        "desc": "Guida completa alla gestione della navigazione, pulsanti legacy, Navigation Builder e permessi utente.",
    },
    {
        "slug": "mappa-moduli",
        "title": "Mappa Moduli",
        "icon": "🗺️",
        "file": "mappa_moduli.html",
        "desc": "Catalogo completo dei moduli del portale con descrizione funzionale, dipendenze e configurazione.",
    },
    {
        "slug": "audit-acl",
        "title": "Audit ACL e Permessi",
        "icon": "🔐",
        "file": "AUDIT_ACL_PERMESSI.html",
        "desc": "Documento di audit tecnico del sistema ACL: pipeline, bug noti, permessi hardcoded e architettura target.",
    },
    {
        "slug": "homepage-builder-guida",
        "title": "Homepage Builder — Guida",
        "icon": "🏠",
        "file": "homepage-builder.html",
        "desc": "Editor visuale con drag&drop nell'anteprima per configurare e riordinare le sezioni della homepage. Supporta griglia app con loghi personalizzati. Genera template Django pronto all'uso.",
    },
    {
        "slug": "setup-wizard-guida",
        "title": "Setup Wizard — Guida",
        "icon": "⚙️",
        "file": "setup-wizard.html",
        "desc": "Guida interattiva al setup iniziale del portale: configurazione database, LDAP, SMTP, moduli e branding.",
    },
    {
        "slug": "schema-layout",
        "title": "Schema Layout Pagine",
        "icon": "📐",
        "file": "schema-layout.html",
        "desc": "Schema visivo del layout del portale: dove si trova la Topnav, la Subnav e il Content, e da dove vengono i dati di ciascuno.",
    },
    {
        "slug": "gestione-permessi",
        "title": "Gestione Permessi",
        "icon": "🔑",
        "file": "GUIDA_GESTIONE_PERMESSI.html",
        "desc": "Guida operativa al sistema ACL: Gestione Accessi (accordion), Wizard Configura Ruolo (AJAX 3 passi) e Matrice Permessi.",
    },
    {
        "slug": "db-documentazione",
        "title": "Documentazione Database",
        "icon": "🗄️",
        "file": "db_documentazione.html",
        "desc": "Schema completo del database: tutte le tabelle, chiavi primarie, foreign key e relazioni inter-app. Ricercabile e navigabile per app.",
    },
]


def _read_env() -> dict:
    """Legge il file .env e restituisce un dizionario chiave→valore (senza virgolette)."""
    values = {}
    if not _ENV_PATH.exists():
        return values
    for raw in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        values[key] = val
    return values

# ── Definizione moduli ────────────────────────────────────────────────────────
MODULE_DEFS = [
    # core (sempre attivi)
    {"key": "core",         "name": "Core & Auth",          "icon": "🔐", "desc": "Autenticazione, ACL, navigazione, sessioni", "core": True,  "home_url": "/"},
    {"key": "dashboard",    "name": "Dashboard",             "icon": "📊", "desc": "Home operativa modulare con widget per ruolo", "core": True,  "home_url": "/"},
    {"key": "admin_portale","name": "Admin Portale",         "icon": "🛠️", "desc": "Gestione utenti, ruoli, permessi, audit e configurazioni", "core": True,  "home_url": "/admin-portale/"},
    # opzionali
    {"key": "assenze",      "name": "Gestione Assenze",      "icon": "📅", "desc": "Workflow assenze, ferie, permessi con integrazione SharePoint", "core": False, "home_url": "/assenze/"},
    {"key": "anomalie",     "name": "Segnalazioni Anomalie", "icon": "⚠️", "desc": "Raccolta, gestione e tracciamento segnalazioni operative", "core": False, "home_url": "/gestione-anomalie"},
    {"key": "assets",       "name": "Asset & Officina",      "icon": "🏭", "desc": "Inventario macchinari, work order, schede tecniche, verifiche periodiche", "core": False, "home_url": "/assets/"},
    {"key": "tasks",        "name": "Progetti & Task",       "icon": "📋", "desc": "Gestione progetti con Gantt, task assegnabili e milestone", "core": False, "home_url": "/tasks/"},
    {"key": "tickets",      "name": "Ticket IT & Manut.",    "icon": "🎫", "desc": "Sistema ticket IT e manutenzione con priorità e deleghe", "core": False, "home_url": "/tickets/"},
    {"key": "notizie",      "name": "Bacheca Notizie",       "icon": "📰", "desc": "Comunicazioni interne, notizie obbligatorie, avvisi", "core": False, "home_url": "/notizie/"},
    {"key": "anagrafica",   "name": "Anagrafica",            "icon": "👥", "desc": "Registro centrale dipendenti, fornitori, reparti", "core": False, "home_url": "/anagrafica/"},
    {"key": "automazioni",  "name": "Automazioni",           "icon": "🤖", "desc": "Designer visuale regole, trigger, azioni email e integrazioni", "core": False, "home_url": "/automazioni/"},
    {"key": "timbri",       "name": "Timbri & Presenze",     "icon": "🕐", "desc": "Timbrature digitali con integrazione SharePoint", "core": False, "home_url": "/timbri/"},
    {"key": "planimetria",  "name": "Planimetria",           "icon": "🗺️", "desc": "Mappe interattive stabilimento e posizionamento asset", "core": False, "home_url": "/planimetria/"},
    {"key": "dpi",          "name": "Gestione DPI",          "icon": "🦺", "desc": "Dispositivi di Protezione Individuale: richieste, approvazione, consegna, storico", "core": False, "home_url": "/dpi/"},
    {"key": "procedure_refresh", "name": "Presa Visione Procedure", "icon": "📄", "desc": "Presa visione MT/MTSI: anagrafica documenti, revisioni, campagne, tracking lettura, report audit", "core": False, "home_url": "/procedure-refresh/"},
]

OPTIONAL_KEYS = [m["key"] for m in MODULE_DEFS if not m["core"]]


def _get_module_states() -> dict[str, bool]:
    """Legge stato visibilità moduli da SiteConfig."""
    try:
        from core.models import SiteConfig
        states = {}
        for key in OPTIONAL_KEYS:
            val = SiteConfig.objects.filter(key=f"module_visible_{key}").values_list("value", flat=True).first()
            states[key] = val in (None, "1", "true", "yes")  # default attivo se non configurato
        return states
    except Exception:
        return {k: True for k in OPTIONAL_KEYS}


def _set_module_state(key: str, enabled: bool) -> None:
    from core.models import SiteConfig
    SiteConfig.objects.update_or_create(
        key=f"module_visible_{key}",
        defaults={"value": "1" if enabled else "0"},
    )


def _get_login_redirect_target() -> str:
    """Restituisce la key del modulo impostato come redirect post-login, o '' se non configurato."""
    try:
        from core.models import SiteConfig
        val = SiteConfig.objects.filter(key="module_login_redirect_target").values_list("value", flat=True).first()
        return val or ""
    except Exception:
        return ""


def _set_login_redirect_target(key: str) -> None:
    """Imposta (o rimuove se key='') il redirect post-login verso un modulo."""
    from core.models import SiteConfig
    SiteConfig.objects.update_or_create(
        key="module_login_redirect_target",
        defaults={"value": key},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Module Manager
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
def moduli(request):
    states = _get_module_states()
    redirect_target = _get_login_redirect_target()
    modules_ctx = []
    for m in MODULE_DEFS:
        modules_ctx.append({
            **m,
            "enabled": True if m["core"] else states.get(m["key"], True),
            "login_redirect": (not m["core"]) and (m["key"] == redirect_target),
        })
    return render(request, "hub_tools/moduli.html", {
        "modules": modules_ctx,
        "login_redirect_target": redirect_target,
    })


@_staff_required
@require_POST
def api_toggle_module(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON non valido"})

    key = (data.get("key") or "").strip()
    enabled = bool(data.get("enabled", True))

    if key not in OPTIONAL_KEYS:
        return JsonResponse({"ok": False, "error": f"Modulo '{key}' non trovato o non modificabile"})

    try:
        _set_module_state(key, enabled)
        action = "attivato" if enabled else "disattivato"
        return JsonResponse({"ok": True, "message": f"Modulo '{key}' {action}."})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)})


@_staff_required
@require_POST
def api_set_login_redirect(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON non valido"})

    key = (data.get("key") or "").strip()

    # key vuota = disabilita redirect
    if key and key not in OPTIONAL_KEYS:
        return JsonResponse({"ok": False, "error": f"Modulo '{key}' non trovato o non modificabile"})

    try:
        _set_login_redirect_target(key)
        if key:
            module = next((m for m in MODULE_DEFS if m["key"] == key), None)
            url = module["home_url"] if module else f"/{key}/"
            return JsonResponse({"ok": True, "target": key, "url": url, "message": f"Redirect post-login impostato su '{key}'."})
        return JsonResponse({"ok": True, "target": "", "url": "", "message": "Redirect post-login disabilitato."})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)})


# ══════════════════════════════════════════════════════════════════════════════
# Database Manager
# ══════════════════════════════════════════════════════════════════════════════

def _get_db_engine() -> str:
    from django.conf import settings
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if "sqlite" in engine:
        return "sqlite"
    if "mssql" in engine or "sqlserver" in engine:
        return "sqlserver"
    return "unknown"


@_staff_required
def database(request):
    engine = _get_db_engine()
    backups = []
    if _BACKUP_DIR.exists():
        for f in sorted(_BACKUP_DIR.iterdir(), reverse=True)[:20]:
            if f.is_file():
                backups.append({
                    "name": f.name,
                    "size": f"{f.stat().st_size / 1024:.1f} KB",
                    "date": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
                })
    return render(request, "hub_tools/database.html", {
        "engine": engine,
        "backups": backups,
    })


@_staff_required
@require_GET
def api_db_stats(request):
    engine = _get_db_engine()
    stats = []
    try:
        if engine == "sqlite":
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = [r[0] for r in cur.fetchall()]
                for t in tables:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM [{t}]")  # noqa: S608
                        count = cur.fetchone()[0]
                        stats.append({"table": t, "rows": count, "size": "—"})
                    except Exception:
                        pass

        elif engine == "sqlserver":
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute("""
                    SELECT
                        t.name AS table_name,
                        p.rows AS row_count,
                        CAST(ROUND((SUM(a.used_pages) * 8) / 1024.0, 2) AS VARCHAR) + ' MB' AS used_size
                    FROM sys.tables t
                    INNER JOIN sys.indexes i ON t.object_id = i.object_id
                    INNER JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
                    INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
                    WHERE t.is_ms_shipped = 0 AND i.object_id > 255
                    GROUP BY t.name, p.rows
                    ORDER BY t.name
                """)
                for row in cur.fetchall():
                    stats.append({"table": row[0], "rows": row[1], "size": row[2]})

        return JsonResponse({"ok": True, "stats": stats, "engine": engine})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)})


@_staff_required
@require_POST
def api_db_backup(request):
    engine = _get_db_engine()
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        if engine == "sqlite":
            from django.conf import settings
            src = settings.DATABASES["default"]["NAME"]
            dst = _BACKUP_DIR / f"db_backup_{ts}.sqlite3"
            shutil.copy2(src, dst)
            return JsonResponse({"ok": True, "message": f"Backup SQLite salvato: {dst.name}"})

        elif engine == "sqlserver":
            try:
                data = json.loads(request.body)
            except Exception:
                data = {}
            backup_path = data.get("backup_path", "").strip()

            from django.conf import settings
            db_name = settings.DATABASES["default"].get("NAME", "")
            db_host = settings.DATABASES["default"].get("HOST", "")
            if not backup_path:
                if _is_local_sql_host(db_host):
                    # SQL Server locale: salva il .bak nella cartella backup del portale.
                    bak_dir = _BACKUP_DIR / "sqlserver"
                    bak_dir.mkdir(parents=True, exist_ok=True)
                    backup_path = str(bak_dir / f"{db_name}_{ts}.bak")
                else:
                    # SQL Server remoto: percorso lato server SQL (non file system web server).
                    backup_path = f"C:\\SQLBackups\\{db_name}_{ts}.bak"

            from django.db import connection
            with connection.cursor() as cur:
                cur.execute(
                    "BACKUP DATABASE ? TO DISK = ? WITH FORMAT, INIT, NAME = ?",
                    [db_name, backup_path, f"BrizioHUB_backup_{ts}"]
                )
            # Registra il backup nella lista locale
            ref_file = _BACKUP_DIR / f"sqlserver_backup_{ts}.ref"
            ref_file.write_text(backup_path, encoding="utf-8")
            return JsonResponse({"ok": True, "message": f"Backup SQL Server avviato → {backup_path}"})

        return JsonResponse({"ok": False, "error": f"Engine '{engine}' non supportato per backup"})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)})


@_staff_required
@require_POST
def api_db_cleanup(request):
    """Pulizia: sessioni scadute, log vecchi, eventi automazione processati."""
    from django.utils import timezone
    results = []

    # Sessioni Django scadute
    try:
        from django.contrib.sessions.models import Session
        deleted, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
        results.append(f"Sessioni scadute eliminate: {deleted}")
    except Exception as exc:
        results.append(f"Sessioni: errore — {exc}")

    # Automation run log vecchi (> 90 giorni)
    try:
        from automazioni.models import AutomationRunLog
        cutoff = timezone.now() - __import__("datetime").timedelta(days=90)
        deleted, _ = AutomationRunLog.objects.filter(executed_at__lt=cutoff).delete()
        results.append(f"AutomationRunLog > 90gg eliminati: {deleted}")
    except Exception as exc:
        results.append(f"AutomationRunLog: {exc}")

    # Automation event queue processati
    try:
        from automazioni.models import AutomationEventQueue
        deleted, _ = AutomationEventQueue.objects.filter(status="processed").delete()
        results.append(f"Event queue processati eliminati: {deleted}")
    except Exception as exc:
        results.append(f"EventQueue: {exc}")

    # Notifiche lette > 30 giorni
    try:
        from core.models import Notifica
        cutoff = timezone.now() - __import__("datetime").timedelta(days=30)
        deleted, _ = Notifica.objects.filter(letta=True, creata_il__lt=cutoff).delete()
        results.append(f"Notifiche lette > 30gg eliminate: {deleted}")
    except Exception as exc:
        results.append(f"Notifiche: {exc}")

    return JsonResponse({"ok": True, "results": results})


@_staff_required
@require_POST
def api_db_optimize(request):
    """Ottimizzazione: VACUUM (SQLite) o UPDATE STATISTICS + rebuild index (SQL Server)."""
    engine = _get_db_engine()
    results = []

    try:
        from django.db import connection

        if engine == "sqlite":
            with connection.cursor() as cur:
                cur.execute("VACUUM")
            results.append("VACUUM eseguito — database compattato.")
            with connection.cursor() as cur:
                cur.execute("ANALYZE")
            results.append("ANALYZE eseguito — statistiche aggiornate.")

        elif engine == "sqlserver":
            from django.conf import settings
            db_name = settings.DATABASES["default"].get("NAME", "")

            with connection.cursor() as cur:
                # UPDATE STATISTICS su tutte le tabelle utente
                cur.execute("""
                    DECLARE @sql NVARCHAR(MAX) = '';
                    SELECT @sql = @sql + 'UPDATE STATISTICS [' + name + '];' + CHAR(13)
                    FROM sys.tables WHERE is_ms_shipped = 0;
                    EXEC sp_executesql @sql;
                """)
            results.append("UPDATE STATISTICS eseguito su tutte le tabelle.")

            with connection.cursor() as cur:
                # Rebuild index frammentati > 30%
                cur.execute("""
                    DECLARE @sql NVARCHAR(MAX) = '';
                    SELECT @sql = @sql +
                        'ALTER INDEX [' + i.name + '] ON [' + t.name + '] REBUILD;' + CHAR(13)
                    FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') s
                    JOIN sys.indexes i ON s.object_id = i.object_id AND s.index_id = i.index_id
                    JOIN sys.tables t ON i.object_id = t.object_id
                    WHERE s.avg_fragmentation_in_percent > 30 AND i.name IS NOT NULL;
                    EXEC sp_executesql @sql;
                """)
            results.append("Index REBUILD completato (soglia frammentazione > 30%).")

        else:
            return JsonResponse({"ok": False, "error": f"Engine '{engine}' non supportato"})

        return JsonResponse({"ok": True, "results": results})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)})


@_staff_required
@require_POST
def api_db_restore(request):
    """Ripristino database da file di backup."""
    engine = _get_db_engine()
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON non valido"})

    backup_name = (data.get("backup_name") or "").strip()
    if not backup_name:
        return JsonResponse({"ok": False, "error": "Nome backup non specificato"})

    try:
        if engine == "sqlite":
            src = _BACKUP_DIR / backup_name
            if not src.exists():
                return JsonResponse({"ok": False, "error": f"File backup non trovato: {backup_name}"})

            from django.conf import settings
            dst = Path(settings.DATABASES["default"]["NAME"])
            # Salva versione corrente come .pre_restore
            pre = dst.with_suffix(".pre_restore")
            shutil.copy2(dst, pre)
            shutil.copy2(src, dst)
            return JsonResponse({"ok": True, "message": f"Database ripristinato da '{backup_name}'. Versione precedente salvata come '{pre.name}'. Riavvia il server."})

        elif engine == "sqlserver":
            from django.conf import settings
            db_name = settings.DATABASES["default"].get("NAME", "")

            # Cerca il ref file per ottenere il path fisico
            ref = _BACKUP_DIR / backup_name
            if not ref.exists():
                return JsonResponse({"ok": False, "error": f"Riferimento backup non trovato: {backup_name}"})
            bak_path = ref.read_text(encoding="utf-8").strip()

            from django.db import connection
            with connection.cursor() as cur:
                cur.execute(
                    "RESTORE DATABASE ? FROM DISK = ? WITH REPLACE, RECOVERY",
                    [db_name, bak_path]
                )
            return JsonResponse({"ok": True, "message": f"Database SQL Server ripristinato da '{bak_path}'. Riavvia il server."})

        return JsonResponse({"ok": False, "error": f"Engine '{engine}' non supportato"})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)})


# ══════════════════════════════════════════════════════════════════════════════
# Homepage Builder
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
def homepage_builder(request):
    """Mostra l'Homepage Builder integrato nell'admin (in iframe)."""
    return render(request, "hub_tools/homepage_builder.html")


@_staff_required
@xframe_options_exempt
@require_GET
def homepage_builder_tool(request):
    """Serve il file standalone homepage-builder.html dalla cartella tools/."""
    filepath = _TOOLS_DIR / "homepage-builder.html"
    if not filepath.exists():
        raise Http404("Homepage Builder non trovato")
    return HttpResponse(filepath.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Setup Wizard — Riconfigura (legge .env corrente)
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
def setup_wizard_hub(request):
    """Mostra il Setup Wizard precompilato con i valori del .env corrente."""
    env = _read_env()
    return render(request, "hub_tools/setup_wizard.html", {"env": env})


# ══════════════════════════════════════════════════════════════════════════════
# Guide e Manuali
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
def db_schema(request):
    """Infografica schema DB: modelli, campi e relazioni."""
    return render(request, "hub_tools/db_schema.html")


@_staff_required
def guide_list(request):
    """Elenco guide e manuali disponibili."""
    return render(request, "hub_tools/guide_list.html", {"guides": GUIDES})


@_staff_required
def guide_view(request, slug):
    """Visualizza una guida specifica in iframe."""
    guide = next((g for g in GUIDES if g["slug"] == slug), None)
    if not guide:
        raise Http404("Guida non trovata")
    return render(request, "hub_tools/guide_view.html", {"guide": guide})


@_staff_required
@xframe_options_exempt
@require_GET
def guide_serve(request, filename):
    """Serve un file HTML dalla cartella tools/ (solo file nel catalogo GUIDES)."""
    allowed = {g["file"] for g in GUIDES}
    if filename not in allowed:
        raise Http404("File non trovato")
    filepath = _TOOLS_DIR / filename
    if not filepath.exists():
        raise Http404("File non trovato")
    return HttpResponse(filepath.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# API Riconfigura — salva .env e config.ini anche a setup già completato
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
@require_POST
def api_reconfigure(request):
    """
    Salva la configurazione nel .env e config.ini senza verificare SETUP_COMPLETED.
    Richiamato dal Setup Wizard hub (riconfigura sistema già installato).
    """
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON non valido"})

    def s(key, default=""):
        return str(data.get(key) or default).strip()

    def b(key, default=False):
        return "1" if data.get(key, default) else "0"

    # Legge il .env attuale per preservare campi non gestiti da questo form
    current_env = _read_env()

    # Preserva SECRET_KEY e SETUP_COMPLETED esistenti
    secret_key = current_env.get("DJANGO_SECRET_KEY", "")
    if not secret_key or secret_key.upper() in ("CHANGE_ME", "CHANGE_ME_FROM_ENV"):
        import secrets as _secrets
        import string as _string
        alphabet = _string.ascii_letters + _string.digits + "!@#$%^&*(-_=+)"
        secret_key = "".join(_secrets.choice(alphabet) for _ in range(50))

    instance_name = s("instance_name", current_env.get("INSTANCE_NAME", "BrizioHUB"))
    app_version = s("app_version", current_env.get("APP_VERSION", load_app_version()))
    module_version_lines = build_module_version_env_block(app_version)
    ldap_enabled_ini = "true" if data.get("ldap_enabled") else "false"

    env_lines = f"""\
# ── BrizioHUB — Configurazione aggiornata da Hub Setup Wizard ─────────────────
INSTANCE_NAME={instance_name}
DJANGO_SECRET_KEY={secret_key}
APP_VERSION={app_version}
{module_version_lines}
DJANGO_DEBUG={current_env.get('DJANGO_DEBUG', '0')}
DJANGO_ALLOWED_HOSTS={current_env.get('DJANGO_ALLOWED_HOSTS', '*')}
SETUP_COMPLETED=1

# Branding
BRANDING_LOGO={current_env.get('BRANDING_LOGO', '')}
BRANDING_FAVICON={current_env.get('BRANDING_FAVICON', '')}

# Sicurezza HTTPS
SECURE_SSL_REDIRECT={b('secure_ssl')}
CSRF_COOKIE_SECURE={b('csrf_secure')}
SESSION_COOKIE_SECURE={b('session_secure')}

# Database
DB_ENGINE={s('db_engine', current_env.get('DB_ENGINE', 'sqlserver'))}
DB_HOST={s('db_host', current_env.get('DB_HOST', ''))}
DB_NAME={s('db_name', current_env.get('DB_NAME', ''))}
DB_USER={s('db_user', current_env.get('DB_USER', ''))}
DB_PASSWORD={s('db_password', current_env.get('DB_PASSWORD', ''))}
DB_DRIVER={s('db_driver', current_env.get('DB_DRIVER', 'ODBC Driver 18 for SQL Server'))}
DB_TRUST_CERT={b('db_trust_cert')}

# Autenticazione e navigazione
LEGACY_AUTH_ENABLED={current_env.get('LEGACY_AUTH_ENABLED', '1')}
NAVIGATION_REGISTRY_ENABLED={b('nav_registry', current_env.get('NAVIGATION_REGISTRY_ENABLED', '0') == '1')}
NAVIGATION_LEGACY_FALLBACK_ENABLED=1
ASSENZE_SYNC_ON_PAGE_LOAD={current_env.get('ASSENZE_SYNC_ON_PAGE_LOAD', '0')}
SESSION_IDLE_TIMEOUT_SECONDS={s('session_timeout', current_env.get('SESSION_IDLE_TIMEOUT_SECONDS', '3600'))}
SESSION_EXPIRE_AT_BROWSER_CLOSE={b('session_expire', True)}
LEGACY_ACL_CACHE_TTL={s('acl_cache_ttl', current_env.get('LEGACY_ACL_CACHE_TTL', '120'))}
LEGACY_NAV_CACHE_TTL={s('nav_cache_ttl', current_env.get('LEGACY_NAV_CACHE_TTL', '120'))}

# Active Directory / LDAP
LDAP_ENABLED={b('ldap_enabled')}
LDAP_SERVER={s('ldap_server', current_env.get('LDAP_SERVER', ''))}
LDAP_DOMAIN={s('ldap_domain', current_env.get('LDAP_DOMAIN', ''))}
LDAP_UPN_SUFFIX={s('ldap_upn', current_env.get('LDAP_UPN_SUFFIX', ''))}
LDAP_TIMEOUT={s('ldap_timeout', current_env.get('LDAP_TIMEOUT', '5'))}
LDAP_SERVICE_USER={s('ldap_service_user', current_env.get('LDAP_SERVICE_USER', ''))}
LDAP_SERVICE_PASSWORD={s('ldap_service_password', current_env.get('LDAP_SERVICE_PASSWORD', ''))}
LDAP_BASE_DN={s('ldap_base_dn', current_env.get('LDAP_BASE_DN', ''))}
LDAP_USER_FILTER={current_env.get('LDAP_USER_FILTER', '(&(objectCategory=person)(objectClass=user))')}
LDAP_GROUP_ALLOWLIST={current_env.get('LDAP_GROUP_ALLOWLIST', '')}
LDAP_SYNC_PAGE_SIZE={current_env.get('LDAP_SYNC_PAGE_SIZE', '500')}

# Microsoft Graph / SharePoint
GRAPH_TENANT_ID={s('graph_tenant_id', current_env.get('GRAPH_TENANT_ID', ''))}
GRAPH_CLIENT_ID={s('graph_client_id', current_env.get('GRAPH_CLIENT_ID', ''))}
GRAPH_CLIENT_SECRET={s('graph_client_secret', current_env.get('GRAPH_CLIENT_SECRET', ''))}
GRAPH_SITE_ID={s('graph_site_id', current_env.get('GRAPH_SITE_ID', ''))}
GRAPH_LIST_ID_ASSENZE={s('graph_list_assenze', current_env.get('GRAPH_LIST_ID_ASSENZE', ''))}
GRAPH_LIST_ID_DIPENDENTI={s('graph_list_dipendenti', current_env.get('GRAPH_LIST_ID_DIPENDENTI', ''))}
GRAPH_LIST_ID_CAPOREPARTO={s('graph_list_caporeparto', current_env.get('GRAPH_LIST_ID_CAPOREPARTO', ''))}
GRAPH_LIST_ID_ANOMALIE_DB={s('graph_list_anomalie_db', current_env.get('GRAPH_LIST_ID_ANOMALIE_DB', ''))}

# Assenze
ASSENZE_SP_PULL_INTERVAL_SECONDS={current_env.get('ASSENZE_SP_PULL_INTERVAL_SECONDS', '300')}
ASSENZE_CALENDAR_MAX_EVENTS={current_env.get('ASSENZE_CALENDAR_MAX_EVENTS', '1500')}
ASSENZE_CALENDAR_COLORS_CACHE_TTL={current_env.get('ASSENZE_CALENDAR_COLORS_CACHE_TTL', '300')}

# SQL logging
SQL_LOG_ENABLED={current_env.get('SQL_LOG_ENABLED', '0')}
SQL_LOG_LEVEL={current_env.get('SQL_LOG_LEVEL', 'DEBUG')}
SQL_LOG_FORCE_DEBUG_CURSOR={current_env.get('SQL_LOG_FORCE_DEBUG_CURSOR', '0')}
SQL_LOG_MAX_BYTES={current_env.get('SQL_LOG_MAX_BYTES', '10485760')}
SQL_LOG_BACKUP_COUNT={current_env.get('SQL_LOG_BACKUP_COUNT', '10')}

# SMTP
EMAIL_HOST={s('email_host', current_env.get('EMAIL_HOST', ''))}
EMAIL_PORT={s('email_port', current_env.get('EMAIL_PORT', '587'))}
EMAIL_HOST_USER={s('email_user', current_env.get('EMAIL_HOST_USER', ''))}
EMAIL_HOST_PASSWORD={s('email_password', current_env.get('EMAIL_HOST_PASSWORD', ''))}
EMAIL_USE_TLS={b('email_tls', True)}
DEFAULT_FROM_EMAIL={s('email_from', current_env.get('DEFAULT_FROM_EMAIL', ''))}
"""

    # Aggiorna anche config.ini
    _CONFIG_INI_PATH = _APP_DIR.parent / "config.ini"
    ini_lines = f"""\
; BrizioHUB — Configurazione aggiornata da Hub Setup Wizard

[APP]
debug = False
secret_key = LOADED_FROM_ENV

[DATABASE]
path = {current_env.get('LEGACY_DB_PATH', 'utenti.db')}

[SQLSERVER]
server = {s('db_host', current_env.get('DB_HOST', ''))}
database = {s('db_name', current_env.get('DB_NAME', ''))}
driver = {s('db_driver', current_env.get('DB_DRIVER', 'ODBC Driver 18 for SQL Server'))}
username = {s('db_user', current_env.get('DB_USER', ''))}
password = {s('db_password', current_env.get('DB_PASSWORD', ''))}
encrypt = yes
trust_server_certificate = {'yes' if data.get('db_trust_cert') else 'no'}
login_timeout = 5

[CACHE]
foto_ttl = 600
assenze_ttl = {s('session_timeout', current_env.get('ASSENZE_SP_PULL_INTERVAL_SECONDS', '300'))}
capi_ttl = 600

[AZIENDA]
tenant_id = {s('graph_tenant_id', current_env.get('GRAPH_TENANT_ID', ''))}
client_id = {s('graph_client_id', current_env.get('GRAPH_CLIENT_ID', ''))}
client_secret = {s('graph_client_secret', current_env.get('GRAPH_CLIENT_SECRET', ''))}
site_id = {s('graph_site_id', current_env.get('GRAPH_SITE_ID', ''))}
list_id_assenze = {s('graph_list_assenze', current_env.get('GRAPH_LIST_ID_ASSENZE', ''))}
list_id_dipendenti = {s('graph_list_dipendenti', current_env.get('GRAPH_LIST_ID_DIPENDENTI', ''))}
list_id_caporeparto = {s('graph_list_caporeparto', current_env.get('GRAPH_LIST_ID_CAPOREPARTO', ''))}
list_id_anomalie_db = {s('graph_list_anomalie_db', current_env.get('GRAPH_LIST_ID_ANOMALIE_DB', ''))}

[ACTIVE_DIRECTORY]
enabled = {ldap_enabled_ini}
server = {s('ldap_server', current_env.get('LDAP_SERVER', ''))}
domain = {s('ldap_domain', current_env.get('LDAP_DOMAIN', ''))}
upn_suffix = {s('ldap_upn', current_env.get('LDAP_UPN_SUFFIX', ''))}
timeout = {s('ldap_timeout', current_env.get('LDAP_TIMEOUT', '5'))}
service_user = {s('ldap_service_user', current_env.get('LDAP_SERVICE_USER', ''))}
service_password = {s('ldap_service_password', current_env.get('LDAP_SERVICE_PASSWORD', ''))}
base_dn = {s('ldap_base_dn', current_env.get('LDAP_BASE_DN', ''))}

[DEFAULT]
default_password = CHANGE_ME
"""

    try:
        _ENV_PATH.write_text(env_lines, encoding="utf-8")
        _CONFIG_INI_PATH.write_text(ini_lines, encoding="utf-8")
        return JsonResponse({"ok": True, "message": "Configurazione salvata con successo. Riavvia il server per applicare le modifiche al database/LDAP."})
    except PermissionError as exc:
        return JsonResponse({"ok": False, "error": f"Permessi insufficienti per scrivere .env: {exc}"})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)})


# ══════════════════════════════════════════════════════════════════════════════
# Categorie moduli
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
def categorie(request):
    from django.shortcuts import redirect

    from core.branding import PORTAL_BRANDING_DEFAULTS
    from core.models import ModuleCategory, NavigationItem, SiteConfig
    from core.navigation_registry import bump_navigation_registry_version

    branding_keys = {
        "portal_name": "Nome portale globale.",
        "portal_subtitle": "Sottotitolo branding globale.",
        "brand_logo_full": "URL logo esteso usato nella sidebar espansa.",
        "brand_logo_compact": "URL logo compatto usato nella sidebar collassata.",
    }

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "branding":
            for key, description in branding_keys.items():
                SiteConfig.set(key, request.POST.get(key, "").strip(), description)
        elif action == "create":
            key = request.POST.get("key", "").strip()
            label = request.POST.get("label", "").strip()
            icon = request.POST.get("icon", "").strip()
            color = request.POST.get("topbar_color", "#1e3a5f").strip()
            order = int(request.POST.get("order", 100) or 100)
            if key and label:
                ModuleCategory.objects.get_or_create(
                    key=key,
                    defaults={"label": label, "icon": icon, "topbar_color": color, "order": order},
                )
                bump_navigation_registry_version()
        elif action == "edit":
            cat_id = request.POST.get("id")
            try:
                cat = ModuleCategory.objects.get(pk=cat_id)
                cat.label = request.POST.get("label", cat.label).strip() or cat.label
                cat.icon = request.POST.get("icon", cat.icon).strip()
                cat.topbar_color = request.POST.get("topbar_color", cat.topbar_color).strip() or cat.topbar_color
                cat.order = int(request.POST.get("order", cat.order) or cat.order)
                cat.save()
                bump_navigation_registry_version()
            except ModuleCategory.DoesNotExist:
                pass
        elif action == "delete":
            cat_id = request.POST.get("id")
            ModuleCategory.objects.filter(pk=cat_id).delete()
            bump_navigation_registry_version()
        elif action == "assign":
            nav_item_id = request.POST.get("nav_item_id")
            cat_id = request.POST.get("category_id") or None
            try:
                nav_item = NavigationItem.objects.get(pk=nav_item_id)
                nav_item.category_id = int(cat_id) if cat_id else None
                nav_item.save(update_fields=["category"])
                bump_navigation_registry_version()
            except NavigationItem.DoesNotExist:
                pass
        elif action == "item_icon":
            nav_item_id = request.POST.get("nav_item_id")
            try:
                nav_item = NavigationItem.objects.get(pk=nav_item_id)
                nav_item.icon = request.POST.get("icon", "").strip()
                nav_item.save(update_fields=["icon"])
                bump_navigation_registry_version()
            except NavigationItem.DoesNotExist:
                pass
        return redirect("hub_tools:hub_categorie")

    cats = list(ModuleCategory.objects.all())
    nav_items = list(NavigationItem.objects.filter(section="topbar").select_related("category").order_by("order", "label"))
    branding_values = SiteConfig.get_many(
        {
            "portal_name": PORTAL_BRANDING_DEFAULTS["portal_name"],
            "portal_subtitle": PORTAL_BRANDING_DEFAULTS["portal_subtitle"],
            "brand_logo_full": PORTAL_BRANDING_DEFAULTS["brand_logo_full"],
            "brand_logo_compact": PORTAL_BRANDING_DEFAULTS["brand_logo_compact"],
        }
    )
    return render(request, "hub_tools/categorie.html", {
        "categorie": cats,
        "nav_items": nav_items,
        "branding_values": branding_values,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Gestione Notifiche
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
def notifiche_hub(request):
    """Dashboard notifiche: lista, filtri, statistiche, invio manuale."""
    from core.models import Notifica
    from core.legacy_anagrafica import fetch_anagrafica_rows

    # Filtri
    f_tipo    = request.GET.get("tipo", "").strip()
    f_letta   = request.GET.get("letta", "").strip()   # "si" | "no" | ""
    f_user_id = request.GET.get("user_id", "").strip()
    f_q       = request.GET.get("q", "").strip()

    qs = Notifica.objects.all()
    if f_tipo:
        qs = qs.filter(tipo=f_tipo)
    if f_letta == "si":
        qs = qs.filter(letta=True)
    elif f_letta == "no":
        qs = qs.filter(letta=False)
    if f_user_id and f_user_id.isdigit():
        qs = qs.filter(legacy_user_id=int(f_user_id))
    if f_q:
        qs = qs.filter(messaggio__icontains=f_q)

    qs = qs.order_by("-created_at")

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    # Stats
    totale     = Notifica.objects.count()
    non_lette  = Notifica.objects.filter(letta=False).count()
    lette      = totale - non_lette
    popup_pend = Notifica.objects.filter(letta=False, popup_shown=False).count()

    # Conteggio per tipo
    from django.db.models import Count
    tipo_label_map = dict(Notifica.TIPI)
    per_tipo_raw = {
        row["tipo"]: row["n"]
        for row in Notifica.objects.values("tipo").annotate(n=Count("id")).order_by()
    }
    per_tipo_list = [
        {"value": v, "label": tipo_label_map.get(v, v), "count": c}
        for v, c in sorted(per_tipo_raw.items(), key=lambda x: -x[1])
        if c > 0
    ]

    # Arricchisce ogni notifica con il nome utente
    visible_ids = list({n.legacy_user_id for n in page.object_list})
    user_names: dict[int, str] = {}
    if visible_ids:
        try:
            rows = fetch_anagrafica_rows(ids=visible_ids)
            for r in rows:
                uid = int(r.get("id") or 0)
                if uid:
                    user_names[uid] = f"{r.get('cognome','')} {r.get('nome','')}".strip()
        except Exception:
            pass
    for n in page.object_list:
        n.user_nome = user_names.get(n.legacy_user_id, "")

    # Lista dipendenti per form invio
    try:
        dipendenti = [
            {"id": int(r.get("id") or 0), "nome": f"{r.get('cognome','')} {r.get('nome','')}".strip(), "reparto": r.get("reparto","") or ""}
            for r in fetch_anagrafica_rows()
            if int(r.get("id") or 0) > 0
        ]
        reparti = sorted({d["reparto"] for d in dipendenti if d["reparto"]})
    except Exception:
        dipendenti = []
        reparti = []

    return render(request, "hub_tools/notifiche.html", {
        "page_obj":    page,
        "user_names":  user_names,
        "f_tipo":      f_tipo,
        "f_letta":     f_letta,
        "f_user_id":   f_user_id,
        "f_q":         f_q,
        "tipi":        Notifica.TIPI,
        "totale":      totale,
        "non_lette":   non_lette,
        "lette":       lette,
        "popup_pend":  popup_pend,
        "per_tipo_list": per_tipo_list,
        "dipendenti":  dipendenti,
        "reparti":     reparti,
    })


@_staff_required
@require_POST
def api_notifica_invia(request):
    """Invia notifica manuale a: singolo utente / reparto / tutti."""
    from core.notifiche import invia_notifica
    from core.legacy_anagrafica import fetch_anagrafica_rows

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)

    destinatario = (data.get("destinatario") or "").strip()  # "utente" | "reparto" | "tutti"
    tipo         = (data.get("tipo") or "generico").strip()
    messaggio    = (data.get("messaggio") or "").strip()
    url_azione   = (data.get("url_azione") or "").strip()

    if not messaggio:
        return JsonResponse({"ok": False, "error": "Il messaggio è obbligatorio"}, status=400)

    from core.models import Notifica
    tipi_validi = {t[0] for t in Notifica.TIPI}
    if tipo not in tipi_validi:
        tipo = "generico"

    # Raccoglie i legacy_user_id destinatari
    target_ids: list[int] = []

    if destinatario == "utente":
        uid_str = str(data.get("user_id") or "").strip()
        if not uid_str.isdigit():
            return JsonResponse({"ok": False, "error": "user_id non valido"}, status=400)
        target_ids = [int(uid_str)]

    elif destinatario == "reparto":
        reparto = (data.get("reparto") or "").strip()
        if not reparto:
            return JsonResponse({"ok": False, "error": "Reparto non specificato"}, status=400)
        try:
            rows = fetch_anagrafica_rows()
            target_ids = [
                int(r.get("id") or 0)
                for r in rows
                if str(r.get("reparto") or "").strip().casefold() == reparto.casefold()
                and int(r.get("id") or 0) > 0
            ]
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    elif destinatario == "tutti":
        try:
            rows = fetch_anagrafica_rows()
            target_ids = [int(r.get("id") or 0) for r in rows if int(r.get("id") or 0) > 0]
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    else:
        return JsonResponse({"ok": False, "error": "Destinatario non valido"}, status=400)

    if not target_ids:
        return JsonResponse({"ok": False, "error": "Nessun destinatario trovato"}, status=400)

    count = 0
    for uid in target_ids:
        invia_notifica(
            legacy_user_id=uid,
            tipo=tipo,
            messaggio=messaggio,
            url_azione=url_azione,
        )
        count += 1

    return JsonResponse({"ok": True, "count": count, "message": f"Notifica inviata a {count} destinatari."})


@_staff_required
@require_POST
def api_notifica_elimina(request, notifica_id: int):
    """Elimina una singola notifica."""
    from core.models import Notifica
    deleted, _ = Notifica.objects.filter(pk=notifica_id).delete()
    return JsonResponse({"ok": bool(deleted)})


@_staff_required
@require_POST
def api_notifiche_bulk(request):
    """Azioni bulk: elimina_lette | elimina_utente | segna_lette_tutte."""
    from core.models import Notifica
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)

    azione = (data.get("azione") or "").strip()

    if azione == "elimina_lette":
        deleted, _ = Notifica.objects.filter(letta=True).delete()
        return JsonResponse({"ok": True, "count": deleted, "message": f"Eliminate {deleted} notifiche lette."})

    elif azione == "elimina_utente":
        uid_str = str(data.get("user_id") or "").strip()
        if not uid_str.isdigit():
            return JsonResponse({"ok": False, "error": "user_id non valido"}, status=400)
        deleted, _ = Notifica.objects.filter(legacy_user_id=int(uid_str)).delete()
        return JsonResponse({"ok": True, "count": deleted, "message": f"Eliminate {deleted} notifiche per l'utente."})

    elif azione == "segna_lette_tutte":
        updated = Notifica.objects.filter(letta=False).update(letta=True, popup_shown=True)
        return JsonResponse({"ok": True, "count": updated, "message": f"Segnate come lette {updated} notifiche."})

    return JsonResponse({"ok": False, "error": "Azione non riconosciuta"}, status=400)
