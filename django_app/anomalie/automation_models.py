"""Marcatori di idempotenza delle automazioni anomalie.

Il task orario rilegge ogni volta lo stato dalla tabella legacy `anomalie`: senza
memoria, lo stesso P/N ricorrente o lo stesso OP completato verrebbe notificato a
ogni run. Una riga qui dice "questo evento e' gia' stato notificato".
"""
from __future__ import annotations

from django.db import models


class AnomalieAutomazioneMarker(models.Model):
    class Tipo(models.TextChoices):
        RESOCONTO = "resoconto", "Resoconto giornaliero inviato"
        RICORRENZA_PN = "ricorrenza_pn", "Allarme difetto ricorrente P/N"
        DIGEST = "digest", "Digest settimanale inviato"
        OP_COMPLETATO = "op_completato", "OP completato notificato"

    tipo = models.CharField(max_length=32, choices=Tipo.choices, db_index=True)
    chiave = models.CharField(max_length=255)
    dettaglio = models.JSONField(default=dict, blank=True)
    creato_il = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-creato_il"]
        indexes = [models.Index(fields=["tipo", "chiave"], name="anomalie_marker_tipo_chiave")]
        verbose_name = "Marcatore automazione anomalie"
        verbose_name_plural = "Marcatori automazioni anomalie"

    def __str__(self) -> str:
        return f"{self.tipo}:{self.chiave}"
