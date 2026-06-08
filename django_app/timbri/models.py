from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .storage import PrivateTimbriStorage


PNG_MAX_SIZE = 20 * 1024 * 1024


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = slugify(str(value or "").strip())
    return cleaned[:80] or fallback


def _registro_image_upload_to(instance: "RegistroTimbroImmagine", filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()[:20] or ".png"
    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    operatore = instance.registro.operatore if instance.registro_id else None
    operatore_key = _safe_segment(getattr(operatore, "full_name", "") or getattr(operatore, "matricola", ""), "operatore")
    record_key = instance.registro_id or "tmp"
    variant = str(instance.variante or "").strip().lower()
    folder = "timbri" if variant == RegistroTimbroImmagine.VARIANTE_TIMBRO else "firme"
    return f"{folder}/{operatore_key}/{record_key}/{stamp}_{variant}{suffix}"


class OperatoreTimbri(models.Model):
    legacy_anagrafica_id = models.IntegerField(null=True, blank=True, db_index=True)
    nome = models.CharField(max_length=200)
    cognome = models.CharField(max_length=200, blank=True, default="")
    matricola = models.CharField(max_length=100, blank=True, default="", db_index=True)
    reparto = models.CharField(max_length=200, blank=True, default="", db_index=True)
    ruolo = models.CharField(max_length=200, blank=True, default="")
    email_notifica = models.CharField(max_length=200, blank=True, default="")
    is_active_legacy = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cognome", "nome", "matricola", "id"]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        text = f"{self.cognome} {self.nome}".strip()
        return " ".join(text.split()) or self.nome or self.matricola or f"operatore:{self.pk}"


class TimbriImportIssue(models.Model):
    source_file = models.CharField(max_length=255, blank=True, default="", db_index=True)
    csv_row_number = models.PositiveIntegerField(db_index=True)
    sharepoint_item_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    operatore_label = models.CharField(max_length=200, blank=True, default="")
    operatore_label_alt = models.CharField(max_length=200, blank=True, default="")
    matricola = models.CharField(max_length=100, blank=True, default="", db_index=True)
    reparto = models.CharField(max_length=200, blank=True, default="")
    qualifica = models.CharField(max_length=200, blank=True, default="")
    codice_timbro = models.CharField(max_length=120, blank=True, default="")
    tipo_timbro_raw = models.CharField(max_length=100, blank=True, default="")
    attivo_raw = models.CharField(max_length=20, blank=True, default="")
    motivo_scarto = models.TextField(blank=True, default="")
    raw_payload = models.TextField(blank=True, default="")
    is_resolved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["is_resolved", "operatore_label", "matricola", "csv_row_number", "id"]
        unique_together = [("source_file", "csv_row_number")]
        verbose_name = "Scarto import timbri"
        verbose_name_plural = "Scarti import timbri"

    def __str__(self) -> str:
        base = self.operatore_label or self.operatore_label_alt or self.matricola or f"riga:{self.csv_row_number}"
        return f"{base} - {self.motivo_scarto[:80]}"


class RegistroTimbro(models.Model):
    TIPO_FISICO = "FISICO"
    TIPO_DIGITALE = "DIGITALE"
    TIPO_FISICO_E_DIGITALE = "FISICO_E_DIGITALE"
    TIPO_ALTRO = "ALTRO"
    TIPO_SOLO_FIRMA = "SOLO_FIRMA"
    TIPO_SOLO_SIGLA = "SOLO_SIGLA"

    TIPO_CHOICES = [
        (TIPO_FISICO, "Fisico"),
        (TIPO_DIGITALE, "Digitale"),
        (TIPO_FISICO_E_DIGITALE, "Fisico e digitale"),
        (TIPO_ALTRO, "Altro"),
        (TIPO_SOLO_FIRMA, "Solo firma"),
        (TIPO_SOLO_SIGLA, "Solo sigla"),
    ]

    # Tipi che rappresentano un timbro "reale" (non solo firma/sigla)
    TIPI_TIMBRO = {TIPO_FISICO, TIPO_DIGITALE, TIPO_FISICO_E_DIGITALE, TIPO_ALTRO}
    TIPI_FIRMA = {TIPO_SOLO_FIRMA}
    TIPI_SIGLA = {TIPO_SOLO_SIGLA}

    operatore = models.ForeignKey(OperatoreTimbri, on_delete=models.CASCADE, related_name="registri")
    codice_timbro = models.CharField(max_length=120, blank=True, default="", db_index=True)
    qualifica = models.CharField(max_length=200, blank=True, default="")
    tipo_timbro = models.CharField(max_length=30, choices=TIPO_CHOICES, default=TIPO_FISICO_E_DIGITALE)
    data_consegna = models.DateField(null=True, blank=True)
    data_ritiro = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    firma_testo = models.TextField(blank=True, default="")
    is_attivo = models.BooleanField(default=True, db_index=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    sharepoint_item_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    last_import_at = models.DateTimeField(null=True, blank=True)
    edited_in_portal = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timbri_registri_creati",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timbri_registri_aggiornati",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_attivo", "-data_consegna", "-updated_at", "-id"]

    def __str__(self) -> str:
        base = self.codice_timbro or self.qualifica or f"registro:{self.pk}"
        return f"{self.operatore.full_name} - {base}"

    def clean(self) -> None:
        if self.is_archived and self.is_attivo:
            self.is_attivo = False

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def stato_label(self) -> str:
        if self.is_archived:
            return "Archiviato"
        if self.is_attivo:
            return "Attivo"
        return "Superato"


class RegistroTimbroImmagine(models.Model):
    VARIANTE_TIMBRO = "TIMBRO"
    VARIANTE_FIRMA = "FIRMA"
    VARIANTE_SIGLA = "SIGLA"

    VARIANTE_CHOICES = [
        (VARIANTE_TIMBRO, "Timbro"),
        (VARIANTE_FIRMA, "Firma"),
        (VARIANTE_SIGLA, "Sigla"),
    ]

    registro = models.ForeignKey(RegistroTimbro, on_delete=models.CASCADE, related_name="immagini")
    variante = models.CharField(max_length=20, choices=VARIANTE_CHOICES)
    image = models.ImageField(upload_to=_registro_image_upload_to, storage=PrivateTimbriStorage)
    source_url = models.CharField(max_length=1000, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    file_size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["variante", "id"]
        unique_together = [("registro", "variante")]

    def __str__(self) -> str:
        return f"{self.registro_id}:{self.variante}"

    def clean(self) -> None:
        if not self.image:
            raise ValidationError({"image": "Immagine obbligatoria."})
        file_obj = self.image.file if hasattr(self.image, "file") else self.image
        size = int(getattr(file_obj, "size", 0) or 0)
        name = str(getattr(self.image, "name", "") or "")
        if size and size > PNG_MAX_SIZE:
            raise ValidationError({"image": "Dimensione massima 20 MB."})
        if name and Path(name).suffix.lower() != ".png":
            raise ValidationError({"image": "Sono consentiti solo file PNG."})

    def save(self, *args, **kwargs):
        self.full_clean()
        image_field = getattr(self, "image", None)
        if image_field:
            try:
                self.width = int(image_field.width or 0)
                self.height = int(image_field.height or 0)
            except Exception:
                self.width = 0
                self.height = 0
            try:
                self.file_size = int(image_field.size or 0)
            except Exception:
                self.file_size = 0
            if not self.original_filename:
                self.original_filename = os.path.basename(str(image_field.name or ""))[:255]
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        storage = self.image.storage if self.image else None
        file_name = self.image.name if self.image else ""
        super().delete(*args, **kwargs)
        if storage and file_name and storage.exists(file_name):
            storage.delete(file_name)


class TimbriUserPermOverride(models.Model):
    """Override per-utente dei permessi copia/download timbri (sovrascrive il ruolo)."""

    AZIONE_COPY = "timbri_copy"
    AZIONE_DOWNLOAD = "timbri_download"
    AZIONE_CHOICES = [
        (AZIONE_COPY, "Copia immagine"),
        (AZIONE_DOWNLOAD, "Scarica immagine"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="timbri_perm_overrides",
    )
    azione = models.CharField(max_length=40, choices=AZIONE_CHOICES)
    granted = models.BooleanField(
        help_text="True = forza permesso ON anche se il ruolo non ce l'ha; False = forza OFF."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "azione")]
        ordering = ["user__username", "azione"]
        verbose_name = "Override permesso timbri utente"
        verbose_name_plural = "Override permessi timbri utenti"

    def __str__(self) -> str:
        stato = "ON" if self.granted else "OFF"
        return f"{self.user_id}:{self.azione}={stato}"
