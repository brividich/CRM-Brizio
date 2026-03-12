from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from anomalie.views import _anomalie_attachments_root, _fetch_all_dict, _has_table


class Command(BaseCommand):
    help = "Pulizia cartelle allegati anomalie orfane (local_id non più presente in tabella anomalie)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Elimina realmente le cartelle orfane trovate (default: solo report).",
        )
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=0,
            help="Considera solo cartelle più vecchie di N giorni (0 = nessun filtro età).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Massimo numero di cartelle da processare (0 = nessun limite).",
        )

    def handle(self, *args, **options):
        if not _has_table("anomalie"):
            raise CommandError("Tabella anomalie non disponibile.")

        root = _anomalie_attachments_root()
        if not root.exists():
            self.stdout.write(self.style.WARNING(f"Cartella allegati non trovata: {root}"))
            return
        if not root.is_dir():
            raise CommandError(f"Percorso allegati non valido (non directory): {root}")

        rows = _fetch_all_dict("SELECT id FROM anomalie")
        local_ids = {int(r["id"]) for r in rows if r.get("id") is not None}

        older_days = max(0, int(options.get("older_than_days") or 0))
        limit = max(0, int(options.get("limit") or 0))
        cutoff = None
        if older_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=older_days)

        orphan_dirs: list[Path] = []
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            if not child.name.isdigit():
                continue
            local_id = int(child.name)
            if local_id in local_ids:
                continue
            if cutoff is not None:
                modified = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
                if modified > cutoff:
                    continue
            orphan_dirs.append(child)
            if limit and len(orphan_dirs) >= limit:
                break

        if not orphan_dirs:
            self.stdout.write(self.style.SUCCESS("Nessuna cartella orfana trovata."))
            return

        self.stdout.write(self.style.WARNING(f"Trovate {len(orphan_dirs)} cartelle orfane."))
        for path in orphan_dirs:
            self.stdout.write(f"- {path}")

        if not options.get("delete"):
            self.stdout.write(self.style.WARNING("Dry-run: nessuna cartella eliminata (usa --delete)."))
            return

        deleted = 0
        failed = 0
        for path in orphan_dirs:
            try:
                shutil.rmtree(path)
                deleted += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(f"Errore eliminazione {path}: {exc}")

        if failed:
            raise CommandError(f"Cleanup completato con errori: eliminate={deleted}, fallite={failed}")
        self.stdout.write(self.style.SUCCESS(f"Cleanup completato: eliminate {deleted} cartelle orfane."))
