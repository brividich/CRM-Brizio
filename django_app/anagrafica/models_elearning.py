"""E-learning professionale (prompt 05, rilascio 2): tracciamento lato server e registro.

- ``TrainingElearningSessione``: una sessione di fruizione del player. Il tempo si
  accredita solo da heartbeat lato server (limite ≥ 30 s, pausa per inattività,
  una sessione attiva per iscrizione): mai sommando valori inviati dal browser.
- ``TrainingElearningSlideView``: tempo effettivo per slide e slide «completata».
- ``TrainingElearningCompletamento``: la riga che garantisce **a livello di
  database** un solo completamento per iscrizione (OneToOne su iscrizione e su
  record) e che fotografa i requisiti verificati: è la riga del registro di audit.

File importato da ``anagrafica/models.py`` (``from .models_elearning import *``).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

__all__ = ["TrainingElearningSessione", "TrainingElearningSlideView", "TrainingElearningCompletamento"]


class TrainingElearningSessione(models.Model):
    enrollment = models.ForeignKey(
        "anagrafica.TrainingElearningEnrollment", on_delete=models.CASCADE, related_name="sessioni",
    )
    avviata_il = models.DateTimeField(auto_now_add=True)
    ultimo_beat_il = models.DateTimeField()
    slide_corrente = models.ForeignKey(
        "anagrafica.TrainingSlide", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    secondi_accreditati = models.PositiveIntegerField(default=0)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ua_hash = models.CharField(max_length=64, blank=True, default="")
    chiusa = models.BooleanField(default=False)

    class Meta:
        ordering = ["-avviata_il"]
        verbose_name = "Sessione e-learning"
        verbose_name_plural = "Sessioni e-learning"
        indexes = [models.Index(fields=["enrollment", "chiusa"])]

    def __str__(self) -> str:
        return f"Sessione #{self.pk} iscrizione {self.enrollment_id}"


class TrainingElearningSlideView(models.Model):
    enrollment = models.ForeignKey(
        "anagrafica.TrainingElearningEnrollment", on_delete=models.CASCADE, related_name="slide_viste",
    )
    slide = models.ForeignKey("anagrafica.TrainingSlide", on_delete=models.CASCADE, related_name="viste")
    prima_vista = models.DateTimeField(auto_now_add=True)
    ultima_vista = models.DateTimeField(auto_now=True)
    secondi = models.PositiveIntegerField(default=0)
    completata = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Slide vista"
        verbose_name_plural = "Slide viste"
        constraints = [models.UniqueConstraint(fields=["enrollment", "slide"], name="uniq_elearning_slide_vista")]


class TrainingElearningCompletamento(models.Model):
    """Un solo completamento per iscrizione (ciclo), con la prova di cosa è stato verificato."""

    enrollment = models.OneToOneField(
        "anagrafica.TrainingElearningEnrollment", on_delete=models.PROTECT, related_name="completamento",
    )
    record = models.OneToOneField(
        "anagrafica.TrainingEmployeeRecord", on_delete=models.PROTECT, related_name="completamento_elearning",
    )
    tentativo = models.ForeignKey(
        "anagrafica.TrainingQuizAttempt", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
    )
    verifica_json = models.JSONField(default=dict)
    sha256 = models.CharField(max_length=64)
    creato_il = models.DateTimeField(auto_now_add=True)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-creato_il"]
        verbose_name = "Completamento e-learning (registro)"
        verbose_name_plural = "Completamenti e-learning (registro)"

    def __str__(self) -> str:
        return f"Completamento #{self.pk} record {self.record_id}"
