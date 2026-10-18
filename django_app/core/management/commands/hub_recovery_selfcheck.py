"""Verifica applicativa dopo un ripristino (BUILD_SPEC R3 §5.3 fase 10).

  manage.py hub_recovery_selfcheck [--json] [--samples 5]

Controlla, sulla macchina appena ricostruita:
- connessione al DB e nessuna migrazione da applicare;
- chiavi in uso uguali alle impronte del backup (se si passa ``--plan``);
- lettura di N file privati per radice tramite lo storage cifrato del portale
  (decifratura in memoria, come quando un utente apre un allegato);
- pagine protette servite dall'applicazione a un amministratore (home e «Backup e
  ripristino») con il client di test di Django, senza passare dalla rete.
Il login reale con un utente tecnico resta una verifica manuale del report.
Exit code: 0 = ok, 2 = almeno un controllo fallito.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Controlli applicativi dopo un ripristino (DB, migrazioni, chiavi, documenti cifrati, pagine)."

    def add_arguments(self, parser):
        parser.add_argument("--plan", default="")
        parser.add_argument("--samples", type=int, default=5)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **opts):
        checks: dict = {}
        checks["database"] = self._db()
        checks["migrations"] = self._migrations()
        if opts["plan"]:
            checks["keys"] = self._keys(Path(opts["plan"]))
        checks["private_files"] = self._private_files(opts["samples"])
        checks["pages"] = self._pages()
        failed = [k for k, v in checks.items() if v.get("status") == "failed"]
        payload = {"status": "failed" if failed else "ok", "checks": checks}
        if opts["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            for name, c in checks.items():
                style = self.style.SUCCESS if c["status"] == "ok" else (
                    self.style.WARNING if c["status"] == "warning" else self.style.ERROR)
                self.stdout.write(style(f"{name}: {c['status'].upper()} {c.get('message', '')}".rstrip()))
        if failed:
            sys.exit(2)

    def _db(self):
        from django.db import connection

        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            return {"status": "ok", "message": connection.settings_dict.get("NAME", "")}
        except Exception as exc:
            return {"status": "failed", "message": f"{exc.__class__.__name__}: {exc}"}

    def _migrations(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        try:
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception as exc:
            return {"status": "failed", "message": f"{exc.__class__.__name__}: {exc}"}
        if pending:
            return {"status": "warning", "message": f"{len(pending)} migrazioni da applicare: DB e codice non allineati",
                    "pending": [f"{m.app_label}.{m.name}" for m, _ in pending[:20]]}
        return {"status": "ok", "message": "nessuna migrazione da applicare"}

    def _keys(self, plan_path: Path):
        from core.backup_engine import manifest as mf
        from core.backup_engine.recovery_kit import compare_fingerprints

        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        diff = compare_fingerprints({"fingerprints": mf.keys_section()}, plan.get("expected_keys") or {})
        if diff:
            return {"status": "failed", "message": f"chiavi diverse dal backup: {', '.join(diff)}"}
        return {"status": "ok", "message": "chiavi uguali a quelle del backup"}

    def _private_files(self, samples: int):
        from core.backup_engine.files import private_roots
        from core.encrypted_storage import decrypt_bytes, is_encrypted

        rng = random.Random()
        out, status = {}, "ok"
        for label, root in private_roots().items():
            root = Path(root)
            files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
            picked = rng.sample(files, min(samples, len(files))) if files else []
            res = {"files": len(files), "checked": 0, "decrypted": 0, "errors": []}
            for p in picked:
                data = p.read_bytes()
                res["checked"] += 1
                if is_encrypted(data):
                    try:
                        decrypt_bytes(data)
                        res["decrypted"] += 1
                    except Exception as exc:
                        res["errors"].append(f"{p.name}: {exc.__class__.__name__}")
                        status = "failed"
            out[label] = res
        return {"status": status, "roots": out,
                "message": f"{sum(r['decrypted'] for r in out.values())} documenti cifrati aperti"}

    def _pages(self):
        from django.contrib.auth import get_user_model
        from django.test import Client
        from django.urls import reverse

        admin = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by("id").first()
        if admin is None:
            return {"status": "warning", "message": "nessun superuser attivo per la prova delle pagine"}
        host = (getattr(settings, "HUB_PUBLIC_HOSTNAME", "") or (settings.ALLOWED_HOSTS or ["localhost"])[0]).lstrip(".")
        client = Client(HTTP_HOST=host if host != "*" else "localhost")
        client.force_login(admin)
        results = {}
        for name in ("monitoring_admin:backup_status", "monitoring_admin:system_status"):
            try:
                results[name] = client.get(reverse(name), secure=True).status_code
            except Exception as exc:
                results[name] = f"{exc.__class__.__name__}"
        ok = all(code == 200 for code in results.values())
        return {"status": "ok" if ok else "failed", "pages": results,
                "message": "pagine protette servite" if ok else "pagine non servite correttamente"}
