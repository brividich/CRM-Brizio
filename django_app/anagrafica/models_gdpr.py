"""Richieste di rettifica dei propri dati (GDPR art. 16, checklist E3 del 21/10/2026).

Il dipendente segnala da «La mia scheda» un dato sbagliato; HR la gestisce in
Impostazioni → «Richieste di rettifica» e la chiude con una risposta, che arriva
al dipendente come notifica. Il termine di risposta (art. 12.3) e' un mese.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

__all__ = ["RichiestaRettifica"]

GIORNI_RISPOSTA = 30


class RichiestaRettifica(models.Model):
    AMBITO_CHOICES = [
        ("ANAGRAFICA", "Dati anagrafici e recapiti"),
        ("RAPPORTO", "Rapporto di lavoro (reparto, mansione, contratto)"),
        ("FERIE", "Ferie, permessi e ratei"),
        ("CEDOLINO", "Voci del cedolino"),
        ("VISITE", "Visite mediche e idoneità"),
        ("FORMAZIONE", "Formazione e attestati"),
        ("DPI", "DPI"),
        ("ALTRO", "Altro"),
    ]
    STATO_APERTA = "APERTA"
    STATO_CHIUSA = "CHIUSA"
    STATO_CHOICES = [(STATO_APERTA, "Aperta"), (STATO_CHIUSA, "Chiusa")]

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="richieste_rettifica")
    ambito = models.CharField(max_length=20, choices=AMBITO_CHOICES, default="ALTRO")
    testo = models.TextField(help_text="Quale dato è sbagliato e come dovrebbe essere.")
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_APERTA, db_index=True)
    risposta = models.TextField(blank=True, default="")
    creata_il = models.DateTimeField(auto_now_add=True, db_index=True)
    gestita_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    gestita_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creata_il"]
        verbose_name = "Richiesta di rettifica"
        verbose_name_plural = "Richieste di rettifica"

    def __str__(self) -> str:
        return f"Rettifica #{self.pk} ({self.get_ambito_display()})"

    @property
    def scadenza(self):
        return (self.creata_il or timezone.now()) + timedelta(days=GIORNI_RISPOSTA)

    @property
    def in_ritardo(self) -> bool:
        return self.stato == self.STATO_APERTA and timezone.now() > self.scadenza
