"""Retention GFS dei backup set e garbage collection dello store dei file.

Regole:
- FULL, FILES, HOST: tenuti tutti i set riusciti degli ultimi ``keep_daily`` giorni,
  poi il più recente di ogni settimana ISO (ultime ``keep_weekly``) e di ogni mese
  (ultimi ``keep_monthly``);
- LOG: vive finché esiste il FULL su cui poggia e comunque non oltre ``keep_log_days``;
- **mai** cancellato l'ultimo FULL verificato né un set protetto (es. usato
  dall'ultimo drill riuscito) né i LOG che lo seguono;
- i set falliti non occupano posti GFS e si eliminano dopo ``keep_daily`` giorni.
Il piano è sempre calcolato e registrato prima di cancellare (dry-run di default).
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

SET_RE = re.compile(r"^(\d{8}_\d{6})_(full|log|files|host)$")


@dataclass
class SetInfo:
    set_id: str
    kind: str
    created: datetime
    status: str = "ok"
    verified: bool = True
    chain_base: str | None = None     # per i LOG: set FULL di riferimento
    path: Path | None = None


@dataclass
class RetentionPlan:
    keep: dict[str, str] = field(default_factory=dict)      # set_id -> motivo
    delete: dict[str, str] = field(default_factory=dict)    # set_id -> motivo


def parse_set_id(set_id: str) -> tuple[datetime, str] | None:
    m = SET_RE.match(set_id)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"), m.group(2)


def _gfs(sets: list[SetInfo], now: datetime, daily: int, weekly: int, monthly: int) -> dict[str, str]:
    keep: dict[str, str] = {}
    ok = sorted((s for s in sets if s.status != "failed"), key=lambda s: s.created, reverse=True)
    seen_day, seen_week, seen_month = set(), set(), set()
    for s in ok:
        age_days = (now.date() - s.created.date()).days
        day = s.created.date()
        week = tuple(s.created.isocalendar()[:2])
        month = (s.created.year, s.created.month)
        if age_days < daily:
            # tutti i set recenti, non uno al giorno: un FULL manuale in giornata non deve
            # far sparire il FULL delle 02:00 e i log che poggiano su di esso (buco nel ripristino puntuale)
            seen_day.add(day)
            keep.setdefault(s.set_id, "giornaliero")
        if len(seen_week) < weekly and week not in seen_week:
            seen_week.add(week)
            keep.setdefault(s.set_id, "settimanale")
        if len(seen_month) < monthly and month not in seen_month:
            seen_month.add(month)
            keep.setdefault(s.set_id, "mensile")
    return keep


def plan(sets: list[SetInfo], now: datetime, *, keep_daily: int, keep_weekly: int, keep_monthly: int,
         keep_log_days: int, protected: set[str] | None = None) -> RetentionPlan:
    protected = set(protected or ())
    result = RetentionPlan()
    by_kind: dict[str, list[SetInfo]] = {}
    for s in sets:
        by_kind.setdefault(s.kind, []).append(s)

    for kind in ("full", "files", "host"):
        group = by_kind.get(kind, [])
        result.keep.update(_gfs(group, now, keep_daily, keep_weekly, keep_monthly))

    fulls = sorted(by_kind.get("full", []), key=lambda s: s.created, reverse=True)
    last_verified = next((s for s in fulls if s.status != "failed" and s.verified), None)
    if last_verified:
        result.keep[last_verified.set_id] = "ultimo FULL verificato"
    for sid in protected:
        if any(s.set_id == sid for s in sets):
            result.keep[sid] = "protetto (drill)"

    log_limit = now - timedelta(days=keep_log_days)
    for s in by_kind.get("log", []):
        if s.set_id in protected:
            continue
        base_kept = s.chain_base in result.keep
        follows_protected = s.chain_base in protected or (last_verified and s.chain_base == last_verified.set_id)
        if s.status == "failed" and s.created < now - timedelta(days=keep_daily):
            continue
        if follows_protected or (base_kept and s.created >= log_limit):
            result.keep[s.set_id] = "catena log"

    for s in sets:
        if s.set_id in result.keep:
            continue
        if s.status == "failed" and s.created >= now - timedelta(days=keep_daily):
            result.keep[s.set_id] = "fallito recente (diagnosi)"
            continue
        if s.kind == "log":
            result.delete[s.set_id] = "log senza FULL di base o oltre la retention"
        elif s.status == "failed":
            result.delete[s.set_id] = "fallito"
        else:
            result.delete[s.set_id] = "fuori dalla retention GFS"
    return result


def apply(plan_: RetentionPlan, sets: list[SetInfo], log=lambda msg: None) -> int:
    removed = 0
    by_id = {s.set_id: s for s in sets}
    for sid, reason in sorted(plan_.delete.items()):
        s = by_id.get(sid)
        if s is None or s.path is None or not s.path.exists():
            continue
        shutil.rmtree(s.path)
        removed += 1
        log(f"eliminato {sid} ({reason})")
    return removed


def gc_objects(objects_root: Path, referenced: set[str], dry_run: bool = True) -> tuple[int, int]:
    """Elimina gli oggetti non più referenziati da nessun indice di set conservato."""
    removed = freed = 0
    root = Path(objects_root)
    if not root.exists():
        return 0, 0
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        for obj in sub.iterdir():
            if obj.name.startswith("."):
                continue
            if obj.name not in referenced:
                freed += obj.stat().st_size
                removed += 1
                if not dry_run:
                    obj.unlink()
    return removed, freed
