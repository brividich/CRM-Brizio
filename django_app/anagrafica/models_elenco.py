"""Viste dell'elenco dipendenti configurabili da admin (prompt 03).

Una vista contiene solo CHIAVI del registro ``services.colonne_elenco.REGISTRO``: i permessi
delle colonne si valutano a ogni richiesta, quindi una vista condivisa non espone a nessuno
una colonna che non può vedere.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

__all__ = ["VistaElenco", "PreferenzaVistaUtente"]


class VistaElenco(models.Model):
    AMBITO_GLOBALE = "GLOBALE"
    AMBITO_RUOLO = "RUOLO"
    AMBITO_CHOICES = [(AMBITO_GLOBALE, "Tutti"), (AMBITO_RUOLO, "Solo un ruolo")]

    codice = models.SlugField(max_length=60, unique=True)
    nome = models.CharField(max_length=120)
    descrizione = models.CharField(max_length=300, blank=True, default="")
    # [{"chiave": "reparto", "visibile": true, "larghezza": 0}, ...] nell'ordine di colonna.
    colonne = models.JSONField(default=list, blank=True)
    ordinamento = models.CharField(max_length=60, blank=True, default="", help_text="Chiave della colonna su cui ordinare all'apertura.")
    # Filtri dell'elenco applicati all'apertura: {"reparto": "...", "area": "...", "tipologia_contratto": "..."}.
    filtri = models.JSONField(default=dict, blank=True)
    predefinita = models.BooleanField(default=False, help_text="Vista proposta a chi non ne ha scelta una.")
    ambito = models.CharField(max_length=10, choices=AMBITO_CHOICES, default=AMBITO_GLOBALE)
    ruolo_legacy_id = models.IntegerField(null=True, blank=True, help_text="Con ambito «Solo un ruolo»: id del ruolo legacy.")
    blocca_personalizzazione = models.BooleanField(
        default=False, help_text="Chi usa questa vista non può nascondere o riordinare le colonne.",
    )
    preset = models.BooleanField(default=False, editable=False, help_text="Creata dal sistema: si può modificare e ripristinare.")
    ordine = models.PositiveSmallIntegerField(default=100)
    attiva = models.BooleanField(default=True)
    aggiornata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    aggiornata_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Vista elenco dipendenti"
        verbose_name_plural = "Viste elenco dipendenti"

    def __str__(self) -> str:
        return self.nome

    @property
    def chiavi(self) -> list[str]:
        return [str(v.get("chiave")) for v in (self.colonne or []) if isinstance(v, dict) and v.get("visibile", True)]


class PreferenzaVistaUtente(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferenza_vista_dipendenti")
    vista = models.ForeignKey(VistaElenco, null=True, blank=True, on_delete=models.SET_NULL, related_name="preferenze")
    aggiornata_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Preferenza vista elenco"
        verbose_name_plural = "Preferenze vista elenco"
