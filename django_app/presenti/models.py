"""Modelli del modulo Presenti in azienda.

Le presenze NON stanno qui: si leggono ogni minuto dal database Solari
(``presenti.solari``). Qui restano solo i dati che nascono nel portale:

- ``Appello``: un appello di evacuazione, con la fotografia delle persone presenti
  al momento dell'avvio (chi è entrato dopo non c'era quando è suonato l'allarme);
- ``AppelloSpunta``: chi è stato contato al punto di raccolta, da chi e quando;
- ``AvvisoUscitaMancante``: avvisi già mandati al capo per un'uscita non
  timbrata, così la stessa giornata non viene segnalata due volte.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class Appello(models.Model):
    aperto_il = models.DateTimeField(auto_now_add=True)
    aperto_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    chiuso_il = models.DateTimeField(null=True, blank=True)
    chiuso_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    esercitazione = models.BooleanField(
        default=False, help_text="Prova di evacuazione: resta nello storico distinta da un'emergenza reale.",
    )
    nota = models.CharField(max_length=300, blank=True, default="")
    osservazioni = models.TextField(
        blank=True, default="", help_text="Osservazioni per il verbale: criticità, tempi, azioni di miglioramento.",
    )
    # [{solari_id, legacy_id, cognome, nome, matricola, reparto, incarichi:[{nome, colore}], entrata}]
    persone = models.JSONField(default=list)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-aperto_il"]
        verbose_name = "Appello di evacuazione"
        verbose_name_plural = "Appelli di evacuazione"

    def __str__(self) -> str:
        return f"Appello {self.aperto_il:%d-%m-%Y %H:%M}"

    @property
    def aperto(self) -> bool:
        return self.chiuso_il is None


class AppelloSpunta(models.Model):
    appello = models.ForeignKey(Appello, on_delete=models.CASCADE, related_name="spunte")
    solari_id = models.IntegerField()
    contato_il = models.DateTimeField(auto_now_add=True)
    contato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["appello", "solari_id"], name="presenti_spunta_unica"),
        ]
        verbose_name = "Persona contata"
        verbose_name_plural = "Persone contate"


class AvvisoUscitaMancante(models.Model):
    solari_id = models.IntegerField()
    giorno = models.DateField()
    legacy_anagrafica_id = models.IntegerField(null=True, blank=True)
    capo_legacy_anagrafica_id = models.IntegerField(null=True, blank=True)
    inviato_il = models.DateTimeField(auto_now_add=True)
    esito = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-giorno"]
        constraints = [
            models.UniqueConstraint(fields=["solari_id", "giorno"], name="presenti_avviso_uscita_unico"),
        ]
        verbose_name = "Avviso uscita non timbrata"
        verbose_name_plural = "Avvisi uscita non timbrata"
