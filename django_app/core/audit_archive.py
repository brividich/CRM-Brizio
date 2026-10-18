"""Archiviazione e pulizia dello storico ``core_auditlog`` (BUILD_SPEC R0.3/R0.4).

Classifica le righe esistenti con **la stessa** ``core.audit_policy`` usata dai
segnali, così archivio e scrittura non possono divergere:

- ``tecnico``      → righe ``auto_*`` di modelli di classe B: archiviate complete, poi cancellate;
- ``update_nullo`` → righe ``auto_update`` di classe D senza modifiche significative:
  archiviate complete, poi cancellate;
- ``contenuti``    → righe ``auto_*`` di classe C che contengono valori: archiviate e
  aggiornate in DB **a soli metadati** (la traccia chi/cosa/quando resta);
- ``keep``         → tutto il resto (classe A, chiamate esplicite ``log_action``,
  ``login_fallito``): mai toccato dalla categoria ``policy``.

La categoria ``business`` archivia (e poi rimuove dal DB) le sole righe ``keep``
più vecchie di almeno 60 mesi: soglia minima imposta, non riducibile.

Archivio: ``<dir>/auditlog/<YYYY-MM>/part-<n>.jsonl.gz`` + ``manifest.json`` per mese.
Ogni parte è scritta su file temporaneo, rinominata, riletta e verificata con
SHA-256 **prima** di cancellare o ridurre le righe in DB. Stato di ripresa in
``<dir>/audit_archive_state.json``.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

from core import audit_policy

logger = logging.getLogger(__name__)

AUTO_AZIONI = ("auto_insert", "auto_update", "auto_delete")
CATEGORIE_POLICY = ("tecnico", "update_nullo", "contenuti")
MAX_SQL_PARAMS = 1000          # limite SQL Server = 2100 parametri per statement
BULK_UPDATE_BATCH = 400        # bulk_update usa ~3 parametri per riga
BUSINESS_MIN_MONTHS = audit_policy.AUDIT_RETENTION_POLICY["A"]["online_months"]
ARCHIVE_KEEP_MONTHS = audit_policy.AUDIT_RETENTION_POLICY["archive_months"]
STATE_FILE = "audit_archive_state.json"
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,100}$")
_VALUE_KEYS = ("valori", "modifiche", "nuovi_valori")
_FIELDS = (
    "id", "created_at", "legacy_user_id", "utente_display", "azione", "modulo",
    "dettaglio", "ip_address", "oggetto_tipo", "oggetto_id",
)


class ArchiveError(RuntimeError):
    pass


# ── Classificazione ──────────────────────────────────────────────────────────

def _model_key(row: dict) -> str:
    det = row.get("dettaglio") if isinstance(row.get("dettaglio"), dict) else {}
    return f"{str(row.get('modulo') or '').lower()}.{str(det.get('model') or '').lower()}"


_IGNORED_CACHE: dict[str, frozenset[str]] = {}


def _ignored_for_key(key: str) -> frozenset[str]:
    if key not in _IGNORED_CACHE:
        app_label, _, model_name = key.partition(".")
        try:
            model = apps.get_model(app_label, model_name)
            names = audit_policy.ignored_fields(model)
        except (LookupError, ValueError):
            names = frozenset(audit_policy.IGNORED_FIELDS.get(key, ())) | audit_policy.ALWAYS_IGNORED_FOR_CHANGE_DETECTION
        _IGNORED_CACHE[key] = names
    return _IGNORED_CACHE[key]


def classify_row(row: dict) -> str:
    """Categoria di una riga esistente secondo la politica corrente."""
    azione = row.get("azione") or ""
    if azione not in AUTO_AZIONI:
        return "keep"
    key = _model_key(row)
    classe = audit_policy.classify_key(key)
    det = row.get("dettaglio") if isinstance(row.get("dettaglio"), dict) else {}
    if classe == "excluded":
        return "tecnico"
    if classe == "metadata_only":
        return "contenuti" if any(k in det for k in _VALUE_KEYS) else "keep"
    if azione == "auto_update" and key in audit_policy.IGNORED_FIELDS and "nuovi_valori" not in det:
        modifiche = det.get("modifiche") or {}
        ignorati = _ignored_for_key(key)
        if not [k for k in modifiche if k not in ignorati]:
            return "update_nullo"
    return "keep"


def reduce_to_metadata(dettaglio: dict) -> dict:
    """Dettaglio di classe C ridotto a soli metadati (nomi campi, mai valori)."""
    det = dettaglio if isinstance(dettaglio, dict) else {}
    out = {k: det[k] for k in ("model", "pk", "oggetto") if k in det}
    if isinstance(det.get("valori"), dict):
        out["campi_valorizzati"] = sorted(
            k for k, v in det["valori"].items() if v not in (None, "", [], {})
        )
    campi = set()
    for k in ("modifiche", "nuovi_valori"):
        if isinstance(det.get(k), dict):
            campi.update(det[k])
    if campi:
        out["campi"] = sorted(campi)
    out["_ridotto"] = {"da": "audit_archive", "policy": audit_policy.AUDIT_POLICY_VERSION}
    return out


# ── File di archivio ─────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json_atomic(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _row_to_json(row: dict, categoria: str) -> dict:
    out = {}
    for k in _FIELDS:
        v = row.get(k)
        out[k] = v.isoformat() if isinstance(v, (datetime, date)) else v
    out["_categoria"] = categoria
    return out


def _month_of(row: dict) -> str:
    created = row.get("created_at")
    if isinstance(created, datetime):
        if timezone.is_aware(created):
            created = timezone.localtime(created)
        return created.strftime("%Y-%m")
    return "senza-data"


def _read_manifest(month_dir: Path) -> dict:
    p = month_dir / "manifest.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"month": month_dir.name, "parts": []}


def write_part(archive_dir: Path, month: str, records: list[dict]) -> dict:
    """Scrive una parte gz su file temporaneo, la verifica e aggiorna il manifest."""
    month_dir = archive_dir / "auditlog" / month
    month_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(month_dir)
    n = len(manifest["parts"]) + 1
    while (month_dir / f"part-{n:05d}.jsonl.gz").exists():
        n += 1
    final = month_dir / f"part-{n:05d}.jsonl.gz"
    tmp = month_dir / f".part-{n:05d}.jsonl.gz.tmp"
    h = hashlib.sha256()

    class _Tee:
        def __init__(self, fh):
            self.fh = fh

        def write(self, b):
            h.update(b)
            return self.fh.write(b)

        def flush(self):
            self.fh.flush()

    with open(tmp, "wb") as raw:
        tee = _Tee(raw)
        with gzip.GzipFile(fileobj=tee, mode="wb", mtime=0) as gz:
            for rec in records:
                gz.write((json.dumps(rec, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
        raw.flush()
        os.fsync(raw.fileno())
    expected = h.hexdigest()
    os.replace(tmp, final)
    actual = _sha256_file(final)
    if actual != expected:
        raise ArchiveError(f"Verifica hash fallita per {final.name}: atteso {expected}, letto {actual}")
    # rilettura completa: il gzip deve essere integro e contenere tutte le righe
    with gzip.open(final, "rt", encoding="utf-8") as gz:
        lette = sum(1 for _ in gz)
    if lette != len(records):
        raise ArchiveError(f"{final.name}: righe rilette {lette} ≠ scritte {len(records)}")
    ids = [r["id"] for r in records]
    categorie: dict[str, int] = defaultdict(int)
    for r in records:
        categorie[r.get("_categoria", "")] += 1
    part = {
        "file": final.name,
        "rows": len(records),
        "id_min": min(ids),
        "id_max": max(ids),
        "sha256": expected,
        "categorie": dict(categorie),
        "written_at": timezone.now().isoformat(),
    }
    manifest["parts"].append(part)
    manifest.update({
        "month": month,
        "policy_version": audit_policy.AUDIT_POLICY_VERSION,
        "rows": sum(p["rows"] for p in manifest["parts"]),
        "id_min": min(p["id_min"] for p in manifest["parts"]),
        "id_max": max(p["id_max"] for p in manifest["parts"]),
        "updated_at": timezone.now().isoformat(),
    })
    _write_json_atomic(month_dir / "manifest.json", manifest)
    return part


def verify_month(month_dir: Path) -> tuple[bool, list[str]]:
    """Verifica tutte le parti di un mese contro il manifest."""
    errori: list[str] = []
    mp = month_dir / "manifest.json"
    if not mp.exists():
        return False, ["manifest.json assente"]
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [f"manifest illeggibile: {exc}"]
    for part in manifest.get("parts", []):
        p = month_dir / part["file"]
        if not p.exists():
            errori.append(f"{part['file']}: mancante")
        elif _sha256_file(p) != part["sha256"]:
            errori.append(f"{part['file']}: sha256 non corrisponde")
    return not errori, errori


# ── Stato di ripresa ─────────────────────────────────────────────────────────

def _load_state(archive_dir: Path) -> dict:
    p = archive_dir / STATE_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            logger.warning("audit_archive: stato illeggibile, si riparte dall'inizio")
    return {}


def _save_state(archive_dir: Path, state: dict) -> None:
    state["updated_at"] = timezone.now().isoformat()
    _write_json_atomic(archive_dir / STATE_FILE, state)


# ── Scansione ────────────────────────────────────────────────────────────────

def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _base_queryset(category: str, before: datetime | None):
    from core.models import AuditLog

    qs = AuditLog.objects.all()
    if category == "policy":
        qs = qs.filter(azione__in=AUTO_AZIONI)
    if before is not None:
        qs = qs.filter(created_at__lt=before)
    return qs


def _iter_batches(category: str, before, batch: int, start_id: int = 0):
    last_id = start_id
    base = _base_queryset(category, before)
    while True:
        rows = list(base.filter(id__gt=last_id).order_by("id").values(*_FIELDS)[:batch])
        if not rows:
            return
        yield rows
        last_id = rows[-1]["id"]


def _target_categories(category: str) -> tuple[str, ...]:
    return ("keep",) if category == "business" else CATEGORIE_POLICY


def business_cutoff(older_than_months: int, today: date | None = None) -> datetime:
    if older_than_months < BUSINESS_MIN_MONTHS:
        raise ArchiveError(
            f"La categoria business richiede almeno {BUSINESS_MIN_MONTHS} mesi "
            f"(politica di conservazione): ricevuto {older_than_months}."
        )
    today = today or timezone.localdate()
    y, m = divmod(today.year * 12 + (today.month - 1) - older_than_months, 12)
    return timezone.make_aware(datetime(y, m + 1, 1))


@dataclass
class PlanStats:
    righe_lette: int = 0
    per_gruppo: dict = field(default_factory=dict)

    def add(self, categoria: str, row: dict):
        det = row.get("dettaglio")
        key = (categoria, row.get("modulo") or "", (det or {}).get("model", "") if isinstance(det, dict) else "")
        g = self.per_gruppo.setdefault(key, {"righe": 0, "byte": 0, "da": None, "a": None})
        g["righe"] += 1
        # stima: JSON in nvarchar (UTF-16) ≈ 2 byte per carattere
        g["byte"] += 2 * len(json.dumps(det, ensure_ascii=False, default=str))
        created = row.get("created_at")
        if created is not None:
            g["da"] = created if g["da"] is None or created < g["da"] else g["da"]
            g["a"] = created if g["a"] is None or created > g["a"] else g["a"]

    def as_rows(self) -> list[dict]:
        out = []
        for (cat, modulo, model), g in sorted(self.per_gruppo.items(), key=lambda kv: -kv[1]["byte"]):
            out.append({
                "categoria": cat, "modulo": modulo, "modello": model, "righe": g["righe"],
                "mb_stimati": round(g["byte"] / 1_048_576, 2),
                "da": g["da"].isoformat() if g["da"] else None,
                "a": g["a"].isoformat() if g["a"] else None,
            })
        return out


def plan(category: str = "policy", before: datetime | None = None, batch: int = 20000) -> PlanStats:
    """Dry-run: nessuna scrittura, né in DB né su disco."""
    stats = PlanStats()
    targets = _target_categories(category)
    for rows in _iter_batches(category, before, batch):
        for row in rows:
            stats.righe_lette += 1
            cat = classify_row(row)
            if cat in targets:
                stats.add(cat, row)
    return stats


@dataclass
class RunResult:
    righe_lette: int = 0
    archiviate: int = 0
    cancellate: int = 0
    ridotte: int = 0
    parti: int = 0
    last_id: int = 0
    completato: bool = False
    interrotto_per_tempo: bool = False


def _checkpoint_if_simple() -> None:
    if connection.vendor != "microsoft":
        return
    with connection.cursor() as cur:
        cur.execute("SELECT recovery_model_desc FROM sys.databases WHERE name = DB_NAME()")
        row = cur.fetchone()
        if row and str(row[0]).upper() == "SIMPLE":
            cur.execute("CHECKPOINT")


def run(
    archive_dir: Path,
    *,
    category: str = "policy",
    before: datetime | None = None,
    batch: int = 20000,
    max_minutes: float | None = None,
    checkpoint: bool = False,
    resume: bool = True,
    _after_archive_hook=None,
) -> RunResult:
    """Archivia e poi cancella/riduce. Le righe ``keep`` (categoria policy) non sono mai toccate."""
    from core.models import AuditLog

    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    targets = _target_categories(category)
    state = _load_state(archive_dir)
    state_key = f"{category}:{before.isoformat() if before else '-'}"
    start_id = int(state.get("runs", {}).get(state_key, {}).get("last_id", 0)) if resume else 0
    result = RunResult(last_id=start_id)
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None

    for rows in _iter_batches(category, before, batch, start_id):
        da_cancellare: list[int] = []
        da_ridurre: list[tuple[int, dict]] = []
        per_mese: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            result.righe_lette += 1
            cat = classify_row(row)
            if cat not in targets:
                continue
            if cat == "contenuti":
                ridotto = reduce_to_metadata(row["dettaglio"])
                per_mese[_month_of(row)].append(_row_to_json({**row, "dettaglio": ridotto}, cat))
                da_ridurre.append((row["id"], ridotto))
            else:
                per_mese[_month_of(row)].append(_row_to_json(row, cat))
                da_cancellare.append(row["id"])

        # 1) archivio scritto e verificato
        for month, records in sorted(per_mese.items()):
            write_part(archive_dir, month, records)
            result.parti += 1
            result.archiviate += len(records)
        if _after_archive_hook:
            _after_archive_hook()

        # 2) solo dopo: DB, in transazioni brevi per lotto
        with transaction.atomic():
            for ids in _chunks(da_cancellare, MAX_SQL_PARAMS):
                AuditLog.objects.filter(id__in=ids).delete()
                result.cancellate += len(ids)
            if da_ridurre:
                objs = [AuditLog(id=i, dettaglio=d) for i, d in da_ridurre]
                AuditLog.objects.bulk_update(objs, ["dettaglio"], batch_size=BULK_UPDATE_BATCH)
                result.ridotte += len(objs)

        result.last_id = rows[-1]["id"]
        state.setdefault("runs", {})[state_key] = {
            "last_id": result.last_id,
            "policy_version": audit_policy.AUDIT_POLICY_VERSION,
        }
        _save_state(archive_dir, state)
        if checkpoint:
            _checkpoint_if_simple()
        if deadline and time.monotonic() >= deadline:
            result.interrotto_per_tempo = True
            return result

    result.completato = True
    state.setdefault("runs", {})[state_key] = {
        "last_id": result.last_id,
        "completed_at": timezone.now().isoformat(),
        "policy_version": audit_policy.AUDIT_POLICY_VERSION,
    }
    _save_state(archive_dir, state)
    return result


# ── Rilettura per verifiche ispettive ────────────────────────────────────────

def _restore_ddl(table: str) -> str:
    if connection.vendor == "microsoft":
        text, big, dt = "NVARCHAR(MAX)", "BIGINT", "DATETIME2"
        return (
            f"IF OBJECT_ID(N'{table}', N'U') IS NULL CREATE TABLE [{table}] ("
            f"id {big} NOT NULL PRIMARY KEY, created_at {dt} NULL, legacy_user_id INT NULL, "
            f"utente_display NVARCHAR(200) NULL, azione NVARCHAR(100) NULL, modulo NVARCHAR(100) NULL, "
            f"dettaglio {text} NULL, ip_address NVARCHAR(64) NULL, oggetto_tipo NVARCHAR(100) NULL, "
            f"oggetto_id NVARCHAR(64) NULL, categoria NVARCHAR(32) NULL)"
        )
    return (
        f'CREATE TABLE IF NOT EXISTS "{table}" ('
        "id INTEGER NOT NULL PRIMARY KEY, created_at TEXT NULL, legacy_user_id INTEGER NULL, "
        "utente_display TEXT NULL, azione TEXT NULL, modulo TEXT NULL, dettaglio TEXT NULL, "
        "ip_address TEXT NULL, oggetto_tipo TEXT NULL, oggetto_id TEXT NULL, categoria TEXT NULL)"
    )


def restore(source: Path, into_table: str = "core_auditlog_restored") -> int:
    """Rilegge un manifest (tutte le parti) o una parte in una tabella separata."""
    from core.models import AuditLog

    if not _TABLE_RE.match(into_table or ""):
        raise ArchiveError(f"Nome tabella non valido: {into_table!r}")
    if into_table.lower() == AuditLog._meta.db_table.lower():
        raise ArchiveError("Il ripristino dentro core_auditlog non è ammesso: usa una tabella separata.")
    source = Path(source)
    if source.name == "manifest.json":
        ok, errori = verify_month(source.parent)
        if not ok:
            raise ArchiveError("Archivio non integro: " + "; ".join(errori))
        manifest = json.loads(source.read_text(encoding="utf-8"))
        parts = [source.parent / p["file"] for p in manifest.get("parts", [])]
    else:
        parts = [source]
    qn = connection.ops.quote_name
    cols = list(_FIELDS) + ["categoria"]
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {qn(into_table)} ({', '.join(qn(c) for c in cols)}) VALUES ({placeholders})"
    totale = 0
    visti: set = set()  # una ripresa dopo errore può aver archiviato due volte le stesse righe
    with connection.cursor() as cur:
        cur.execute(_restore_ddl(into_table))
        for part in parts:
            with gzip.open(part, "rt", encoding="utf-8") as gz:
                buf = []
                for line in gz:
                    rec = json.loads(line)
                    if rec.get("id") in visti:
                        continue
                    visti.add(rec.get("id"))
                    buf.append([
                        rec.get("id"), rec.get("created_at"), rec.get("legacy_user_id"),
                        rec.get("utente_display"), rec.get("azione"), rec.get("modulo"),
                        json.dumps(rec.get("dettaglio"), ensure_ascii=False),
                        rec.get("ip_address"), rec.get("oggetto_tipo"), rec.get("oggetto_id"),
                        rec.get("_categoria"),
                    ])
                    if len(buf) >= 500:
                        cur.executemany(sql, buf)
                        totale += len(buf)
                        buf = []
                if buf:
                    cur.executemany(sql, buf)
                    totale += len(buf)
    return totale


# ── Conservazione degli archivi (120 mesi) ───────────────────────────────────

def prune_archives(archive_dir: Path, *, keep_months: int = ARCHIVE_KEEP_MONTHS, apply: bool = False,
                   today: date | None = None) -> list[dict]:
    """Elenca (e con ``apply`` elimina) i mesi oltre ``keep_months``. Mai senza manifest verificato."""
    if keep_months < ARCHIVE_KEEP_MONTHS:
        raise ArchiveError(f"La conservazione minima degli archivi è {ARCHIVE_KEEP_MONTHS} mesi.")
    today = today or timezone.localdate()
    limite = today.year * 12 + (today.month - 1) - keep_months
    root = Path(archive_dir) / "auditlog"
    esiti: list[dict] = []
    if not root.exists():
        return esiti
    for month_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        m = re.match(r"^(\d{4})-(\d{2})$", month_dir.name)
        if not m:
            continue
        idx = int(m.group(1)) * 12 + int(m.group(2)) - 1
        if idx >= limite:
            continue
        ok, errori = verify_month(month_dir)
        esito = {"mese": month_dir.name, "verificato": ok, "errori": errori, "eliminato": False}
        if ok and apply:
            shutil.rmtree(month_dir)
            esito["eliminato"] = True
        esiti.append(esito)
        logger.info("audit_archive prune: %s", esito)
    return esiti
