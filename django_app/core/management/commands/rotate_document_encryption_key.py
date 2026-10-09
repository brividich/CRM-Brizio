"""Ri-cifra i file privati con la chiave corrente (audit M12).

Procedura:
    1. nel .env: DOCUMENT_ENCRYPTION_OLD_KEYS=<chiave attuale>,
       DOCUMENT_ENCRYPTION_KEY=<chiave nuova>; riavvio
    2. python manage.py rotate_document_encryption_key            # dry-run
    3. python manage.py rotate_document_encryption_key --apply
    4. tolta la vecchia chiave da DOCUMENT_ENCRYPTION_OLD_KEYS; riavvio

I file non cifrati vengono solo contati (per cifrarli: encrypt_existing_documents).
"""
from __future__ import annotations

from pathlib import Path

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from anagrafica.management.commands.encrypt_existing_documents import _STORAGE_ROOTS
from core.encrypted_storage import rotate_bytes


class Command(BaseCommand):
    help = "Ri-cifra i documenti privati con DOCUMENT_ENCRYPTION_KEY (rotazione chiave)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", default=False, help="Scrive i file ri-cifrati.")

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        if not str(getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "") or "").strip():
            raise CommandError("DOCUMENT_ENCRYPTION_KEY non configurata.")
        if not getattr(settings, "DOCUMENT_ENCRYPTION_OLD_KEYS", None):
            self.stdout.write(self.style.WARNING(
                "DOCUMENT_ENCRYPTION_OLD_KEYS vuota: i file sono gia' tutti sulla chiave corrente "
                "oppure manca la vecchia chiave per leggerli."
            ))
        mode = "[apply]" if apply else "[dry-run]"
        rotated = plain = errors = 0
        seen: set[str] = set()
        for storage_name, settings_key in _STORAGE_ROOTS.items():
            root = Path(str(getattr(settings, settings_key, "") or ""))
            if not root.exists():
                continue
            root_id = str(root.resolve()).lower()
            if root_id in seen:
                continue
            seen.add(root_id)
            self.stdout.write(f"{mode} [{storage_name}] {root}")
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    data = path.read_bytes()
                    new_data = rotate_bytes(data)
                    if new_data is None:
                        plain += 1
                        continue
                    if apply:
                        tmp = path.with_name(path.name + ".rotating")
                        tmp.write_bytes(new_data)
                        tmp.replace(path)
                    rotated += 1
                except (OSError, ValueError, InvalidToken) as exc:
                    errors += 1
                    self.stderr.write(self.style.ERROR(f"  [ERRORE] {path}: {exc}"))
        verb = "ri-cifrati" if apply else "da ri-cifrare"
        self.stdout.write(self.style.SUCCESS(
            f"{mode} {verb}: {rotated}, non cifrati: {plain}, errori: {errors}"
        ))
        if errors:
            raise CommandError("Alcuni file non sono stati ri-cifrati: NON togliere la vecchia chiave.")
