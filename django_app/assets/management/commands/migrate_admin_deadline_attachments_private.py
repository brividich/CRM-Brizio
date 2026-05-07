from __future__ import annotations

import shutil
from filecmp import cmp
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from assets.models import AssetAdministrativeDeadlineCompletionAttachment


class Command(BaseCommand):
    help = "Migra gli allegati scadenze amministrative asset da MEDIA_ROOT ad ASSETS_PRIVATE_ROOT."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Esegue la copia dei file.")
        parser.add_argument(
            "--delete-source",
            action="store_true",
            help="Dopo una copia riuscita elimina il file legacy da MEDIA_ROOT.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        delete_source = bool(options["delete_source"])
        media_root = Path(settings.MEDIA_ROOT).resolve()
        private_root = Path(settings.ASSETS_PRIVATE_ROOT).resolve()
        copied = skipped = missing = deleted = updated = collisions = 0

        for attachment in AssetAdministrativeDeadlineCompletionAttachment.objects.only("id", "file"):
            raw_name = str(attachment.file.name or "").strip()
            name = raw_name.replace("\\", "/").lstrip("/")
            if not name:
                skipped += 1
                continue
            try:
                source = (media_root / name).resolve()
                target = (private_root / name).resolve()
            except OSError:
                missing += 1
                self.stdout.write(self.style.WARNING(f"#{attachment.id}: path non valido"))
                continue
            if not source.is_relative_to(media_root) or not target.is_relative_to(private_root):
                skipped += 1
                self.stdout.write(self.style.WARNING(f"#{attachment.id}: path fuori root consentite"))
                continue
            if target.exists():
                if source.exists() and not cmp(source, target, shallow=False):
                    collisions += 1
                    self.stdout.write(
                        self.style.WARNING(f"#{attachment.id}: collisione target con contenuto diverso, nessuna modifica")
                    )
                    continue
                skipped += 1
                if delete_source and source.exists() and apply_changes:
                    source.unlink()
                    deleted += 1
                if apply_changes and raw_name != name:
                    attachment.file.name = name
                    attachment.save(update_fields=["file"])
                    updated += 1
                continue
            if not source.exists():
                missing += 1
                self.stdout.write(self.style.WARNING(f"#{attachment.id}: sorgente mancante {name}"))
                continue
            if apply_changes:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if raw_name != name:
                    attachment.file.name = name
                    attachment.save(update_fields=["file"])
                    updated += 1
                if delete_source:
                    source.unlink()
                    deleted += 1
            copied += 1

        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: copied={copied} skipped={skipped} missing={missing} "
                f"deleted={deleted} updated={updated} collisions={collisions}"
            )
        )
