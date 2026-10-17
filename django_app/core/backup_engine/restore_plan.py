"""Piano di ripristino a un punto nel tempo, calcolato dai soli manifest del target.

Nessuna dipendenza da Django né dal database: si usa anche da una macchina nuova
(``hub_restore_plan`` o ``restore-host.ps1``), con il portale ancora da installare.

Il piano contiene: il FULL di partenza, i LOG in ordine (con ``STOPAT`` sull'ultimo
se il punto cade dentro un log), lo snapshot dei file e la fotografia della macchina
più recenti non oltre il punto, la release esatta e le impronte attese delle chiavi.
Fallisce se la catena dei log ha buchi.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SET_RE = re.compile(r"^(\d{8}_\d{6})_(full|log|files|host)$")
PLAN_VERSION = 1


class PlanError(ValueError):
    pass


@dataclass
class _Set:
    set_id: str
    kind: str
    created: datetime
    path: Path
    data: dict


def _lsn(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def load_sets(env_root: Path) -> list[_Set]:
    out: list[_Set] = []
    root = Path(env_root)
    if not root.exists():
        return out
    for d in root.iterdir():
        m = SET_RE.match(d.name) if d.is_dir() else None
        mp = d / "manifest.json"
        if not m or not mp.exists():
            continue
        try:
            data = json.loads(mp.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if data.get("status") == "failed":
            continue
        out.append(_Set(d.name, m.group(2), datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"), d, data))
    return sorted(out, key=lambda s: s.created)


def _latest(sets: list[_Set], kind: str, until: datetime | None) -> _Set | None:
    cands = [s for s in sets if s.kind == kind and (until is None or s.created <= until)]
    return cands[-1] if cands else None


def build_plan(env_root: Path, target_time: datetime | None = None) -> dict:
    sets = load_sets(env_root)
    full = _latest(sets, "full", target_time)
    if full is None:
        raise PlanError("Nessun backup FULL riuscito " + (f"prima di {target_time:%Y-%m-%d %H:%M}" if target_time else "nel target"))
    warnings: list[str] = []

    logs = [s for s in sets if s.kind == "log" and (s.data.get("chain") or {}).get("full_set_id") == full.set_id]
    chosen: list[_Set] = []
    stopat = None
    for s in logs:
        chosen.append(s)
        if target_time is not None and s.created >= target_time:
            stopat = target_time
            break
    if target_time is not None and stopat is None:
        if chosen:
            warnings.append(f"Punto richiesto oltre l'ultimo log ({chosen[-1].created:%Y-%m-%d %H:%M}): "
                            "si ripristina all'ultimo log disponibile.")
        elif target_time > full.created:
            warnings.append(f"Nessun log dopo il FULL {full.set_id}: si ripristina al FULL ({full.created:%Y-%m-%d %H:%M}).")

    databases: dict[str, dict] = {}
    for art in full.data.get("artifacts", []):
        if art.get("kind") == "full":
            databases[art["database"]] = {"full": {"set_id": full.set_id, "path": f"{full.set_id}/{art['path']}",
                                                  "sha256": art["sha256"], "lsn": art.get("lsn")}, "logs": []}
    for db, entry in databases.items():
        prev_last = _lsn((entry["full"].get("lsn") or {}).get("last"))
        first_log = True
        for s in chosen:
            chain = ((s.data.get("chain") or {}).get("databases") or {}).get(db)
            art = next((a for a in s.data.get("artifacts", []) if a.get("database") == db and a.get("kind") == "log"), None)
            if not chain or not art:
                raise PlanError(f"{db}: il log {s.set_id} non contiene questo database: catena interrotta.")
            first, last = _lsn(chain["first_lsn"]), _lsn(chain["last_lsn"])
            if first_log:
                if prev_last >= 0 and first > prev_last:
                    raise PlanError(f"{db}: il primo log {s.set_id} non copre il FULL (FirstLSN {first} > {prev_last}).")
                first_log = False
            elif first != prev_last:
                raise PlanError(f"{db}: buco nella catena prima di {s.set_id} (FirstLSN {first} ≠ LastLSN {prev_last}).")
            prev_last = last
            entry["logs"].append({"set_id": s.set_id, "path": f"{s.set_id}/{art['path']}", "sha256": art["sha256"],
                                  "first_lsn": chain["first_lsn"], "last_lsn": chain["last_lsn"]})

    files = _latest(sets, "files", target_time) or _latest(sets, "files", None)
    if files and target_time and files.created > target_time:
        warnings.append("Nessuno snapshot dei file prima del punto richiesto: si usa il più vecchio disponibile.")
    host = _latest(sets, "host", target_time) or _latest(sets, "host", None)
    if not files:
        warnings.append("Nessun backup dei file nel target.")
    if not host:
        warnings.append("Nessuna fotografia della macchina nel target.")
    app = full.data.get("app") or {}
    release_ref = (host.data.get("release_ref") if host else None) or full.data.get("release_ref")
    if not release_ref:
        warnings.append("Zip della release non presente nel target: va recuperato da shared\\packages o rigenerato dal commit.")
    restore_point = stopat or (chosen[-1].created if chosen else full.created)
    return {
        "plan_version": PLAN_VERSION,
        "env": full.data.get("env"),
        "requested_time": target_time.isoformat() if target_time else None,
        "restore_point": restore_point.isoformat(),
        "stopat": stopat.isoformat() if stopat else None,
        "full_set_id": full.set_id,
        "last_log_set_id": chosen[-1].set_id if chosen else None,
        "databases": databases,
        "sql": full.data.get("sql"),
        "files_set_id": files.set_id if files else None,
        "files_index": f"{files.set_id}/files/index.json" if files else None,
        "host_set_id": host.set_id if host else None,
        "host_manifest": f"{host.set_id}/host/host-manifest.json" if host else None,
        "release": {"version": app.get("version"), "commit": app.get("commit"), "branch": app.get("branch"),
                    "zip": release_ref},
        "migrations": app.get("migrations") or {},
        "expected_keys": {k: (full.data.get("keys") or {}).get(k)
                          for k in ("document_encryption_key_sha256", "secret_key_sha256")},
        "row_counts": full.data.get("row_counts") or {},
        "warnings": warnings,
    }


def latest_restore_point(env_root: Path) -> datetime | None:
    """Punto ripristinabile più recente (per l'RPO): None se il piano non si costruisce."""
    try:
        return datetime.fromisoformat(build_plan(env_root)["restore_point"])
    except PlanError:
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI senza Django: ``python restore_plan.py <BACKUP_TARGET>\\<env> [--target-time "AAAA-MM-GG HH:MM"] [--out file]``."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Piano di ripristino NOVICROM HUB (dai soli manifest)")
    ap.add_argument("env_root", help="Cartella dei backup dell'ambiente, es. \\\\nas\\hub-backup\\prod")
    ap.add_argument("--target-time", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    when = datetime.strptime(args.target_time, "%Y-%m-%d %H:%M") if args.target_time else None
    try:
        plan = build_plan(Path(args.env_root), when)
    except PlanError as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"OK: piano scritto in {args.out} (punto di ripristino {plan['restore_point']})")
    else:
        print(text)
    for w in plan["warnings"]:
        print(f"AVVISO: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
