"""
hub_tools/views.py — Strumenti di gestione BrizioHUB

Views:
  /admin-portale/hub/moduli/           → module manager
  /admin-portale/hub/database/         → DB manager (stats, backup, cleanup, ottimizza, ripristino)

Tutte le views richiedono utente staff (is_staff=True).
"""
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from django.contrib.auth.decorators import user_passes_test
from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

_staff_required = user_passes_test(lambda u: u.is_active and u.is_staff, login_url="/login/")

_APP_DIR = Path(__file__).resolve().parent.parent  # django_app/
_BACKUP_DIR = _APP_DIR.parent / "backup" / "db"

# ── Definizione moduli ────────────────────────────────────────────────────────
MODULE_DEFS = [
    # core (sempre attivi)
    {"key": "core",         "name": "Core & Auth",          "icon": "🔐", "desc": "Autenticazione, ACL, navigazione, sessioni", "core": True},
    {"key": "dashboard",    "name": "Dashboard",             "icon": "📊", "desc": "Home operativa modulare con widget per ruolo", "core": True},
    {"key": "admin_portale","name": "Admin Portale",         "icon": "🛠️", "desc": "Gestione utenti, ruoli, permessi, audit e configurazioni", "core": True},
    # opzionali
    {"key": "assenze",      "name": "Gestione Assenze",      "icon": "📅", "desc": "Workflow assenze, ferie, permessi con integrazione SharePoint", "core": False},
    {"key": "anomalie",     "name": "Segnalazioni Anomalie", "icon": "⚠️", "desc": "Raccolta, gestione e tracciamento segnalazioni operative", "core": False},
    {"key": "assets",       "name": "Asset & Officina",      "icon": "🏭", "desc": "Inventario macchinari, work order, schede tecniche, verifiche periodiche", "core": False},
    {"key": "tasks",        "name": "Progetti & Task",       "icon": "📋", "desc": "Gestione progetti con Gantt, task assegnabili e milestone", "core": False},
    {"key": "tickets",      "name": "Ticket IT & Manut.",    "icon": "🎫", "desc": "Sistema ticket IT e manutenzione con priorità e deleghe", "core": False},
    {"key": "notizie",      "name": "Bacheca Notizie",       "icon": "📰", "desc": "Comunicazioni interne, notizie obbligatorie, avvisi", "core": False},
    {"key": "anagrafica",   "name": "Anagrafica",            "icon": "👥", "desc": "Registro centrale dipendenti, fornitori, reparti", "core": False},
    {"key": "automazioni",  "name": "Automazioni",           "icon": "🤖", "desc": "Designer visuale regole, trigger, azioni email e integrazioni", "core": False},
    {"key": "timbri",       "name": "Timbri & Presenze",     "icon": "🕐", "desc": "Timbrature digitali con integrazione SharePoint", "core": False},
    {"key": "planimetria",  "name": "Planimetria",           "icon": "🗺️", "desc": "Mappe interattive stabilimento e posizionamento asset", "core": False},
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


# ══════════════════════════════════════════════════════════════════════════════
# Module Manager
# ══════════════════════════════════════════════════════════════════════════════

@_staff_required
def moduli(request):
    states = _get_module_states()
    modules_ctx = []
    for m in MODULE_DEFS:
        modules_ctx.append({
            **m,
            "enabled": True if m["core"] else states.get(m["key"], True),
        })
    return render(request, "hub_tools/moduli.html", {"modules": modules_ctx})


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
            if not backup_path:
                # Prova a costruire un path sul server SQL
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
