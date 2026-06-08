"""
Management command per cifrare i file privati esistenti su disco.

Eseguire UNA SOLA VOLTA dopo aver impostato DOCUMENT_ENCRYPTION_KEY in prod.
I file già cifrati (magic prefix NCENC1) vengono saltati automaticamente.

Utilizzo:
    # Anteprima (dry-run, default):
    python manage.py encrypt_existing_documents

    # Applica cifratura:
    python manage.py encrypt_existing_documents --apply

    # Solo storage specifico:
    python manage.py encrypt_existing_documents --apply --storage anagrafica
"""
from __future__ import annotations

import os
from pathlib import Path

from django.core.management.base import BaseCommand

from core.encrypted_storage import _MAGIC, encrypt_bytes, is_encrypted


_STORAGE_ROOTS = {
    "anagrafica": "ANAGRAFICA_PRIVATE_ROOT",
    "timbri": "TIMBRI_PRIVATE_ROOT",
    "tickets": "TICKETS_PRIVATE_ROOT",
    "diario_preposto": "DIARIO_PREPOSTO_PRIVATE_ROOT",
    "assets": "ASSETS_PRIVATE_ROOT",
}


class Command(BaseCommand):
    help = "Cifra at rest i file privati esistenti (da eseguire una tantum dopo attivazione chiave)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Applica la cifratura. Senza questo flag esegue solo dry-run.",
        )
        parser.add_argument(
            "--storage",
            choices=list(_STORAGE_ROOTS.keys()),
            default=None,
            help="Limita a un singolo storage. Default: tutti.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        apply = options["apply"]
        storage_filter = options["storage"]

        key = str(getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "") or "").strip()
        if not key:
            self.stderr.write(self.style.ERROR(
                "DOCUMENT_ENCRYPTION_KEY non configurata. Impossibile cifrare."
            ))
            return

        if not apply:
            self.stdout.write(self.style.WARNING(
                "DRY-RUN attivo. Usa --apply per applicare le modifiche."
            ))

        targets = (
            {storage_filter: _STORAGE_ROOTS[storage_filter]}
            if storage_filter
            else _STORAGE_ROOTS
        )

        total_scanned = 0
        total_encrypted = 0
        total_skipped = 0
        total_errors = 0

        for storage_name, settings_key in targets.items():
            root = Path(str(getattr(settings, settings_key, "")))
            if not root.exists():
                self.stdout.write(f"  {storage_name}: cartella non trovata ({root}), salto.")
                continue

            self.stdout.write(f"\n[{storage_name}] root={root}")
            for filepath in root.rglob("*"):
                if not filepath.is_file():
                    continue
                total_scanned += 1
                try:
                    data = filepath.read_bytes()
                    if is_encrypted(data):
                        total_skipped += 1
                        continue
                    encrypted = encrypt_bytes(data)
                    if apply:
                        filepath.write_bytes(encrypted)
                    total_encrypted += 1
                    self.stdout.write(f"  {'[CIFRATO]' if apply else '[DA CIFRARE]'} {filepath.name}")
                except Exception as exc:
                    total_errors += 1
                    self.stderr.write(self.style.ERROR(f"  [ERRORE] {filepath}: {exc}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Completato — scansionati: {total_scanned}, "
            f"{'cifrati' if apply else 'da cifrare'}: {total_encrypted}, "
            f"già cifrati: {total_skipped}, errori: {total_errors}"
        ))
        if not apply and total_encrypted > 0:
            self.stdout.write(self.style.WARNING(
                "Riesegui con --apply per applicare la cifratura."
            ))
