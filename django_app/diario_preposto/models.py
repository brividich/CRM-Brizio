from __future__ import annotations

import logging

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .storage import PrivateDiarioPrepostoStorage

logger = logging.getLogger(__name__)

CODICE_PREPOSTO_PREFIX = "DP"
CODICE_PREPOSTO_PADDING = 4
CODICE_PREPOSTO_START = 0


def _anno_segnalazione(value) -> int:
    if value is None:
        return timezone.localtime(timezone.now()).year
    if timezone.is_naive(value):
        return value.year
    return timezone.localtime(value).year


def _build_codice_preposto(year: int, sequence: int) -> str:
    return f"{CODICE_PREPOSTO_PREFIX}-{year}-{sequence:0{CODICE_PREPOSTO_PADDING}d}"


def _extract_codice_sequence(code: str, year: int) -> int | None:
    prefix = f"{CODICE_PREPOSTO_PREFIX}-{year}-"
    if not code or not str(code).startswith(prefix):
        return None
    try:
        return int(str(code)[len(prefix):])
    except ValueError:
        return None


class SegnalazionePreposto(models.Model):
    codice_identificativo = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        editable=False,
        db_index=True,
    )
    titolo = models.CharField(max_length=300)
    data_segnalazione = models.DateTimeField()
    descrizione = models.TextField()
    preposto = models.CharField(max_length=200, blank=True)
    chi_segnala = models.CharField(max_length=200, blank=True)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="segnalazioni_preposto_create",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_segnalazione", "-created_at"]
        verbose_name = "Segnalazione Preposto"
        verbose_name_plural = "Segnalazioni Preposto"

    @classmethod
    def next_codice_identificativo(cls, year: int) -> str:
        prefix = f"{CODICE_PREPOSTO_PREFIX}-{year}-"
        last_code = (
            cls.objects.filter(codice_identificativo__startswith=prefix)
            .order_by("-codice_identificativo")
            .values_list("codice_identificativo", flat=True)
            .first()
        )
        last_sequence = _extract_codice_sequence(last_code or "", year)
        next_sequence = CODICE_PREPOSTO_START if last_sequence is None else last_sequence + 1
        return _build_codice_preposto(year, next_sequence)

    def save(self, *args, **kwargs):
        if self.codice_identificativo:
            return super().save(*args, **kwargs)

        update_fields = kwargs.get("update_fields")
        call_kwargs = dict(kwargs)
        if update_fields is not None:
            call_kwargs["update_fields"] = set(update_fields) | {"codice_identificativo"}

        max_attempts = 5
        for attempt in range(max_attempts):
            self.codice_identificativo = self.next_codice_identificativo(
                _anno_segnalazione(self.data_segnalazione)
            )
            try:
                with transaction.atomic():
                    return super().save(*args, **call_kwargs)
            except IntegrityError:
                self.codice_identificativo = ""
                if not self._state.adding or attempt == max_attempts - 1:
                    raise

    def __str__(self) -> str:
        label = self.codice_identificativo or f"pk:{self.pk}"
        return f"[{label}] {self.titolo} - {self.chi_segnala or self.preposto}"


class SegnalazioneAllegato(models.Model):
    segnalazione = models.ForeignKey(
        SegnalazionePreposto,
        on_delete=models.CASCADE,
        related_name="allegati",
    )
    nome_file = models.CharField(max_length=300)
    file = models.FileField(
        upload_to="diario_preposto/allegati/",
        storage=PrivateDiarioPrepostoStorage,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome_file"]
        verbose_name = "Allegato segnalazione"
        verbose_name_plural = "Allegati segnalazione"

    def __str__(self) -> str:
        return self.nome_file


class DiarioPrepostoImpostazioni(models.Model):
    """Singleton: impostazioni del modulo Diario Preposto."""

    acl_scrittura = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Lista di username o email autorizzati alla scrittura "
            "(creazione/modifica/eliminazione), oltre agli admin legacy."
        ),
    )

    class Meta:
        verbose_name = "Impostazioni Diario Preposto"
        verbose_name_plural = "Impostazioni Diario Preposto"
        constraints = [
            models.CheckConstraint(check=models.Q(pk=1), name="diarioprepostoimpostazioni_singleton"),
        ]

    def __str__(self) -> str:
        return "Impostazioni Diario Preposto"

    @classmethod
    def get_singleton(cls) -> "DiarioPrepostoImpostazioni":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
