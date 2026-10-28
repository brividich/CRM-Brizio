from django.db import models
from django.utils import timezone

from core.private_attachments import PrivateAttachmentStorage


class RegistroRifiutiQuerySet(models.QuerySet):
    def attivi(self):
        """Movimenti validi: gli annullati restano a registro ma non contano."""
        return self.filter(annullato=False)


class RegistroRifiuti(models.Model):
    UNITA_CHOICES = [
        ("kg", "kg"),
        ("t", "t"),
        ("l", "litri"),
        ("m3", "m³"),
    ]
    ORIGINE_CHOICES = [
        ("portale", "Portale"),
        ("import", "Import CSV"),
        ("sharepoint", "SharePoint"),
        ("storico", "Storico"),
    ]
    TIPO_CHOICES = [
        ("C", "C - Carico"),
        ("O", "O - Scarico originale"),
        ("M", "M - Scarico effettivo"),
        ("R", "R - Rettifica scarico"),
    ]

    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES, db_index=True)
    data = models.DateField(db_index=True)
    id_registrazione = models.CharField(max_length=50, blank=True, default="", db_index=True)
    rif_op = models.CharField(max_length=200, blank=True, default="")
    codice = models.CharField(max_length=100, blank=True, default="")
    quantita = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    carico_scarico = models.CharField(max_length=10, blank=True, default="")
    rentri_si_no = models.BooleanField(default=False)
    salva = models.BooleanField(default=False)
    note_rentri = models.TextField(blank=True, default="")
    # Solo per tipo=C
    pericolosita = models.CharField(max_length=100, blank=True, default="")
    # Solo per tipo=M e tipo=R
    rettifica_scarico = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    arrivo_fir = models.CharField(max_length=200, blank=True, default="")
    aggiornato = models.DateTimeField(null=True, blank=True)
    # Solo per tipo=C
    # Storage privato (formulari rifiuti): mai serviti da /media/.
    allegato = models.FileField(
        upload_to="rentri/allegati/",
        storage=PrivateAttachmentStorage(download_hint="Allegato RENTRI: non esposto via URL."),
        null=True,
        blank=True,
    )
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")
    inserito_da = models.CharField(max_length=200, blank=True, default="")
    # Unità della quantità: vuota sui movimenti storici (non dichiarata).
    unita = models.CharField(max_length=3, choices=UNITA_CHOICES, blank=True, default="")
    # Da dove arriva il movimento: i termini di annotazione si controllano solo
    # su quelli scritti dal portale (gli altri hanno created_at = data di import).
    origine = models.CharField(max_length=12, choices=ORIGINE_CHOICES, default="portale")
    # Consolidamento: dopo, i dati non si modificano più (si corregge con R o annullando).
    consolidato_il = models.DateTimeField(null=True, blank=True)
    consolidato_da = models.CharField(max_length=200, blank=True, default="")
    # Annullamento: il movimento resta a registro, barrato, e non conta più.
    annullato = models.BooleanField(default=False, db_index=True)
    annullato_il = models.DateTimeField(null=True, blank=True)
    annullato_da = models.CharField(max_length=200, blank=True, default="")
    motivo_annullamento = models.TextField(blank=True, default="")
    # Ultimo errore di invio a SharePoint (vuoto = allineato o non configurato).
    sync_errore = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RegistroRifiutiQuerySet.as_manager()

    class Meta:
        ordering = ["-data", "-id"]
        verbose_name = "Registro Rifiuti"
        verbose_name_plural = "Registri Rifiuti"

    def __str__(self):
        return f"{self.tipo} | {self.id_registrazione or '—'} | {self.data}"

    def save(self, *args, **kwargs):
        if not self.id_registrazione:
            from .numerazione import alloca_id_registrazione

            anno = self.data.year if self.data else timezone.now().year
            self.id_registrazione = alloca_id_registrazione(anno)
        super().save(*args, **kwargs)

    @property
    def bloccato(self) -> bool:
        """Consolidato o annullato: i dati non si toccano più."""
        return bool(self.salva or self.annullato)


class RentriRegistroCounter(models.Model):
    """Progressivo annuale del registro: il numero si **alloca**, non si conta.

    Una riga per anno; ``ultimo`` è l'ultimo progressivo assegnato. Fino al
    2026-09 il numero nasceva da ``COUNT(*)`` dei movimenti dell'anno: dopo
    un'eliminazione il conteggio arretrava e il numero successivo **ripeteva**
    uno già stampato su un'altra riga (64 id duplicati in produzione). Il
    conteggio non è una sequenza — questo contatore lo è.

    L'allocazione avviene in transazione con ``select_for_update``
    (:func:`rentri.numerazione.alloca_id_registrazione`), così due salvataggi
    simultanei non si contendono lo stesso numero. Stessa forma di
    ``anagrafica.TrainingCourseCodeCounter``.
    """

    anno = models.PositiveSmallIntegerField(unique=True, db_index=True)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Progressivo registro Rentri"
        verbose_name_plural = "Progressivi registro Rentri"

    def __str__(self) -> str:
        return f"{self.anno}: {self.ultimo}"


class RentriImpostazioni(models.Model):
    """Singleton: impostazioni del modulo Rentri (tracciabilità rifiuti)."""

    codice_iscrizione_rentri = models.CharField(
        max_length=50, blank=True, default="",
        verbose_name="Codice iscrizione RENTRI",
        help_text="Codice rilasciato dal sistema RENTRI all'atto dell'iscrizione.",
    )
    ragione_sociale = models.CharField(
        max_length=200, blank=True, default="",
        verbose_name="Ragione sociale",
    )
    responsabile_nome = models.CharField(
        max_length=200, blank=True, default="",
        verbose_name="Responsabile",
    )
    responsabile_email = models.EmailField(
        blank=True, default="",
        verbose_name="Email responsabile",
    )
    responsabili = models.JSONField(blank=True, default=list, verbose_name="Referenti")
    note_generali = models.TextField(blank=True, default="", verbose_name="Note operative")

    class Meta:
        verbose_name = "Impostazioni Rentri"
        verbose_name_plural = "Impostazioni Rentri"
        constraints = [
            models.CheckConstraint(check=models.Q(pk=1), name="rentriimpostazioni_singleton"),
        ]

    def __str__(self) -> str:
        return "Impostazioni Rentri"

    @classmethod
    def get_singleton(cls) -> "RentriImpostazioni":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
