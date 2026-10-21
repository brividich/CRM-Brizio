"""Sposta in storage privato cifrato i file storici rimasti in MEDIA_ROOT.

Molti FileField sono passati a uno storage privato (``EncryptedStorageMixin``),
ma i file caricati prima del passaggio sono rimasti in ``MEDIA_ROOT``, cioe' in
una cartella che IIS serve senza autenticazione. Il web.config li blocca per
cartella; questo command li toglie proprio dalla webroot: per ogni record che
punta a un file presente in MEDIA_ROOT e assente nello storage privato, copia
il file cifrato nello storage privato (stesso nome, quindi nessuna modifica al
database), verifica che si decifri identico e cancella l'originale.

Anteprima di default; ``--apply`` per spostare. Con ``--orfani`` elenca anche i
file nelle cartelle protette che nessun record referenzia (non li cancella).

Uso:
    python manage.py media_privatizza
    python manage.py media_privatizza --apply
    python manage.py media_privatizza --apply --app timbri
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from core.encrypted_storage import EncryptedStorageMixin, decrypt_bytes, encrypt_bytes, is_encrypted

# Cartelle di MEDIA_ROOT bloccate in IIS perche' contengono dati personali storici.
CARTELLE_PROTETTE = (
    "anagrafica",
    "firme",
    "fotocard",
    "timbri",
    "tasks_vrf",
    "tasks_attachments",
    "attrezzature_import_preview",
)


def _campi_privati(solo_app: str | None):
    for model in apps.get_models():
        if solo_app and model._meta.app_label != solo_app:
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, models.FileField):
                continue
            storage = field.storage
            if isinstance(storage, EncryptedStorageMixin) and isinstance(storage, FileSystemStorage):
                yield model, field, storage


class Command(BaseCommand):
    help = "Sposta in storage privato cifrato i file storici rimasti nella webroot (MEDIA_ROOT)"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Sposta davvero. Senza: solo anteprima.")
        parser.add_argument("--app", default=None, help="Limita a un'app (es. timbri, anagrafica).")
        parser.add_argument("--orfani", action="store_true",
                            help="Elenca i file nelle cartelle protette non referenziati da nessun record.")

    def handle(self, *args, **options):
        apply = options["apply"]
        media_root = Path(settings.MEDIA_ROOT).resolve()
        if apply and not str(getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "") or "").strip():
            raise CommandError("DOCUMENT_ENCRYPTION_KEY non configurata: i file finirebbero in chiaro.")

        da_spostare, spostati, errori = 0, 0, 0
        referenziati: set[Path] = set()
        for model, field, storage in _campi_privati(options["app"]):
            privata = Path(storage.location).resolve()
            if privata == media_root:
                continue
            nomi = (
                model._default_manager.exclude(**{field.name: ""})
                .exclude(**{f"{field.name}__isnull": True})
                .values_list(field.name, flat=True)
                .distinct()
            )
            for nome in nomi.iterator():
                legacy = (media_root / nome).resolve()
                if not legacy.is_relative_to(media_root):
                    continue
                referenziati.add(legacy)
                destinazione = (privata / nome).resolve()
                if not legacy.is_file() or destinazione.exists() or not destinazione.is_relative_to(privata):
                    continue
                da_spostare += 1
                etichetta = f"{model._meta.label}.{field.name}"
                if not apply:
                    self.stdout.write(f"[anteprima] {etichetta}: {nome}")
                    continue
                try:
                    originale = legacy.read_bytes()
                    cifrato = originale if is_encrypted(originale) else encrypt_bytes(originale)
                    destinazione.parent.mkdir(parents=True, exist_ok=True)
                    destinazione.write_bytes(cifrato)
                    controllo = decrypt_bytes(destinazione.read_bytes())
                    atteso = decrypt_bytes(originale)
                    if hashlib.sha256(controllo).digest() != hashlib.sha256(atteso).digest():
                        destinazione.unlink(missing_ok=True)
                        raise ValueError("verifica dopo la cifratura non riuscita")
                    legacy.unlink()
                    spostati += 1
                    self.stdout.write(f"[spostato] {etichetta}: {nome}")
                except Exception as exc:  # un file rotto non ferma gli altri
                    errori += 1
                    self.stderr.write(f"[errore] {etichetta}: {nome}: {exc}")

        if options["orfani"]:
            for cartella in CARTELLE_PROTETTE:
                base = media_root / cartella
                if not base.is_dir():
                    continue
                orfani = [p for p in base.rglob("*") if p.is_file() and p.resolve() not in referenziati]
                if orfani:
                    self.stdout.write(f"[orfani] {cartella}/: {len(orfani)} file non referenziati")

        if apply:
            from core.audit import log_action

            log_action(None, "media_privatizza", "core",
                       {"spostati": spostati, "errori": errori, "app": options["app"] or "tutte"})
            self.stdout.write(self.style.SUCCESS(f"Spostati {spostati} file, errori {errori}."))
        else:
            self.stdout.write(f"Anteprima: {da_spostare} file da spostare. Rilancia con --apply.")
        if errori:
            raise CommandError(f"{errori} file non spostati: vedi gli errori sopra.")
