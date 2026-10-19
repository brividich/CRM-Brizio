"""Applicazioni autorizzate a leggere i dati del portale dall'API ``/api/v1/``.

Il token in chiaro si vede una volta sola, alla creazione
(``manage.py dati_api_client``): a DB resta solo l'hash SHA-256, come per i
collector dei contatori (``assets.MeterIngestClient``).
"""
from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models

# Ambiti che un'applicazione può leggere. Nessuno espone nomi di persone o dati
# sanitari: il personale c'è solo come conteggi aggregati per reparto.
AMBITI = {
    "asset": "Anagrafica asset (tag, nome, categoria, reparto, stato)",
    "manutenzione": "Ordini di lavoro (tipo, stato, date, ore, costi; senza assegnatari)",
    "scadenze": "Scadenze di asset, licenze, contratti, verifiche impianti, DPI, RENTRI, CAPA (senza nominativi)",
    "personale_aggregato": "Scadenze del personale come soli conteggi per reparto e tipo",
}


class ApiClient(models.Model):
    """Applicazione (Power BI, Power Automate, gestionale) che legge l'API dati."""

    nome = models.CharField(max_length=120, unique=True)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    ambiti = models.JSONField(default=list, blank=True, help_text="Chiavi di dati_bi.models.AMBITI")
    attivo = models.BooleanField(default=True, db_index=True)
    ultimo_accesso = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    creato_il = models.DateTimeField(auto_now_add=True)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["nome", "id"]
        verbose_name = "Applicazione API dati"
        verbose_name_plural = "Applicazioni API dati"

    def __str__(self) -> str:
        return self.nome

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

    @staticmethod
    def nuovo_token() -> str:
        return "pnh_" + secrets.token_urlsafe(32)

    def imposta_token(self, token: str) -> None:
        self.token_hash = self.hash_token(token)

    def puo(self, ambito: str) -> bool:
        return isinstance(self.ambiti, list) and ambito in self.ambiti
