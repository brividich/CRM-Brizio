"""Sposta i documenti fornitori dallo storage pubblico (/media) a quello privato.

Contesto SEC: storicamente `FornitoreDocumento.file` era salvato sotto MEDIA_ROOT
(servito da IIS senza autenticazione). Ora il campo usa lo storage privato cifrato
(`PrivateAnagraficaStorage`); questo comando riloca i file già caricati nella nuova
posizione privata (cifrandoli at-rest) e, opzionalmente, rimuove l'originale pubblico.

Idempotente. Default in dry-run: usare --apply per eseguire.

    python manage.py migrate_documenti_privati            # anteprima
    python manage.py migrate_documenti_privati --apply    # sposta nel privato
    python manage.py migrate_documenti_privati --apply --delete-old  # + rimuove i pubblici
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Riloca i documenti fornitori da MEDIA pubblico allo storage privato cifrato."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Esegue lo spostamento (default: solo anteprima).")
        parser.add_argument("--delete-old", action="store_true",
                            help="Elimina il file pubblico originale dopo lo spostamento.")

    def handle(self, *args, **opts):
        from anagrafica.models import FornitoreDocumento

        apply = bool(opts["apply"])
        delete_old = bool(opts["delete_old"])
        media_root = Path(settings.MEDIA_ROOT)
        moved = skipped = missing = 0

        for doc in FornitoreDocumento.objects.all().iterator():
            name = doc.file.name if doc.file else ""
            if not name:
                continue
            storage = doc.file.storage
            if storage.exists(name):
                skipped += 1
                continue  # già presente nello storage privato
            old_path = media_root / name
            if not old_path.exists():
                missing += 1
                self.stderr.write(f"  MANCANTE: doc {doc.id} ({name})")
                continue
            if apply:
                data = old_path.read_bytes()
                storage._save(name, ContentFile(data))  # cifra e scrive nel privato
                if delete_old:
                    try:
                        old_path.unlink()
                    except OSError:
                        pass
            moved += 1
            self.stdout.write(f"  {'SPOSTATO' if apply else 'DA SPOSTARE'}: doc {doc.id} ({name})")

        suffix = "" if apply else "  (dry-run: usa --apply per eseguire)"
        self.stdout.write(self.style.SUCCESS(
            f"Documenti fornitori — spostati/da spostare: {moved}, gia' privati: {skipped}, "
            f"originali mancanti: {missing}.{suffix}"
        ))
