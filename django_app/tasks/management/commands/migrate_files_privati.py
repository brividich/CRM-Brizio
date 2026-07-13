"""Sposta allegati Task e documenti VRF dallo storage pubblico (/media) al privato.

Contesto SEC: `TaskAttachment.file` e `Project.vrf_file` erano su MEDIA_ROOT (serviti
da IIS senza autenticazione, con nomi VRF prevedibili). Ora usano lo storage privato
cifrato (`PrivateTasksStorage`); questo comando riloca i file già caricati nella nuova
posizione privata (cifrandoli at-rest) e, opzionalmente, rimuove l'originale pubblico.

Idempotente. Default in dry-run: usare --apply per eseguire.

    python manage.py migrate_files_privati
    python manage.py migrate_files_privati --apply
    python manage.py migrate_files_privati --apply --delete-old
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Riloca allegati Task e documenti VRF da MEDIA pubblico allo storage privato cifrato."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Esegue lo spostamento (default: solo anteprima).")
        parser.add_argument("--delete-old", action="store_true",
                            help="Elimina il file pubblico originale dopo lo spostamento.")

    def _migrate_field(self, queryset, field_name, *, apply, delete_old):
        media_root = Path(settings.MEDIA_ROOT)
        moved = skipped = missing = 0
        for obj in queryset.iterator():
            f = getattr(obj, field_name, None)
            name = f.name if f else ""
            if not name:
                continue
            storage = f.storage
            if storage.exists(name):
                skipped += 1
                continue
            old_path = media_root / name
            if not old_path.exists():
                missing += 1
                self.stderr.write(f"  MANCANTE: {field_name} {obj.pk} ({name})")
                continue
            if apply:
                storage._save(name, ContentFile(old_path.read_bytes()))
                if delete_old:
                    try:
                        old_path.unlink()
                    except OSError:
                        pass
            moved += 1
            self.stdout.write(f"  {'SPOSTATO' if apply else 'DA SPOSTARE'}: {field_name} {obj.pk} ({name})")
        return moved, skipped, missing

    def handle(self, *args, **opts):
        from tasks.models import Project, TaskAttachment

        apply = bool(opts["apply"])
        delete_old = bool(opts["delete_old"])

        a_moved, a_skip, a_miss = self._migrate_field(
            TaskAttachment.objects.all(), "file", apply=apply, delete_old=delete_old)
        v_moved, v_skip, v_miss = self._migrate_field(
            Project.objects.exclude(vrf_file=""), "vrf_file", apply=apply, delete_old=delete_old)

        suffix = "" if apply else "  (dry-run: usa --apply per eseguire)"
        self.stdout.write(self.style.SUCCESS(
            f"Allegati Task — spostati/da spostare: {a_moved}, gia' privati: {a_skip}, mancanti: {a_miss}. "
            f"VRF — spostati/da spostare: {v_moved}, gia' privati: {v_skip}, mancanti: {v_miss}.{suffix}"
        ))
