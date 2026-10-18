"""Task django-q del motore di backup (accodati dalla pagina «Backup e ripristino»).

I backup veri girano da Task Scheduler; qui solo operazioni brevi su richiesta.
"""
from __future__ import annotations

from .config import load_config


def verify_task(set_id: str | None = None) -> dict:
    """Verifica un set (o l'ultimo FULL con i suoi LOG). L'esito va in BackupRun (kind=verify)."""
    from . import engine

    cfg = load_config()
    if set_id:
        targets = [cfg.env_root / set_id]
    else:
        full = engine.latest_set(cfg, "full")
        if full is None:
            return {"status": "failed", "error": "nessun FULL nel target"}
        targets = [full.path] + [s.path for s in engine._log_sets_for(cfg, full.set_id)]
    results = [engine.verify_set(cfg, p) for p in targets if p.exists()]
    return {"status": max((r.status for r in results), key=lambda s: {"ok": 0, "warning": 1}.get(s, 2), default="failed"),
            "sets": {r.set_id: r.status for r in results}}
