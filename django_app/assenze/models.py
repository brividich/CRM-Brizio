from __future__ import annotations

from django.db import models


class CertificazionePresenza(models.Model):
    """Registro presenze giornaliero — mattina obbligatoria, pomeriggio opzionale."""

    nome_dipendente = models.CharField(max_length=200)
    data            = models.DateField()

    # Turno mattina
    entrata_mattina = models.TimeField()
    uscita_mattina  = models.TimeField()

    # Turno pomeriggio (opzionale)
    turno_pomeriggio   = models.BooleanField(default=False)
    entrata_pomeriggio = models.TimeField(null=True, blank=True)
    uscita_pomeriggio  = models.TimeField(null=True, blank=True)

    note = models.TextField(blank=True, default="")

    # Approvazione
    CONSENSO_CHOICES = [
        ("In attesa",  "In attesa"),
        ("Approvato",  "Approvato"),
        ("Rifiutato",  "Rifiutato"),
    ]
    consenso           = models.CharField(max_length=20, choices=CONSENSO_CHOICES, default="In attesa")
    capo_reparto_email = models.CharField(max_length=200, blank=True, default="")
    salta_approvazione = models.BooleanField(default=False)

    # Origine: "utente" = da richiesta assenze, "admin" = inserimento diretto
    ORIGINE_CHOICES = [("utente", "Utente"), ("admin", "Admin")]
    origine = models.CharField(max_length=10, choices=ORIGINE_CHOICES, default="admin")

    # Collegamento alla riga in tabella assenze (se arrivato via richiesta utente)
    assenza_id = models.IntegerField(null=True, blank=True)

    inserito_da = models.CharField(max_length=200, blank=True, default="")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # Sync SharePoint lista "Certificazione presenza"
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-data", "nome_dipendente"]
        verbose_name = "Certificazione presenza"
        verbose_name_plural = "Certificazioni presenza"

    def __str__(self):
        return f"{self.nome_dipendente} — {self.data}"

    @property
    def ore_mattina(self):
        if self.entrata_mattina and self.uscita_mattina:
            delta = (
                self.uscita_mattina.hour * 60 + self.uscita_mattina.minute
                - self.entrata_mattina.hour * 60 - self.entrata_mattina.minute
            )
            return round(delta / 60, 2) if delta > 0 else 0
        return None

    @property
    def ore_pomeriggio(self):
        if self.turno_pomeriggio and self.entrata_pomeriggio and self.uscita_pomeriggio:
            delta = (
                self.uscita_pomeriggio.hour * 60 + self.uscita_pomeriggio.minute
                - self.entrata_pomeriggio.hour * 60 - self.entrata_pomeriggio.minute
            )
            return round(delta / 60, 2) if delta > 0 else 0
        return None

    @property
    def ore_totali(self):
        return round((self.ore_mattina or 0) + (self.ore_pomeriggio or 0), 2)
