"""Revisioni della struttura organizzativa (documento controllato della Qualità).

La struttura viva (reparti → aree → ruoli → mansioni → processi) è la *bozza*:
si modifica nelle pagine di Anagrafica e del Mansionario. Quando la Qualità la
approva, l'MSM **emette una revisione**: qui resta la fotografia completa e non
modificabile di quel momento, con numero, data, motivo e chi l'ha emessa.
Il confronto fra due revisioni e il PDF del mansionario ufficiale si fanno da
queste fotografie, mai dalla struttura viva.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

__all__ = ["StrutturaRevisione"]


class StrutturaRevisione(models.Model):
    numero = models.PositiveIntegerField(unique=True)
    emessa_il = models.DateTimeField(auto_now_add=True)
    emessa_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="revisioni_struttura_emesse",
    )
    # Nome leggibile al momento dell'emissione: resta anche se l'utente sparisce.
    emessa_da_nome = models.CharField(max_length=200, blank=True, default="")
    motivo = models.CharField(max_length=500)
    dati = models.JSONField(default=dict, help_text="Fotografia completa della struttura.")
    riepilogo = models.JSONField(default=dict, help_text="Conteggi per l'elenco revisioni.")

    class Meta:
        ordering = ["-numero"]
        verbose_name = "Revisione della struttura"
        verbose_name_plural = "Revisioni della struttura"

    def __str__(self) -> str:
        return f"Struttura Rev. {self.numero}"
