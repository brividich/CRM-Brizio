from __future__ import annotations

import hashlib
import json
import logging

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

STATO_BOZZA = "bozza"
STATO_PUBBLICATA = "pubblicata"
STATO_ARCHIVIATA = "archiviata"

_STATI = [
    (STATO_BOZZA, "Bozza"),
    (STATO_PUBBLICATA, "Pubblicata"),
    (STATO_ARCHIVIATA, "Archiviata"),
]

COMPLIANCE_NON_LETTO = "non_letto"
COMPLIANCE_APERTO = "aperto"
COMPLIANCE_NON_CONFORME = "non_conforme"
COMPLIANCE_CONFORME = "conforme"


class Notizia(models.Model):
    titolo = models.CharField(max_length=300)
    corpo = models.TextField()
    stato = models.CharField(max_length=20, choices=_STATI, default=STATO_BOZZA, db_index=True)
    versione = models.PositiveIntegerField(default=1)
    hash_versione = models.CharField(max_length=64, blank=True, editable=False)
    obbligatoria = models.BooleanField(default=False, db_index=True)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notizie_create",
    )
    pubblicato_il = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pubblicato_il", "-created_at"]
        verbose_name = "Notizia"
        verbose_name_plural = "Notizie"

    def __str__(self) -> str:
        return f"[{self.get_stato_display()}] {self.titolo} v{self.versione}"


class NotiziaAudience(models.Model):
    """Restringe la visibilità di una notizia a specifici ruoli legacy.

    Se non esiste nessun record per una notizia, la notizia è visibile a tutti.
    """

    notizia = models.ForeignKey(Notizia, on_delete=models.CASCADE, related_name="audience")
    legacy_role_id = models.IntegerField()

    class Meta:
        unique_together = [("notizia", "legacy_role_id")]
        verbose_name = "Audience ruolo"
        verbose_name_plural = "Audience ruoli"

    def __str__(self) -> str:
        return f"Notizia {self.notizia_id} → ruolo {self.legacy_role_id}"


class NotiziaAllegato(models.Model):
    """Allegato a una notizia: file uploadato o URL esterna."""

    notizia = models.ForeignKey(Notizia, on_delete=models.CASCADE, related_name="allegati")
    nome_file = models.CharField(max_length=300)
    file = models.FileField(upload_to="notizie/allegati/", null=True, blank=True)
    url_esterno = models.CharField(max_length=500, blank=True)
    hash_file = models.CharField(max_length=64, blank=True)
    dimensione_bytes = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome_file"]
        verbose_name = "Allegato"
        verbose_name_plural = "Allegati"

    def __str__(self) -> str:
        return self.nome_file

    def save(self, *args, **kwargs) -> None:
        if self.file and not self.hash_file:
            try:
                self.file.seek(0)
                sha = hashlib.sha256()
                for chunk in iter(lambda: self.file.read(65536), b""):
                    sha.update(chunk)
                self.hash_file = sha.hexdigest()
                self.file.seek(0)
                if not self.dimensione_bytes:
                    self.file.seek(0, 2)
                    self.dimensione_bytes = self.file.tell()
                    self.file.seek(0)
            except Exception:
                pass
        super().save(*args, **kwargs)


class NotiziaLettura(models.Model):
    """Ricevuta di lettura versionata — un record per (notizia, utente, versione).

    Conformità: esiste un record con versione_letta == notizia.versione AND ack_at IS NOT NULL.
    Le versioni precedenti rimangono per audit.
    """

    notizia = models.ForeignKey(Notizia, on_delete=models.CASCADE, related_name="letture")
    legacy_user_id = models.IntegerField(db_index=True)
    versione_letta = models.PositiveIntegerField()
    hash_versione_letta = models.CharField(max_length=64)
    opened_at = models.DateTimeField(null=True, blank=True)
    ack_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("notizia", "legacy_user_id", "versione_letta")]
        ordering = ["-versione_letta"]
        verbose_name = "Lettura"
        verbose_name_plural = "Letture"

    def __str__(self) -> str:
        return f"Lettura notizia {self.notizia_id} utente {self.legacy_user_id} v{self.versione_letta}"


# ---------------------------------------------------------------------------
# Funzioni helper
# ---------------------------------------------------------------------------

def compute_hash_versione(notizia: Notizia) -> str:
    """Calcola SHA-256 deterministico della versione corrente della notizia.

    Include: titolo, corpo, versione, lista allegati ordinata per nome_file.
    Non include: id (immutabile anche se l'id cambia in un restore).
    """
    allegati = list(
        notizia.allegati.values("nome_file", "hash_file", "url_esterno").order_by("nome_file")
    )
    payload = {
        "titolo": notizia.titolo,
        "corpo": notizia.corpo,
        "versione": notizia.versione,
        "allegati": [
            {
                "nome_file": a["nome_file"],
                "fingerprint": a["hash_file"] or a["url_esterno"],
            }
            for a in allegati
        ],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_visible_to_user(notizia: Notizia, legacy_role_id: int | None) -> bool:
    """Restituisce True se la notizia è visibile al ruolo dato.

    Se non ci sono record di audience, la notizia è pubblica (visibile a tutti).
    """
    if not notizia.audience.exists():
        return True
    if legacy_role_id is None:
        return False
    return notizia.audience.filter(legacy_role_id=legacy_role_id).exists()


def get_compliance_status(notizia: Notizia, legacy_user_id: int) -> str:
    """Stato di compliance per un utente rispetto alla versione corrente.

    Returns:
        'conforme'      — ha confermato la versione corrente
        'non_conforme'  — ha confermato una versione precedente ma non quella corrente
        'aperto'        — ha aperto la notizia (versione corrente) ma non ancora confermato
        'non_letto'     — non ha mai aperto la versione corrente
    """
    letture = list(
        NotiziaLettura.objects.filter(
            notizia=notizia, legacy_user_id=legacy_user_id
        ).order_by("-versione_letta")
    )
    versione_corrente = notizia.versione

    for lettura in letture:
        if lettura.versione_letta == versione_corrente:
            if lettura.ack_at:
                return COMPLIANCE_CONFORME
            if lettura.opened_at:
                return COMPLIANCE_APERTO
            return COMPLIANCE_NON_LETTO

    # Nessun record per versione corrente
    if letture:
        return COMPLIANCE_NON_CONFORME
    return COMPLIANCE_NON_LETTO


def get_or_create_lettura(notizia: Notizia, legacy_user_id: int) -> NotiziaLettura:
    """Restituisce (o crea) il record di lettura per la versione corrente."""
    lettura, _ = NotiziaLettura.objects.get_or_create(
        notizia=notizia,
        legacy_user_id=legacy_user_id,
        versione_letta=notizia.versione,
        defaults={
            "hash_versione_letta": notizia.hash_versione,
            "opened_at": None,
            "ack_at": None,
        },
    )
    return lettura


def pubblica_notizia(notizia: Notizia, prima_pubblicazione: bool = False) -> None:
    """Pubblica o ri-pubblica una notizia incrementando la versione e ricalcolando l'hash.

    Se è la prima pubblicazione (stato bozza → pubblicata), non incrementa la versione.
    """
    if not prima_pubblicazione:
        notizia.versione += 1
    notizia.hash_versione = compute_hash_versione(notizia)
    notizia.stato = STATO_PUBBLICATA
    notizia.pubblicato_il = timezone.now()
    notizia.save(update_fields=["versione", "hash_versione", "stato", "pubblicato_il"])
