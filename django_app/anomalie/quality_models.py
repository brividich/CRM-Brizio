"""Scheda qualita' delle anomalie (classificazione strutturata ISO 9001 / EN 9100).

La segnalazione resta una riga della tabella legacy ``anomalie`` (con il suo trigger
SQL delle automazioni): la classificazione vive qui, in una tabella Django agganciata
1:1 per id, senza toccare lo schema legacy.

- ``AnomaliaTipoDifetto``: catalogo configurabile dei tipi di difetto (Pareto).
- ``AnomaliaSchedaQualita``: protocollo NC, origine, difetto, gravita', reparto,
  quantita' e decisione sul materiale non conforme (EN 9100 §8.7), piu' il
  collegamento alla voce NC del registro OFI/NC (ISO 9001 §10.2) quando serve.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class AnomaliaTipoDifetto(models.Model):
    codice = models.SlugField(max_length=40, unique=True)
    nome = models.CharField(max_length=120, unique=True)
    famiglia = models.CharField(max_length=80, blank=True, default="")
    attivo = models.BooleanField(default=True, db_index=True)
    ordine = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Tipo difetto anomalie"
        verbose_name_plural = "Catalogo tipi difetto anomalie"

    def __str__(self) -> str:
        return self.nome


class AnomaliaSchedaQualita(models.Model):
    class Origine(models.TextChoices):
        PRODUZIONE = "PRODUZIONE", "Interna - produzione"
        CONTROLLO = "CONTROLLO", "Interna - controllo qualità"
        FORNITORE = "FORNITORE", "Fornitore / lavorazione esterna"
        CLIENTE = "CLIENTE", "Cliente"
        AUDIT = "AUDIT", "Audit"

    class Gravita(models.TextChoices):
        MINORE = "MINORE", "Minore"
        MAGGIORE = "MAGGIORE", "Maggiore"
        CRITICA = "CRITICA", "Critica"

    class Disposizione(models.TextChoices):
        DA_DEFINIRE = "DA_DEFINIRE", "Da definire"
        USO_TALE = "USO_TALE", "Uso così com'è"
        RILAVORAZIONE = "RILAVORAZIONE", "Rilavorazione"
        RIPARAZIONE = "RIPARAZIONE", "Riparazione"
        DEROGA = "DEROGA", "Concessione / deroga cliente"
        SCARTO = "SCARTO", "Scarto"
        RESO_FORNITORE = "RESO_FORNITORE", "Reso al fornitore"

    # Id della riga legacy ``anomalie`` (niente FK: tabella non gestita da Django).
    anomalia_id = models.IntegerField(unique=True, db_index=True)
    protocollo = models.CharField(max_length=20, unique=True)

    # Istantanea dell'OP al momento della registrazione (il P/N di un OP non cambia):
    # serve a Pareto e ricorrenze senza rileggere ogni volta ordini_produzione.
    op_titolo = models.CharField(max_length=100, blank=True, default="", db_index=True)
    part_number = models.CharField(max_length=120, blank=True, default="", db_index=True)

    origine = models.CharField(max_length=12, choices=Origine.choices, blank=True, default="")
    tipo_difetto = models.ForeignKey(
        AnomaliaTipoDifetto, on_delete=models.PROTECT, null=True, blank=True,
        related_name="schede",
    )
    gravita = models.CharField(max_length=10, choices=Gravita.choices, blank=True, default="")
    reparto = models.ForeignKey(
        "anagrafica.Reparto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    quantita_nc = models.PositiveIntegerField(null=True, blank=True)
    quantita_scartata = models.PositiveIntegerField(null=True, blank=True)
    disposizione = models.CharField(
        max_length=16, choices=Disposizione.choices, default=Disposizione.DA_DEFINIRE,
    )
    # True finche' la disposizione e' quella dedotta dal sistema dai flag
    # dell'anomalia; diventa False appena un utente la sceglie a mano.
    disposizione_auto = models.BooleanField(default=True)

    registro_nc = models.ForeignKey(
        "gestione_specifiche.RegistroOFI", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="schede_anomalie",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = "Scheda qualità anomalia"
        verbose_name_plural = "Schede qualità anomalie"
        indexes = [
            models.Index(fields=["part_number", "tipo_difetto"], name="anomalie_sq_pn_difetto"),
        ]

    def __str__(self) -> str:
        return self.protocollo
