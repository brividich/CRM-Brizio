"""Centrale di comando → «Backup e ripristino» (BUILD_SPEC R2 §4.2).

Solo amministratori di portale (stessa regola della Centrale di comando). Nessun
pulsante di ripristino: la pagina mostra lo stato, accoda verifiche e scarica il piano
di ripristino; il ripristino si fa con il tool dedicato.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from admin_portale.decorators import legacy_admin_or_acl_required
from core.audit import log_action

from .models import BackupRun, RestoreDrill

_SET_RE = re.compile(r"^\d{8}_\d{6}_(full|log|files|host)$")
_LEVEL_CSS = {"ok": "ok", "info": "skip", "warning": "warn", "critical": "fail",
              "warn": "warn", "fail": "fail", "skipped": "skip"}


def _config():
    from core.backup_engine.config import load_config

    try:
        return load_config(), ""
    except ValueError as exc:
        return None, str(exc)


@legacy_admin_or_acl_required("monitoring", "backup_status")
def backup_status(request):
    from core import db_diagnostics
    from core.backup_engine import status
    from core.backup_engine.restore_plan import latest_restore_point

    from .health import run_backup_checks

    cfg, cfg_error = _config()
    now = timezone.now()
    tiles = {}
    checks = run_backup_checks()
    by_name = {c.name: c for c in checks}
    if cfg:
        point = latest_restore_point(cfg.env_root)
        if point:
            aware = timezone.make_aware(point) if timezone.is_naive(point) else point
            minutes = int((now - aware).total_seconds() / 60)
            tiles["rpo"] = {"value": f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min",
                            "note": f"punto ripristinabile più recente: {timezone.localtime(aware):%d/%m/%Y %H:%M}",
                            "css": "ok" if minutes <= 90 else "warn" if minutes <= 26 * 60 else "fail"}
        else:
            tiles["rpo"] = {"value": "—", "note": "nessun punto ripristinabile nel target", "css": "fail"}
        last = status.read(cfg).get("last", {})
        tiles["status_last"] = last
        when = (last.get("full") or {}).get("last_ok_at")
        if when:
            try:
                dt = datetime.fromisoformat(when)
                tiles["full_when"] = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
            except ValueError:
                pass
    capacity = db_diagnostics.server_capacity()
    last_drill = RestoreDrill.objects.order_by("-started_at").first()

    qs = BackupRun.objects.all()
    kind = request.GET.get("kind", "")
    state = request.GET.get("status", "")
    days = request.GET.get("days", "30")
    if kind in BackupRun.Kind.values:
        qs = qs.filter(kind=kind)
    if state in BackupRun.Status.values:
        qs = qs.filter(status=state)
    if days.isdigit():
        qs = qs.filter(started_at__gte=now - timedelta(days=int(days)))
    page = Paginator(qs.order_by("-started_at", "-id"), 50).get_page(request.GET.get("page"))

    return render(request, "monitoring/pages/backup.html", {
        "cfg": cfg,
        "cfg_error": cfg_error,
        "checks": [{"name": c.name, "status": c.status, "css": _LEVEL_CSS.get(c.status, "skip"), "message": c.message}
                   for c in checks],
        "by_name": by_name,
        "tiles": tiles,
        "capacity": capacity,
        "last_drill": last_drill,
        "drills": RestoreDrill.objects.order_by("-started_at")[:10],
        "page": page,
        "kinds": BackupRun.Kind.choices,
        "statuses": BackupRun.Status.choices,
        "filters": {"kind": kind, "status": state, "days": days},
        "now": now,
    })


@legacy_admin_or_acl_required("monitoring", "backup_set_detail")
def backup_set_detail(request, set_id: str):
    from core.backup_engine import manifest as mf

    if not _SET_RE.match(set_id):
        raise Http404("Set non valido")
    cfg, cfg_error = _config()
    data, error = None, cfg_error
    if cfg:
        set_dir = cfg.env_root / set_id
        try:
            data = mf.load(set_dir)
        except mf.ManifestError as exc:
            error = f"Manifest non leggibile: {exc}"
    run = BackupRun.objects.filter(set_id=set_id).order_by("-started_at").first()
    env_names = (data or {}).get("keys", {}).get("env_var_names", []) if data else []
    return render(request, "monitoring/pages/backup_set.html", {
        "set_id": set_id, "data": data, "error": error, "run": run, "env_names_count": len(env_names),
        "manifest_json": json.dumps({k: v for k, v in (data or {}).items() if k != "keys"}, ensure_ascii=False,
                                    indent=2, default=str) if data else "",
    })


@legacy_admin_or_acl_required("monitoring", "backup_verify")
@require_POST
def backup_verify(request):
    set_id = (request.POST.get("set_id") or "").strip()
    if set_id and not _SET_RE.match(set_id):
        messages.error(request, "Set non valido.")
        return redirect("monitoring_admin:backup_status")
    try:
        from django_q.tasks import async_task

        async_task("core.backup_engine.tasks.verify_task", set_id or None)
        log_action(request, "backup_verify_queued", "monitoring", {"set_id": set_id or "latest"})
        messages.success(request, "Verifica accodata: l'esito compare nella tabella al termine (tipo «Verifica»).")
    except Exception as exc:
        messages.error(request, f"Verifica non accodata (cluster django-q attivo?): {exc}")
    return redirect("monitoring_admin:backup_status")


@legacy_admin_or_acl_required("monitoring", "backup_restore_plan")
def backup_restore_plan(request):
    from core.backup_engine.restore_plan import PlanError, build_plan

    cfg, cfg_error = _config()
    if not cfg:
        messages.error(request, cfg_error)
        return redirect("monitoring_admin:backup_status")
    when = None
    raw = (request.GET.get("t") or "").strip()
    if raw:
        try:
            when = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            messages.error(request, "Data e ora non valide.")
            return redirect("monitoring_admin:backup_status")
    try:
        plan = build_plan(cfg.env_root, when)
    except PlanError as exc:
        messages.error(request, f"Piano non costruibile: {exc}")
        return redirect("monitoring_admin:backup_status")
    log_action(request, "backup_restore_plan_download", "monitoring", {"t": raw or "latest",
                                                                       "full_set_id": plan["full_set_id"]})
    resp = HttpResponse(json.dumps(plan, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M")
    resp["Content-Disposition"] = f'attachment; filename="restore-plan-{cfg.env}-{stamp}.json"'
    return resp
