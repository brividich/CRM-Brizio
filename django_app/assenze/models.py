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


class AssenzaSharePointOutbox(models.Model):
    """Coda delle modifiche locali alle assenze ancora da inviare a SharePoint.

    Una riga per record della tabella legacy ``assenze``: le modifiche successive
    aggiornano la stessa riga e ne incrementano ``versione``. Il job periodico
    elimina la riga solo se la versione non e' cambiata durante l'invio, cosi' una
    modifica arrivata a meta' invio non va persa. Finche' la riga esiste, la
    lettura da SharePoint non sovrascrive il record locale.
    """

    AZIONE_UPSERT = "upsert"
    AZIONE_DELETE = "delete"
    AZIONE_CHOICES = [(AZIONE_UPSERT, "Crea/aggiorna"), (AZIONE_DELETE, "Elimina")]

    assenza_id = models.IntegerField(unique=True)
    azione = models.CharField(max_length=10, choices=AZIONE_CHOICES, default=AZIONE_UPSERT)
    # Valorizzato per le eliminazioni: il record locale non esiste piu'.
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")
    versione = models.PositiveIntegerField(default=1)
    tentativi = models.PositiveIntegerField(default=0)
    ultimo_errore = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assenza da inviare a SharePoint"
        verbose_name_plural = "Assenze da inviare a SharePoint"

    def __str__(self):
        return f"{self.azione} assenza {self.assenza_id} (v{self.versione})"


class AssenzaOrigineSharePoint(models.Model):
    """Dove e' nata una richiesta collegata alla lista SharePoint.

    Durante la convivenza con le vecchie app, la richiesta la gestisce il sistema
    in cui e' nata: ``creata_su_sharepoint=True`` significa approvata dal flusso
    Power Automate e in sola lettura sul portale. Scritta dalla sincronizzazione
    (lettura: da ``createdBy`` di Graph; invio: creata dal portale).
    """

    assenza_id = models.IntegerField(unique=True)
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")
    creata_su_sharepoint = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Origine assenza (SharePoint)"
        verbose_name_plural = "Origini assenze (SharePoint)"

    def __str__(self):
        luogo = "SharePoint" if self.creata_su_sharepoint else "portale"
        return f"assenza {self.assenza_id} nata su {luogo}"
