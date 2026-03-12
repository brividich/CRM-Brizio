from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Fornitori
# ---------------------------------------------------------------------------

class Fornitore(models.Model):
    CATEGORIA_MATERIALI = "MATERIALI"
    CATEGORIA_SERVIZI = "SERVIZI"
    CATEGORIA_ATTREZZATURE = "ATTREZZATURE"
    CATEGORIA_LOGISTICA = "LOGISTICA"
    CATEGORIA_IT = "IT"
    CATEGORIA_MANUTENZIONE = "MANUTENZIONE"
    CATEGORIA_ALTRO = "ALTRO"

    CATEGORIA_CHOICES = [
        (CATEGORIA_MATERIALI, "Materiali"),
        (CATEGORIA_SERVIZI, "Servizi"),
        (CATEGORIA_ATTREZZATURE, "Attrezzature"),
        (CATEGORIA_LOGISTICA, "Logistica"),
        (CATEGORIA_IT, "IT / Informatica"),
        (CATEGORIA_MANUTENZIONE, "Manutenzione"),
        (CATEGORIA_ALTRO, "Altro"),
    ]

    ragione_sociale = models.CharField(max_length=200)
    piva = models.CharField(max_length=11, blank=True, default="", verbose_name="P.IVA")
    codice_fiscale = models.CharField(max_length=16, blank=True, default="")
    indirizzo = models.CharField(max_length=255, blank=True, default="")
    citta = models.CharField(max_length=100, blank=True, default="", verbose_name="Citta")
    cap = models.CharField(max_length=5, blank=True, default="", verbose_name="CAP")
    provincia = models.CharField(max_length=2, blank=True, default="")
    telefono = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    pec = models.EmailField(blank=True, default="", verbose_name="PEC")
    website = models.URLField(blank=True, default="")
    categoria = models.CharField(
        max_length=20,
        choices=CATEGORIA_CHOICES,
        blank=True,
        default="",
    )
    is_active = models.BooleanField(default=True, verbose_name="Attivo")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ragione_sociale", "id"]
        verbose_name = "Fornitore"
        verbose_name_plural = "Fornitori"

    def __str__(self) -> str:
        return self.ragione_sociale

    @property
    def punteggio_medio(self) -> float | None:
        vals = list(
            self.valutazioni.values_list("qualita", "puntualita", "comunicazione")
        )
        if not vals:
            return None
        total = sum((q + p + c) / 3 for q, p, c in vals)
        return round(total / len(vals), 1)

    @property
    def spesa_totale(self) -> Decimal:
        from django.db.models import Sum
        result = self.ordini.aggregate(t=Sum("importo"))["t"]
        return result or Decimal("0")


# ---------------------------------------------------------------------------
# Documenti allegati al fornitore
# ---------------------------------------------------------------------------

def _fornitore_documento_upload_to(instance, filename: str) -> str:
    fornitore_id = instance.fornitore_id or "tmp"
    suffix = Path(filename or "").suffix.lower()[:20]
    stem = Path(filename or "").stem[:80] or "documento"
    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"anagrafica/fornitori/{fornitore_id}/{stamp}_{stem}{suffix}"


class FornitoreDocumento(models.Model):
    TIPO_CONTRATTO = "CONTRATTO"
    TIPO_OFFERTA = "OFFERTA"
    TIPO_CERTIFICAZIONE = "CERTIFICAZIONE"
    TIPO_VISURA = "VISURA"
    TIPO_ALTRO = "ALTRO"

    TIPO_CHOICES = [
        (TIPO_CONTRATTO, "Contratto"),
        (TIPO_OFFERTA, "Offerta"),
        (TIPO_CERTIFICAZIONE, "Certificazione"),
        (TIPO_VISURA, "Visura camerale"),
        (TIPO_ALTRO, "Altro"),
    ]

    fornitore = models.ForeignKey(Fornitore, on_delete=models.CASCADE, related_name="documenti")
    nome = models.CharField(max_length=200)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_ALTRO)
    file = models.FileField(upload_to=_fornitore_documento_upload_to)
    note = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fornitore_documenti_caricati",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        verbose_name = "Documento fornitore"
        verbose_name_plural = "Documenti fornitore"

    def __str__(self) -> str:
        return f"{self.nome} ({self.get_tipo_display()})"

    def delete(self, *args, **kwargs):
        storage = self.file.storage if self.file else None
        file_name = self.file.name if self.file else ""
        super().delete(*args, **kwargs)
        if storage and file_name and storage.exists(file_name):
            storage.delete(file_name)


# ---------------------------------------------------------------------------
# Ordini / acquisti collegati al fornitore
# ---------------------------------------------------------------------------

class FornitoreOrdine(models.Model):
    STATO_BOZZA = "BOZZA"
    STATO_INVIATO = "INVIATO"
    STATO_CONFERMATO = "CONFERMATO"
    STATO_CONSEGNATO = "CONSEGNATO"
    STATO_ANNULLATO = "ANNULLATO"

    STATO_CHOICES = [
        (STATO_BOZZA, "Bozza"),
        (STATO_INVIATO, "Inviato"),
        (STATO_CONFERMATO, "Confermato"),
        (STATO_CONSEGNATO, "Consegnato"),
        (STATO_ANNULLATO, "Annullato"),
    ]

    fornitore = models.ForeignKey(Fornitore, on_delete=models.CASCADE, related_name="ordini")
    numero_ordine = models.CharField(max_length=50, blank=True, default="")
    data_ordine = models.DateField()
    importo = models.DecimalField(max_digits=12, decimal_places=2)
    descrizione = models.TextField(blank=True, default="")
    stato = models.CharField(max_length=20, choices=STATO_CHOICES, default=STATO_BOZZA)
    note = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fornitore_ordini_creati",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_ordine", "-id"]
        verbose_name = "Ordine fornitore"
        verbose_name_plural = "Ordini fornitore"

    def __str__(self) -> str:
        num = self.numero_ordine or f"#{self.pk}"
        return f"Ordine {num} — {self.fornitore}"


# ---------------------------------------------------------------------------
# Valutazioni fornitore
# ---------------------------------------------------------------------------

class FornitoreValutazione(models.Model):
    fornitore = models.ForeignKey(Fornitore, on_delete=models.CASCADE, related_name="valutazioni")
    data = models.DateField(default=timezone.now)
    qualita = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name="Qualita",
    )
    puntualita = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name="Puntualita",
    )
    comunicazione = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    note = models.TextField(blank=True, default="")
    valutato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fornitore_valutazioni",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]
        verbose_name = "Valutazione fornitore"
        verbose_name_plural = "Valutazioni fornitore"

    def __str__(self) -> str:
        return f"Valutazione {self.fornitore} — {self.data}"

    @property
    def media(self) -> float:
        return round((self.qualita + self.puntualita + self.comunicazione) / 3, 1)


# ---------------------------------------------------------------------------
# Asset assegnati al fornitore (per manutenzione/assistenza)
# ---------------------------------------------------------------------------

class FornitoreAsset(models.Model):
    TIPO_MANUTENZIONE = "MANUTENZIONE"
    TIPO_ASSISTENZA = "ASSISTENZA"
    TIPO_NOLEGGIO = "NOLEGGIO"
    TIPO_FORNITURA = "FORNITURA"

    TIPO_CHOICES = [
        (TIPO_MANUTENZIONE, "Manutenzione"),
        (TIPO_ASSISTENZA, "Assistenza tecnica"),
        (TIPO_NOLEGGIO, "Noleggio"),
        (TIPO_FORNITURA, "Fornitura"),
    ]

    fornitore = models.ForeignKey(Fornitore, on_delete=models.CASCADE, related_name="asset_assegnati")
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.CASCADE,
        related_name="fornitori_manutenzione",
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_MANUTENZIONE)
    data_inizio = models.DateField(default=timezone.now)
    data_fine = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fornitore_asset_assegnati",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_inizio", "-id"]
        verbose_name = "Asset fornitore"
        verbose_name_plural = "Asset fornitore"
        constraints = [
            models.UniqueConstraint(fields=["fornitore", "asset", "tipo"], name="uniq_fornitore_asset_tipo"),
        ]

    def __str__(self) -> str:
        return f"{self.asset} → {self.fornitore} ({self.get_tipo_display()})"

    @property
    def is_attivo(self) -> bool:
        if self.data_fine is None:
            return True
        return self.data_fine >= timezone.localdate()
