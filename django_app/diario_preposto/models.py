from __future__ import annotations

import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


class SegnalazionePreposto(models.Model):
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

    def __str__(self) -> str:
        return f"{self.titolo} – {self.chi_segnala or self.preposto}"


class SegnalazioneAllegato(models.Model):
    segnalazione = models.ForeignKey(
        SegnalazionePreposto,
        on_delete=models.CASCADE,
        related_name="allegati",
    )
    nome_file = models.CharField(max_length=300)
    file = models.FileField(upload_to="diario_preposto/allegati/")
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

    def __str__(self) -> str:
        return "Impostazioni Diario Preposto"
