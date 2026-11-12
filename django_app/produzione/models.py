"""Documenti di produzione degli OP.

Gli OP stanno nella tabella ``ordini_produzione`` (vedi ``core/ordini_produzione.py``),
che non appartiene a nessun modulo: qui un documento cita l'OP col suo titolo, come
fanno Gestione anomalie e il Registro FAI. I FAI restano nel Registro FAI e la scheda
dell'OP li mostra insieme a questi documenti.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class TipoDocumento(models.Model):
    """Tipi di documento di produzione, decisi in Impostazioni."""

    etichetta = models.CharField(max_length=80, unique=True)
    descrizione = models.CharField(max_length=255, blank=True, default="")
    ordine = models.PositiveIntegerField(default=100)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "etichetta"]
        verbose_name = "Tipo di documento di produzione"
        verbose_name_plural = "Tipi di documento di produzione"

    def __str__(self) -> str:
        return self.etichetta


class DocumentoOP(models.Model):
    op = models.CharField(max_length=100, db_index=True, verbose_name="OP")
    tipo = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name="documenti")
    titolo = models.CharField(max_length=200, blank=True, default="", verbose_name="Titolo o numero")
    revisione = models.CharField(max_length=40, blank=True, default="", verbose_name="Rev.")
    data = models.DateField(null=True, blank=True, verbose_name="Data")
    percorso = models.CharField(max_length=500, blank=True, default="", verbose_name="Cartella o file di rete")
    note = models.TextField(blank=True, default="", max_length=2000)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    creato_il = models.DateTimeField(auto_now_add=True)
    modificato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tipo__ordine", "tipo__etichetta", "-data", "-id"]
        verbose_name = "Documento di produzione"
        verbose_name_plural = "Documenti di produzione"

    def __str__(self) -> str:
        return f"{self.tipo} {self.titolo}".strip()
