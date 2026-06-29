"""Task django-q del modulo procedure_refresh.

``run_sgi_share_check``: watchdog che rileva i documenti SGI **nuovi/aggiornati**
sulla share non ancora importati e apre una Issue **informativa** nella centrale
monitoring. L'import resta un'azione **umana** (``import_sgi_da_share --apply`` +
``index_sgi_documents``): qui si NOTIFICA soltanto. Fail-safe assoluto.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_CHECK_NAME = "sgi_share_drift"


def run_sgi_share_check(**kwargs) -> dict:
    """Confronta la share SGI col DB e apre/risolve una Issue se ci sono documenti
    nuovi o con revisione più alta da importare. Ritorna un riepilogo (per i log/test).
    Non scrive mai sui documenti."""
    result: dict = {"ok": True, "skipped": False, "new": 0, "updated": 0}
    try:
        raw_root = str(getattr(settings, "PROCEDURE_REFRESH_SGI_SHARE_ROOT", "") or "").strip()
        if not raw_root:
            result.update(skipped=True, reason="PROCEDURE_REFRESH_SGI_SHARE_ROOT non impostato")
            return result
        root = Path(raw_root)
        if not root.exists():
            result.update(skipped=True, reason=f"root non raggiungibile: {raw_root}")
            return result

        from procedure_refresh.management.commands.import_sgi_da_share import detect_share_drift

        drift = detect_share_drift(root)
        n_new, n_upd = len(drift["new"]), len(drift["updated"])
        result.update(new=n_new, updated=n_upd, in_db=drift.get("in_db", 0))

        try:
            from monitoring.models import Issue
            from monitoring.services import (
                open_or_update_issue_from_health_check,
                resolve_health_check_issue,
            )
        except Exception:
            # monitoring non disponibile: il risultato resta nei log, niente Issue.
            logger.info("sgi_share_check: nuovi=%d aggiornati=%d (monitoring assente)", n_new, n_upd)
            return result

        if n_new or n_upd:
            sample = ", ".join(d["code"] for d in (drift["new"] + drift["updated"])[:10])
            open_or_update_issue_from_health_check(
                check_name=_CHECK_NAME,
                title=f"SGI: {n_new} documenti nuovi + {n_upd} aggiornati da importare",
                message=(
                    f"Documenti sulla share non ancora indicizzati dall'AI (es.: {sample}). "
                    "Azione umana: `manage.py import_sgi_da_share --apply` poi `index_sgi_documents`."
                ),
                severity=Issue.Severity.LOW,
                module_name="procedure_refresh",
                extra_json={"new": drift["new"][:50], "updated": drift["updated"][:50]},
                notify=False,  # informativo: compare in "Stato sistema", niente email
            )
        else:
            resolve_health_check_issue(
                check_name=_CHECK_NAME,
                summary="Nessun documento SGI nuovo/aggiornato sulla share.",
            )
        return result
    except Exception as exc:  # fail-safe: un watchdog non deve mai far rumore in cluster
        logger.warning("run_sgi_share_check fallito: %s", exc)
        result.update(ok=False, error=str(exc))
        return result
