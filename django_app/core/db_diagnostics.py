"""Diagnostica non distruttiva del database: capacità, crescita dell'audit, cache.

Usata da ``hub_backup_doctor``, dal check ``audit_growth`` del monitoring e (R2)
dalla pagina «Backup e ripristino». Solo letture: nessuna modifica al DB.
Sui DB diversi da SQL Server le sezioni specifiche tornano ``supported: False``.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from core import audit_policy

logger = logging.getLogger(__name__)

MB = 1024 * 1024
# Limite di dimensione per database dell'edizione Express (MB), per versione major.
EXPRESS_LIMIT_MB = {"default": 10 * 1024, 17: 50 * 1024}   # 17 = SQL Server 2025
CAPACITY_WARN_PCT = 70
CAPACITY_CRIT_PCT = 85
GROWTH_WARN_MB_MONTH = 500
SATURATION_CRIT_DAYS = 60


def _is_mssql() -> bool:
    return connection.vendor == "microsoft"


def _fetchall(sql: str, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()


def edition_limit_mb(edition: str, product_version: str) -> int | None:
    """Limite per database dell'edizione (MB); None se l'edizione non ha limite noto."""
    if "express" not in (edition or "").lower():
        return None
    try:
        major = int(str(product_version).split(".")[0])
    except (TypeError, ValueError):
        major = 0
    return EXPRESS_LIMIT_MB.get(major, EXPRESS_LIMIT_MB["default"])


def server_capacity() -> dict:
    """Spazio allocato/usato dei file dati del DB corrente rispetto al limite dell'edizione."""
    if not _is_mssql():
        return {"supported": False}
    row = _fetchall(
        "SELECT CAST(SERVERPROPERTY('Edition') AS NVARCHAR(128)), "
        "CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(64)), "
        "(SELECT recovery_model_desc FROM sys.databases WHERE name = DB_NAME()), "
        "(SELECT log_reuse_wait_desc FROM sys.databases WHERE name = DB_NAME()), DB_NAME()"
    )[0]
    edition, version, recovery, log_wait, dbname = row
    files = _fetchall(
        "SELECT type_desc, SUM(CAST(size AS BIGINT)) * 8 / 1024.0, "
        "SUM(CAST(FILEPROPERTY(name, 'SpaceUsed') AS BIGINT)) * 8 / 1024.0 "
        "FROM sys.database_files GROUP BY type_desc"
    )
    data_alloc = data_used = log_alloc = log_used = 0.0
    for type_desc, alloc, used in files:
        if type_desc == "ROWS":
            data_alloc, data_used = float(alloc or 0), float(used or 0)
        elif type_desc == "LOG":
            log_alloc, log_used = float(alloc or 0), float(used or 0)
    limit = edition_limit_mb(edition, version)
    pct = round(data_used / limit * 100, 1) if limit else None
    level = "ok"
    if pct is not None:
        level = "critical" if pct >= CAPACITY_CRIT_PCT else "warning" if pct >= CAPACITY_WARN_PCT else "ok"
    return {
        "supported": True, "database": dbname, "edition": edition, "product_version": version,
        "recovery_model": recovery, "log_reuse_wait": log_wait,
        "data_allocated_mb": round(data_alloc, 1), "data_used_mb": round(data_used, 1),
        "log_allocated_mb": round(log_alloc, 1), "log_used_mb": round(log_used, 1),
        "limit_mb": limit, "used_pct": pct, "level": level,
    }


def top_tables(limit: int = 15) -> list[dict]:
    if not _is_mssql():
        return []
    rows = _fetchall(
        f"SELECT TOP {int(limit)} s.name + '.' + t.name, "
        "SUM(CASE WHEN p.index_id IN (0,1) THEN p.row_count ELSE 0 END), "
        "SUM(p.reserved_page_count) * 8 / 1024.0 "
        "FROM sys.dm_db_partition_stats p JOIN sys.tables t ON t.object_id = p.object_id "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "GROUP BY s.name, t.name ORDER BY SUM(p.reserved_page_count) DESC"
    )
    return [{"tabella": n, "righe": int(r or 0), "mb": round(float(mb or 0), 1)} for n, r, mb in rows]


def _auditlog_table_size() -> tuple[int, float | None]:
    from core.models import AuditLog

    table = AuditLog._meta.db_table
    if _is_mssql():
        row = _fetchall(
            "SELECT SUM(CASE WHEN index_id IN (0,1) THEN row_count ELSE 0 END), "
            "SUM(reserved_page_count) * 8 / 1024.0 FROM sys.dm_db_partition_stats "
            "WHERE object_id = OBJECT_ID(%s)", [table]
        )[0]
        return int(row[0] or 0), float(row[1] or 0)
    if connection.vendor == "sqlite":
        # stima: lunghezza del dettaglio (il resto della riga è trascurabile)
        n, size = _fetchall(f"SELECT COUNT(*), SUM(LENGTH(dettaglio)) FROM {table}")[0]
        return int(n or 0), (float(size or 0) / MB if n else None)
    return AuditLog.objects.count(), None


def audit_growth(days: int = 7, months: int = 6, top: int = 10) -> dict:
    """Crescita di ``core_auditlog``: ultimi ``days`` giorni, mensile, top modelli."""
    from django.db.models import Count
    from django.db.models.functions import TruncMonth

    from core.models import AuditLog

    now = timezone.now()
    total_rows, table_mb = _auditlog_table_size()
    since = now - timedelta(days=days)
    recent_rows = AuditLog.objects.filter(created_at__gte=since).count()
    mb_per_row = (table_mb / total_rows) if (table_mb and total_rows) else None
    recent_mb = round(recent_rows * mb_per_row, 1) if mb_per_row else None
    month_start = (now - timedelta(days=31 * months)).replace(day=1)
    mensile = [
        {"mese": r["mese"].strftime("%Y-%m") if r["mese"] else "", "righe": r["n"],
         "mb_stimati": round(r["n"] * mb_per_row, 1) if mb_per_row else None}
        for r in (
            AuditLog.objects.filter(created_at__gte=month_start)
            .annotate(mese=TruncMonth("created_at")).values("mese")
            .annotate(n=Count("id")).order_by("mese")
        )
    ]
    return {
        "policy_version": audit_policy.AUDIT_POLICY_VERSION,
        "total_rows": total_rows,
        "table_mb": round(table_mb, 1) if table_mb is not None else None,
        "days": days,
        "recent_rows": recent_rows,
        "recent_mb": recent_mb,
        "daily_mb": round(recent_mb / days, 2) if recent_mb is not None else None,
        "monthly_projection_mb": round(recent_mb / days * 30, 1) if recent_mb is not None else None,
        "monthly": mensile,
        "top_models": top_models(days=days, limit=top),
    }


def top_models(days: int = 7, limit: int = 10) -> list[dict]:
    """Top modelli per volume di audit (righe e byte del dettaglio) negli ultimi giorni."""
    since = timezone.now() - timedelta(days=days)
    if _is_mssql():
        sql = (
            f"SELECT TOP {int(limit)} modulo, azione, "
            "ISNULL(JSON_VALUE(dettaglio, '$.model'), '') AS model, COUNT(*), "
            "SUM(CAST(DATALENGTH(dettaglio) AS BIGINT)) FROM core_auditlog "
            "WHERE created_at >= %s AND ISJSON(dettaglio) = 1 "
            "GROUP BY modulo, azione, ISNULL(JSON_VALUE(dettaglio, '$.model'), '') "
            "ORDER BY SUM(CAST(DATALENGTH(dettaglio) AS BIGINT)) DESC"
        )
    elif connection.vendor == "sqlite":
        sql = (
            "SELECT modulo, azione, COALESCE(json_extract(dettaglio, '$.model'), '') AS model, "
            "COUNT(*), SUM(LENGTH(dettaglio)) FROM core_auditlog WHERE created_at >= %s "
            "GROUP BY modulo, azione, model ORDER BY SUM(LENGTH(dettaglio)) DESC LIMIT "
            f"{int(limit)}"
        )
    else:
        return []
    try:
        rows = _fetchall(sql, [since])
    except Exception:
        logger.warning("db_diagnostics: top_models non disponibile", exc_info=True)
        return []
    return [
        {"modulo": m, "azione": a, "modello": mod, "righe": int(n or 0),
         "mb": round(float(b or 0) / MB, 2),
         "classe": audit_policy.classify_key(f"{(m or '').lower()}.{(mod or '').lower()}") if mod else "full"}
        for m, a, mod, n, b in rows
    ]


def saturation_forecast(capacity: dict, growth: dict) -> dict:
    """Giorni alla saturazione del limite dell'edizione ai ritmi dell'audit attuali."""
    limit = capacity.get("limit_mb")
    used = capacity.get("data_used_mb")
    daily = growth.get("daily_mb")
    if not limit or used is None or not daily or daily <= 0:
        return {"days_to_limit": None}
    return {"days_to_limit": int(max(limit - used, 0) / daily)}


def cache_diagnostics(top: int = 10) -> dict:
    """Diagnostica della tabella ``DatabaseCache`` (solo lettura)."""
    cfg = (getattr(settings, "CACHES", {}) or {}).get("default", {})
    if "DatabaseCache" not in str(cfg.get("BACKEND", "")):
        return {"supported": False, "backend": cfg.get("BACKEND", "")}
    table = str(cfg.get("LOCATION") or "")
    if not table.replace("_", "").isalnum():
        return {"supported": False, "error": "nome tabella cache non valido"}
    qn = connection.ops.quote_name(table)
    length = "DATALENGTH" if _is_mssql() else "LENGTH"
    try:
        n, scadute, media, massimo = _fetchall(
            f"SELECT COUNT(*), SUM(CASE WHEN expires < %s THEN 1 ELSE 0 END), "
            f"AVG(CAST({length}(value) AS BIGINT)), MAX(CAST({length}(value) AS BIGINT)) FROM {qn}",
            [timezone.now()],
        )[0]
        if _is_mssql():
            prefix = "LEFT(cache_key, CASE WHEN CHARINDEX(':', cache_key, 4) > 0 THEN CHARINDEX(':', cache_key, 4) ELSE LEN(cache_key) END)"
            top_sql = (f"SELECT TOP {int(top)} {prefix} AS p, COUNT(*), SUM(CAST(DATALENGTH(value) AS BIGINT)) "
                       f"FROM {qn} GROUP BY {prefix} ORDER BY SUM(CAST(DATALENGTH(value) AS BIGINT)) DESC")
        else:
            prefix = "substr(cache_key, 1, CASE WHEN instr(substr(cache_key, 4), ':') > 0 THEN instr(substr(cache_key, 4), ':') + 3 ELSE length(cache_key) END)"
            top_sql = (f"SELECT {prefix} AS p, COUNT(*), SUM(LENGTH(value)) FROM {qn} "
                       f"GROUP BY p ORDER BY SUM(LENGTH(value)) DESC LIMIT {int(top)}")
        prefissi = [{"prefisso": p, "righe": int(c or 0), "mb": round(float(b or 0) / MB, 2)}
                    for p, c, b in _fetchall(top_sql)]
    except Exception as exc:
        return {"supported": True, "table": table, "error": f"{exc.__class__.__name__}"}
    return {
        "supported": True, "table": table, "rows": int(n or 0), "expired_rows": int(scadute or 0),
        "avg_value_bytes": int(media or 0), "max_value_bytes": int(massimo or 0), "top_prefixes": prefissi,
    }


def audit_growth_status(capacity: dict, growth: dict) -> tuple[str, str]:
    """(livello, messaggio) per il check ``audit_growth``: ok / warning / critical."""
    forecast = saturation_forecast(capacity, growth)
    days = forecast.get("days_to_limit")
    monthly = growth.get("monthly_projection_mb")
    if days is not None and days < SATURATION_CRIT_DAYS:
        return "critical", f"Saturazione del limite dell'edizione prevista tra {days} giorni."
    if monthly is not None and monthly > GROWTH_WARN_MB_MONTH:
        return "warning", f"Crescita dell'audit proiettata {monthly:.0f} MB/mese (soglia {GROWTH_WARN_MB_MONTH})."
    return "ok", ""
