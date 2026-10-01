"""Command center del portale per il Server Dashboard del Setup Wizard.

Il Server Dashboard gira *fuori* dal portale (Tkinter sul server): per mostrare
lo stato interno — schedule, qcluster, coda, errori, migrazioni, readyz — lancia
questo comando con il virtualenv dell'ambiente e legge il JSON che stampa.

Sottocomandi:
    status               stato complessivo in JSON (una riga, dopo il marcatore)
    run <schedule>       esegue SUBITO la funzione di uno schedule, nel processo
                         corrente (funziona anche a qcluster fermo)
    post-deploy          registra gli schedule e verifica la release appena
                         attivata; exit code 1 se qualcosa di bloccante non va

Ogni sezione di ``status`` è isolata: un errore in una non svuota le altre.
"""
from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timedelta
from importlib import import_module

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

JSON_MARKER = "@@COMMAND_CENTER_JSON@@"


def _iso(value):
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.isoformat(timespec="seconds")
    return value


def _section(func):
    started = time.monotonic()
    try:
        data = func()
    except Exception as exc:  # una sezione rotta non deve oscurare le altre
        data = {"error": f"{exc.__class__.__name__}: {exc}"}
    if isinstance(data, dict):
        data.setdefault("ms", int((time.monotonic() - started) * 1000))
    return data


def _short(text, limit=300):
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ── Sezioni ───────────────────────────────────────────────────────────────────


def section_build() -> dict:
    from django.conf import settings

    from core.build_info import read_build_info

    info = read_build_info() or {}
    return {
        "version": getattr(settings, "APP_VERSION", "") or info.get("version", ""),
        "commit": info.get("commit_short") or (info.get("commit") or "")[:8],
        "branch": info.get("branch") or "",
        "packaged_at": info.get("built_at") or "",
        "has_drift": bool(info.get("has_drift")),
        "packaged": bool(info),
        "settings": getattr(settings, "SETTINGS_MODULE", ""),
        "debug": bool(settings.DEBUG),
    }


def section_migrations() -> dict:
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connections["default"])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    pending = [f"{m.app_label}.{m.name}" for m, _backwards in plan]
    return {"pending": pending, "count": len(pending)}


def section_qcluster() -> dict:
    from django_q.models import Failure, OrmQ, Success

    now = timezone.now()
    since = now - timedelta(hours=24)
    last_ok = Success.objects.order_by("-stopped").values("name", "func", "stopped").first()
    clusters = []
    try:
        from django_q.status import Stat

        for stat in Stat.get_all():
            clusters.append({
                "host": getattr(stat, "host", ""),
                "status": getattr(stat, "status", ""),
                "workers": len(getattr(stat, "workers", []) or []),
                "uptime_s": int(stat.uptime()) if hasattr(stat, "uptime") else None,
            })
    except Exception:
        clusters = []
    last_age = int((now - last_ok["stopped"]).total_seconds()) if last_ok else None
    return {
        "clusters": clusters,
        "queue": OrmQ.objects.count(),
        "ok_24h": Success.objects.filter(stopped__gte=since).count(),
        "failed_24h": Failure.objects.filter(stopped__gte=since).count(),
        "last_ok": {
            "func": last_ok["func"],
            "at": _iso(last_ok["stopped"]),
            "age_s": last_age,
        } if last_ok else None,
    }


def section_failures(limit: int = 15) -> dict:
    from django_q.models import Failure

    rows = [
        {
            "at": _iso(f["stopped"]),
            "name": f["name"],
            "func": f["func"],
            "result": _short(f["result"], 400),
        }
        for f in Failure.objects.order_by("-stopped").values("stopped", "name", "func", "result")[:limit]
    ]
    return {"rows": rows}


def section_schedules() -> dict:
    from automazioni.schedules import schedule_rows

    rows = []
    for row in schedule_rows():
        rows.append({
            "name": row["name"],
            "func": row["func"],
            "module": row["module"],
            "cadence": row["cadence"],
            "description": _short(row.get("description"), 400),
            "enabled": bool(row["enabled"]),
            "registered": bool(row["registered"]),
            "next_run": _iso(row["next_run"]),
            "last_run": _iso(row["last_run"]),
            "last_ok": row["last_ok"],
        })
    return {
        "rows": rows,
        "total": len(rows),
        "not_registered": sum(1 for r in rows if r["enabled"] and not r["registered"]),
        "last_failed": sum(1 for r in rows if r["last_ok"] is False),
    }


def section_automations() -> dict:
    from django.db.models import Count

    from monitoring.models import AutomationExecution, Issue
    from monitoring.services import OPEN_ISSUE_STATUSES, detect_missed_jobs

    since = timezone.now() - timedelta(hours=24)
    severity = {
        r["severity"]: r["total"]
        for r in Issue.objects.filter(status__in=OPEN_ISSUE_STATUSES)
        .values("severity").annotate(total=Count("id")).order_by()
    }
    missed = detect_missed_jobs(create_issues=False)
    return {
        "open_issues": sum(severity.values()),
        "issues_by_severity": severity,
        "executions_failed_24h": AutomationExecution.objects.filter(
            status=AutomationExecution.Status.FAILED, started_at__gte=since
        ).count(),
        "missed_jobs": [
            f"{getattr(m['job'], 'name', m['job'])} (in ritardo di {m['overdue_minutes']} min)"
            for m in missed
        ][:20],
    }


def section_readyz() -> dict:
    from dataclasses import asdict

    from monitoring.health import run_readyz_checks

    report = run_readyz_checks()
    return {
        "status": report.status,
        "checks": [
            {k: v for k, v in asdict(c).items() if k in ("name", "status", "latency_ms", "critical", "message")}
            for c in report.checks
        ],
    }


SECTIONS = {
    "build": section_build,
    "migrations": section_migrations,
    "qcluster": section_qcluster,
    "schedules": section_schedules,
    "failures": section_failures,
    "automations": section_automations,
    "readyz": section_readyz,
}


def collect_status(skip: set[str] | None = None) -> dict:
    skip = skip or set()
    payload = {"generated_at": _iso(timezone.now())}
    for name, func in SECTIONS.items():
        if name not in skip:
            payload[name] = _section(func)
    return payload


def run_schedule(name: str):
    """Esegue la funzione di uno schedule nel processo corrente. Ritorna il risultato."""
    from automazioni.schedules import spec_by_name

    spec = spec_by_name(name)
    if not spec:
        raise CommandError(f"Schedule sconosciuto: {name}")
    module_path, func_name = spec["func"].rsplit(".", 1)
    func = getattr(import_module(module_path), func_name)
    return func(**(spec.get("kwargs") or {}))


class Command(BaseCommand):
    help = "Command center per il Server Dashboard: stato JSON, esecuzione schedule, verifica post-deploy."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "run", "post-deploy"])
        parser.add_argument("name", nargs="?", default="", help="run: nome dello schedule")
        parser.add_argument("--skip", default="", help="status: sezioni da saltare, separate da virgola")
        parser.add_argument("--pretty", action="store_true", help="status: JSON indentato, senza marcatore")

    def handle(self, *args, **options):
        action = options["action"]
        if action == "status":
            skip = {s.strip() for s in (options.get("skip") or "").split(",") if s.strip()}
            payload = collect_status(skip)
            if options.get("pretty"):
                self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            else:
                self.stdout.write(JSON_MARKER + json.dumps(payload, ensure_ascii=False, default=str))
        elif action == "run":
            if not options.get("name"):
                raise CommandError("Indica il nome dello schedule: command_center run <nome>")
            self._run(options["name"])
        else:
            self._post_deploy()

    def _run(self, name: str):
        self.stdout.write(f"Esecuzione immediata dello schedule '{name}'…")
        started = time.monotonic()
        try:
            result = run_schedule(name)
        except CommandError:
            raise
        except Exception:
            self.stderr.write(traceback.format_exc())
            raise CommandError(f"'{name}' terminato con errore.")
        elapsed = time.monotonic() - started
        self.stdout.write(f"Risultato: {_short(json.dumps(result, ensure_ascii=False, default=str), 2000)}")
        if isinstance(result, dict) and result.get("ok") is False:
            raise CommandError(f"'{name}' ha riportato ok=False ({elapsed:.1f}s).")
        self.stdout.write(self.style.SUCCESS(f"'{name}' completato in {elapsed:.1f}s."))

    def _post_deploy(self):
        problemi: list[str] = []
        avvisi: list[str] = []

        self.stdout.write("[1/4] Registrazione schedule django-q (setup_q_schedules)")
        try:
            call_command("setup_q_schedules", stdout=self.stdout)
            self.stdout.write(self.style.SUCCESS("  OK schedule allineati al codice della release"))
        except Exception as exc:
            problemi.append(f"setup_q_schedules: {exc}")
            self.stdout.write(self.style.ERROR(f"  KO setup_q_schedules: {exc}"))

        self.stdout.write("[2/4] Django system check")
        try:
            call_command("check", stdout=self.stdout)
            self.stdout.write(self.style.SUCCESS("  OK check"))
        except Exception as exc:
            problemi.append(f"check: {exc}")
            self.stdout.write(self.style.ERROR(f"  KO check: {exc}"))

        self.stdout.write("[3/4] Migrazioni pendenti")
        mig = _section(section_migrations)
        if mig.get("error"):
            problemi.append(f"migrazioni: {mig['error']}")
            self.stdout.write(self.style.ERROR(f"  KO {mig['error']}"))
        elif mig["count"]:
            problemi.append(f"{mig['count']} migrazioni non applicate")
            self.stdout.write(self.style.ERROR(f"  KO {mig['count']} non applicate: {', '.join(mig['pending'][:10])}"))
        else:
            self.stdout.write(self.style.SUCCESS("  OK nessuna migrazione pendente"))

        self.stdout.write("[4/4] Readyz (DB, cache, Graph, LDAP, SMTP, coda)")
        ready = _section(section_readyz)
        if ready.get("error"):
            avvisi.append(f"readyz: {ready['error']}")
            self.stdout.write(self.style.WARNING(f"  ?? {ready['error']}"))
        else:
            for c in ready["checks"]:
                riga = f"  {c['status'].upper():<7} {c['name']} {c.get('message') or ''}".rstrip()
                if c["status"] == "fail" and c.get("critical"):
                    problemi.append(f"readyz {c['name']}")
                    self.stdout.write(self.style.ERROR(riga))
                elif c["status"] in ("fail", "warn"):
                    avvisi.append(f"readyz {c['name']}")
                    self.stdout.write(self.style.WARNING(riga))
                else:
                    self.stdout.write(riga)

        sched = _section(section_schedules)
        if not sched.get("error") and sched.get("not_registered"):
            avvisi.append(f"{sched['not_registered']} schedule abilitati ma non registrati")

        for avviso in avvisi:
            self.stdout.write(self.style.WARNING(f"  avviso: {avviso}"))
        if problemi:
            raise CommandError("Verifica post-deploy: " + "; ".join(problemi))
        self.stdout.write(self.style.SUCCESS(
            "Verifica post-deploy OK" + (f" con {len(avvisi)} avvisi" if avvisi else "")
        ))
