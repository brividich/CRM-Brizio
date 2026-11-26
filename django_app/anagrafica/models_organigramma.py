"""Organigrammi ufficiali: documenti disegnati a mano, con revisioni.

Il diagramma di Anagrafica è *calcolato* dai dati (ruoli, «riporta a»,
assegnazioni). L'organigramma ufficiale è un'altra cosa: un **disegno** fatto da
chi lo redige, come in Word, con riquadri presi da ruoli, persone, mansioni o
testo libero, gruppi («team») e linee di staff. Non scrive niente su ruoli,
capi, assegnazioni o permessi: li legge soltanto, per mostrare nomi e foto e per
segnalare dove il disegno non corrisponde più ai dati.

Si lavora su una **bozza** (``OrganigrammaUfficiale.bozza``) e si **pubblica**:
la pubblicazione crea una :class:`OrganigrammaRevisione` numerata e non più
modificabile, che è quella che vedono tutti.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

__all__ = ["OrganigrammaUfficiale", "OrganigrammaRevisione"]


class OrganigrammaUfficiale(models.Model):
    nome = models.CharField(max_length=150)
    descrizione = models.CharField(max_length=300, blank=True, default="")
    ambito = models.ForeignKey(
        "anagrafica.AmbitoRuolo", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="organigrammi_ufficiali",
        help_text="Facoltativo: i ruoli di questo ambito non disegnati vengono segnalati.",
    )
    # Disegno in corso: ``None`` = nessuna bozza aperta.
    bozza = models.JSONField(null=True, blank=True)
    bozza_aggiornata_il = models.DateTimeField(null=True, blank=True)
    bozza_aggiornata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    ordine = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    creato_il = models.DateTimeField(auto_now_add=True)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Organigramma ufficiale"
        verbose_name_plural = "Organigrammi ufficiali"

    def __str__(self) -> str:
        return self.nome

    def revisione_in_vigore(self):
        return self.revisioni.order_by("-numero").first()


class OrganigrammaRevisione(models.Model):
    organigramma = models.ForeignKey(OrganigrammaUfficiale, on_delete=models.CASCADE, related_name="revisioni")
    numero = models.PositiveIntegerField()
    dati = models.JSONField(default=dict, help_text="Disegno pubblicato: riquadri, gruppi e collegamenti.")
    nota = models.TextField(blank=True, default="")
    approvato_da = models.CharField(max_length=200, blank=True, default="")
    data_emissione = models.DateField()
    pubblicata_il = models.DateTimeField(auto_now_add=True)
    pubblicata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["organigramma", "-numero"]
        unique_together = [("organigramma", "numero")]
        verbose_name = "Revisione di organigramma ufficiale"
        verbose_name_plural = "Revisioni di organigrammi ufficiali"

    def __str__(self) -> str:
        return f"{self.organigramma} Rev.{self.numero}"
