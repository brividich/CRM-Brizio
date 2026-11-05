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

__all__ = ["ProspettoModifica", "ProspettoStruttura", "StrutturaRevisione"]


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


class ProspettoStruttura(models.Model):
    """Una prova di cambiamento: niente si scrive finché non si applica."""

    STATO_BOZZA = "BOZZA"
    STATO_APPLICATO = "APPLICATO"
    STATO_ANNULLATO = "ANNULLATO"
    STATO_CHOICES = [(STATO_BOZZA, "In preparazione"), (STATO_APPLICATO, "Applicato"), (STATO_ANNULLATO, "Archiviato")]

    nome = models.CharField(max_length=150)
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_BOZZA)
    # Soglie scelte da chi prepara: non ci sono norme né ore richieste per mansione.
    soglia_mansioni_persona = models.PositiveSmallIntegerField(
        default=8, help_text="Oltre questo numero di mansioni la persona si segnala.",
    )
    soglia_concentrazione = models.PositiveSmallIntegerField(
        default=80, help_text="Dal questa % di tempo media degli operativi sulla mansione il carico è concentrato.",
    )
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="prospetti_creati",
    )
    applicato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="prospetti_applicati",
    )
    applicato_il = models.DateTimeField(null=True, blank=True)
    decorrenza = models.DateField(null=True, blank=True)
    fotografia = models.JSONField(default=dict, blank=True, help_text="Il confronto al momento di applicare.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-pk"]
        verbose_name = "Prospetto dei cambiamenti"
        verbose_name_plural = "Prospetti dei cambiamenti"

    def __str__(self) -> str:
        return self.nome


class ProspettoModifica(models.Model):
    """Una riga del prospetto. Gli id restano numeri: un soggetto sparito si segnala, non cancella la riga."""

    REPARTO_CENTRO = "REPARTO_CENTRO"
    PERSONA_REPARTO = "PERSONA_REPARTO"
    PERSONA_RUOLO = "PERSONA_RUOLO"
    PERSONA_MANSIONE = "PERSONA_MANSIONE"
    MANSIONE_REPARTO = "MANSIONE_REPARTO"
    TIPO_CHOICES = [
        (REPARTO_CENTRO, "Reparto in un altro centro di costo"),
        (PERSONA_REPARTO, "Persona in un altro reparto"),
        (PERSONA_RUOLO, "Ruolo di una persona"),
        (PERSONA_MANSIONE, "Persona su una mansione"),
        (MANSIONE_REPARTO, "Mansione in un altro reparto"),
    ]
    LASCIA, TIENE = "lascia", "tiene"
    ENTRA, TOGLI = "entra", "togli"

    prospetto = models.ForeignKey(ProspettoStruttura, on_delete=models.CASCADE, related_name="modifiche")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    soggetto_id = models.IntegerField(help_text="Area, persona (id legacy) o mansione, secondo il tipo.")
    destinazione_id = models.IntegerField(null=True, blank=True, help_text="Centro, area, ruolo o mansione; vuoto = nessun centro.")
    modo = models.CharField(max_length=20, blank=True, default="")
    livello = models.CharField(max_length=1, blank=True, default="")
    esito = models.CharField(max_length=500, blank=True, default="")
    esito_ok = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = "Modifica del prospetto"
        verbose_name_plural = "Modifiche del prospetto"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} #{self.soggetto_id}"
