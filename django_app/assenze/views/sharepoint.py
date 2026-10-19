"""Viste del modulo Assenze — Sincronizzazione SharePoint (push/pull).

Spacchettamento di ``assenze/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""

from __future__ import annotations

import logging
import time
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods



from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


_SYNC_PULL_LOCK_KEY = "assenze:sync_pull:lock"
_SYNC_PULL_LOCK_TTL = 120
_SP_DELTA_LINK_KEY = "assenze:sp_delta_link"


def _sync_push(limit_rows: int = 30, include_updates: bool = False) -> dict:
    if not _helpers._table_exists("assenze"):
        return {"ok": False, "error": "Tabella assenze non disponibile"}
    if not _helpers._graph_configured():
        return {"ok": False, "error": "SharePoint non configurato"}
    # Stesso lock della coda: due invii paralleli creerebbero l'elemento due volte.
    if not cache.add(_helpers._SP_PUSH_LOCK_KEY, "1", timeout=_helpers._SP_PUSH_LOCK_TTL):
        return {"ok": False, "error": "Invio a SharePoint gia' in corso, riprova tra poco"}
    try:
        _helpers._set_automation_queue_skip(True)
        return _sync_push_locked(limit_rows=limit_rows, include_updates=include_updates)
    finally:
        _helpers._set_automation_queue_skip(False)
        cache.delete(_helpers._SP_PUSH_LOCK_KEY)


def _sync_push_locked(limit_rows: int, include_updates: bool) -> dict:

    limit_rows = max(1, min(int(limit_rows or 30), 300))
    where_sql = "1=1" if include_updates else f"{_helpers._blank_expr('sharepoint_item_id')} IS NULL"

    base_sql = f"""
        SELECT
            id,
            sharepoint_item_id,
            nome_lookup_id,
            capo_reparto_lookup_id,
            copia_nome,
            email_esterna,
            tipo_assenza,
            data_inizio,
            data_fine,
            motivazione_richiesta,
            salta_approvazione,
            consenso
        FROM assenze
        WHERE {where_sql}
    """
    sql = _helpers._select_limited(base_sql, "ORDER BY COALESCE(modified_datetime, created_datetime) ASC, id ASC", limit_rows)
    rows = _helpers._fetch_all_dict(sql)

    inserted = 0
    updated = 0
    failed = 0
    details: list[dict] = []

    for row in rows:
        local_id = int(row["id"])
        try:
            result = _helpers._sync_one_to_sharepoint(local_id, force_update=include_updates)
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "sync fallita"))
            if result.get("action") == "create":
                inserted += 1
            else:
                updated += 1
            details.append({"local_id": local_id, "sharepoint_item_id": result.get("sharepoint_item_id"), "action": result.get("action")})
        except Exception as exc:
            failed += 1
            details.append({"local_id": local_id, "error": str(exc)})
            _helpers.logger.exception("[assenze:sync_push] errore local_id=%s", local_id)

    return {
        "ok": failed == 0,
        "mode": "db_to_sharepoint_push",
        "totals": {"inserted": inserted, "updated": updated, "failed": failed},
        "details": details[:30],
    }


def _sync_pull_from_sharepoint() -> dict:
    """Applica al DB locale le modifiche della lista SharePoint dall'ultimo giro."""
    from ..models import AssenzaSharePointOutbox as Outbox

    if not _helpers._table_exists("assenze"):
        return {"ok": False, "error": "Tabella assenze non disponibile"}
    if not _helpers._graph_configured():
        return {"ok": False, "error": "SharePoint non configurato"}

    delta_link = cache.get(_SP_DELTA_LINK_KEY) or None
    items, new_link = _helpers._graph_delta_changes(delta_link)

    # Lo stesso elemento puo' comparire piu' volte nel feed: vale l'ultima occorrenza.
    latest: dict[str, dict] = {}
    for item in items:
        sp_id = str(item.get("id") or "").strip()
        if sp_id:
            latest[sp_id] = item

    pending_ids = set(Outbox.objects.values_list("assenza_id", flat=True))
    assenze_cols = _helpers.legacy_table_columns("assenze")
    has_dip = _helpers._table_exists("dipendenti")
    has_capi = _helpers._table_exists("capi_reparto")
    totals = {"inserted": 0, "updated": 0, "deleted": 0, "skipped_pending": 0, "discarded": 0, "failed": 0}

    # Le scritture di questo giro non devono far partire le automazioni del portale.
    _helpers._set_automation_queue_skip(True)
    try:
        for sp_id, item in latest.items():
            try:
                row_id = _helpers._find_assenza_id_by_sp_id(sp_id)
                if row_id is not None and row_id in pending_ids:
                    totals["skipped_pending"] += 1
                    continue
                if item.get("deleted"):
                    if row_id is not None and _helpers._delete_assenza(row_id):
                        totals["deleted"] += 1
                        _helpers.logger.info("[assenze:sp_pull] assenza %s eliminata: rimossa su SharePoint (item %s)", row_id, sp_id)
                    continue
                if not item.get("fields"):
                    item = _helpers._graph_get_item(sp_id)
                    if not item:
                        continue
                if row_id is None:
                    # Elemento SharePoint mai collegato: se il portale ha gia' la stessa
                    # richiesta lo si scarta, senza unirlo ne' duplicarlo.
                    _sp_id, payload = _helpers._sp_item_to_local(item)
                    duplicate_id = _helpers._find_duplicate_assenza_id(payload)
                    if duplicate_id is not None:
                        totals["discarded"] += 1
                        _helpers.logger.info(
                            "[assenze:sp_pull] item SharePoint %s scartato: richiesta gia' presente (assenza %s)",
                            sp_id, duplicate_id,
                        )
                        continue
                with transaction.atomic():
                    outcome = _helpers._apply_sp_item_to_local(
                        item, row_id, assenze_cols=assenze_cols, has_dip=has_dip, has_capi=has_capi
                    )
                if outcome in totals:
                    totals[outcome] += 1
            except Exception:
                totals["failed"] += 1
                _helpers.logger.exception("[assenze:sp_pull] item SharePoint %s non applicato", sp_id)
    finally:
        _helpers._set_automation_queue_skip(False)

    # Con errori il token non avanza: il giro dopo rilegge le stesse modifiche.
    if new_link and totals["failed"] == 0:
        cache.set(_SP_DELTA_LINK_KEY, new_link, timeout=None)

    return {
        "ok": totals["failed"] == 0,
        "mode": "sharepoint_to_db_delta",
        "full": not delta_link,
        "totals": totals,
    }


def _pull_interval_seconds() -> int:
    raw = getattr(settings, "ASSENZE_SP_PULL_INTERVAL_SECONDS", 300)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 300
    return max(60, value)


def _maybe_pull(force: bool = False) -> dict:
    if not _helpers._graph_configured():
        return {"ok": False, "skipped": True, "reason": "not_configured"}

    now_ts = int(time.time())
    last_ts = int(cache.get(_helpers._SYNC_PULL_LAST_TS_KEY) or 0)
    interval = _pull_interval_seconds()
    if not force and last_ts and (now_ts - last_ts) < interval:
        return {"ok": True, "skipped": True, "reason": "throttled", "next_in": interval - (now_ts - last_ts)}

    if not cache.add(_SYNC_PULL_LOCK_KEY, "1", timeout=_SYNC_PULL_LOCK_TTL):
        return {"ok": True, "skipped": True, "reason": "busy"}

    try:
        result = _sync_pull_from_sharepoint()
        if result.get("ok"):
            cache.set(_helpers._SYNC_PULL_LAST_TS_KEY, now_ts, timeout=None)
        return result
    except Exception as exc:
        _helpers.logger.exception("_maybe_pull: errore durante sync pull da SharePoint")
        return {"ok": False, "error": str(exc), "mode": "sharepoint_to_db_delta"}
    finally:
        cache.delete(_SYNC_PULL_LOCK_KEY)


@login_required
@require_http_methods(["GET", "POST"])
def api_sync_push(request):
    if not _helpers._assenze_permissions(request).get("can_update_any"):
        return _helpers._json_error("Permessi insufficienti: sync push consentito solo ad AMMINISTRAZIONE.", status=403)
    payload = _helpers._request_json(request)
    limit_raw = payload.get("limit_rows") if payload else request.GET.get("limit_rows", request.POST.get("limit_rows", 30))
    include_updates_raw = payload.get("include_updates") if payload else request.GET.get("include_updates", request.POST.get("include_updates", "0"))
    try:
        limit_rows = int(limit_raw or 30)
    except (TypeError, ValueError):
        limit_rows = 30
    include_updates = _helpers._as_bool(include_updates_raw)

    result = _sync_push(limit_rows=limit_rows, include_updates=include_updates)
    return JsonResponse(result, status=200 if result.get("ok") else 500)


@login_required
@require_http_methods(["GET", "POST"])
def api_sync_pull(request):
    if not _helpers._assenze_permissions(request).get("can_view_calendar"):
        return _helpers._json_error("Permessi insufficienti: sync pull non consentito per il tuo gruppo.", status=403)
    payload = _helpers._request_json(request)
    force_raw = payload.get("force") if payload else request.GET.get("force", request.POST.get("force", "0"))
    result = _maybe_pull(force=_helpers._as_bool(force_raw))
    return JsonResponse(result, status=200 if result.get("ok", True) else 500)
