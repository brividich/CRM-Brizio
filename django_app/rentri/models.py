from django.db import models
from django.utils import timezone


class RegistroRifiuti(models.Model):
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
    allegato = models.FileField(upload_to="rentri/allegati/", null=True, blank=True)
    sharepoint_item_id = models.CharField(max_length=64, blank=True, default="")
    inserito_da = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data", "-id"]
        verbose_name = "Registro Rifiuti"
        verbose_name_plural = "Registri Rifiuti"

    def __str__(self):
        return f"{self.tipo} | {self.id_registrazione or '—'} | {self.data}"

    def save(self, *args, **kwargs):
        if not self.id_registrazione:
            year = self.data.year if self.data else timezone.now().year
            count = RegistroRifiuti.objects.filter(data__year=year).count()
            self.id_registrazione = f"{year}/{count + 1:03d}"
        super().save(*args, **kwargs)


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
