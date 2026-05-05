from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone


# ---------------------------------------------------------------------------
# Categorie DPI (configurabili con immagine)
# ---------------------------------------------------------------------------

class CategoriaDPI(models.Model):
    nome = models.CharField(max_length=100)
    descrizione = models.TextField(blank=True, default="")
    immagine = models.ImageField(upload_to="dpi/categorie/", null=True, blank=True)
    icona_emoji = models.CharField(max_length=10, blank=True, default="🦺")
    vita_utile_giorni = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Vita utile stimata in giorni (per calcolo scadenza automatica alla consegna)",
    )
    unita_misura = models.CharField(max_length=30, blank=True, default="pz")
    scorta_minima = models.PositiveIntegerField(default=0, help_text="Soglia minima in magazzino per segnalazione")
    is_active = models.BooleanField(default=True)
    order_index = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_index", "nome"]
        verbose_name = "Categoria DPI"
        verbose_name_plural = "Categorie DPI"

    def __str__(self) -> str:
        return self.nome

    @property
    def immagine_url(self) -> str:
        if self.immagine:
            return self.immagine.url
        return ""


# ---------------------------------------------------------------------------
# Tipo DPI
# ---------------------------------------------------------------------------

class TipoDPI(models.Model):
    categoria = models.ForeignKey(
        CategoriaDPI,
        on_delete=models.CASCADE,
        related_name="tipi",
    )
    nome = models.CharField(max_length=100)
    descrizione = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    ordine = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria__order_index", "categoria__nome", "ordine", "nome"]
        verbose_name = "Tipo DPI"
        verbose_name_plural = "Tipi DPI"
        constraints = [
            models.UniqueConstraint(
                fields=["categoria", "nome"],
                name="uniq_tipo_dpi_categoria_nome",
            )
        ]

    def __str__(self) -> str:
        return f"{self.categoria.nome} - {self.nome}"


# ---------------------------------------------------------------------------
# Modello DPI
# ---------------------------------------------------------------------------

class ModelloDPI(models.Model):
    tipo = models.ForeignKey(
        TipoDPI,
        on_delete=models.CASCADE,
        related_name="modelli",
    )
    codice = models.CharField(max_length=50, unique=True)
    nome = models.CharField(max_length=150)
    produttore = models.CharField(max_length=150, blank=True, default="")
    descrizione = models.TextField(blank=True, default="")
    immagine = models.ImageField(upload_to="dpi/modelli/", null=True, blank=True)
    vita_utile_giorni = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Override della vita utile della categoria (se vuoto usa quella della categoria)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tipo__categoria__order_index", "tipo__ordine", "codice", "nome"]
        verbose_name = "Modello DPI"
        verbose_name_plural = "Modelli DPI"

    def __str__(self) -> str:
        return f"{self.codice} - {self.nome}"

    @property
    def immagine_url(self) -> str:
        if self.immagine:
            return self.immagine.url
        return ""

    @property
    def effective_vita_utile_giorni(self) -> int | None:
        return self.vita_utile_giorni or self.tipo.categoria.vita_utile_giorni


# ---------------------------------------------------------------------------
# Taglia DPI
# ---------------------------------------------------------------------------

class TagliaDPI(models.Model):
    modello = models.ForeignKey(
        ModelloDPI,
        on_delete=models.CASCADE,
        related_name="taglie",
    )
    valore = models.CharField(max_length=50)
    ordine = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["modello__tipo__categoria__order_index", "modello__tipo__ordine", "ordine", "valore"]
        verbose_name = "Taglia DPI"
        verbose_name_plural = "Taglie DPI"
        constraints = [
            models.UniqueConstraint(
                fields=["modello", "valore"],
                name="uniq_taglia_dpi_modello_valore",
            )
        ]

    def __str__(self) -> str:
        return f"{self.modello.codice} - {self.valore}"


# ---------------------------------------------------------------------------
# Impostazioni modulo (singleton)
# ---------------------------------------------------------------------------

class DPIImpostazioni(models.Model):
    responsabile_nome = models.CharField(max_length=200, blank=True, default="")
    responsabile_email = models.EmailField(blank=True, default="")
    responsabili = models.JSONField(blank=True, default=list)
    note_generali = models.TextField(blank=True, default="")
    notifica_nuova_richiesta = models.BooleanField(
        default=False, help_text="Invia email al responsabile per ogni nuova richiesta"
    )
    notifica_email_extra = models.TextField(
        blank=True, default="",
        help_text="Indirizzi email aggiuntivi per notifiche, uno per riga",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Impostazioni DPI"
        verbose_name_plural = "Impostazioni DPI"
        constraints = [
            models.CheckConstraint(check=models.Q(pk=1), name="dpiimpostazioni_singleton"),
        ]

    def __str__(self) -> str:
        return "Impostazioni DPI"

    @classmethod
    def get_singleton(cls) -> "DPIImpostazioni":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ---------------------------------------------------------------------------
# Richiesta DPI
# ---------------------------------------------------------------------------

class StatoRichiesta(models.TextChoices):
    INVIATA = "INVIATA", "Inviata"
    APPROVATA = "APPROVATA", "Approvata"
    CONSEGNATA = "CONSEGNATA", "Consegnata"
    RIFIUTATA = "RIFIUTATA", "Rifiutata"
    ANNULLATA = "ANNULLATA", "Annullata"


def _next_numero_dpi(year: int | None = None) -> str:
    if year is None:
        year = datetime.now(dt_timezone.utc).year
    prefix = f"DPI-{year}-"
    last = (
        RichiestaDPI.objects.filter(numero__startswith=prefix)
        .order_by("-numero")
        .values_list("numero", flat=True)
        .first()
    )
    if last:
        try:
            seq = int(last.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


class RichiestaDPI(models.Model):
    numero = models.CharField(max_length=30, unique=True, editable=False)
    categoria = models.ForeignKey(
        CategoriaDPI,
        on_delete=models.PROTECT,
        related_name="richieste",
    )
    tipo_dpi = models.ForeignKey(
        TipoDPI,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="richieste",
        help_text="Tipo DPI (opzionale, per selezione più specifica)",
    )
    modello_dpi = models.ForeignKey(
        ModelloDPI,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="richieste",
        help_text="Modello DPI (opzionale, per selezione più specifica)",
    )
    taglia_dpi = models.ForeignKey(
        TagliaDPI,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="richieste",
        help_text="Taglia DPI (opzionale, per selezione più specifica)",
    )
    quantita = models.PositiveIntegerField(default=1)
    motivazione = models.TextField(blank=True, default="")
    stato = models.CharField(
        max_length=15,
        choices=StatoRichiesta.choices,
        default=StatoRichiesta.INVIATA,
        db_index=True,
    )

    # Richiedente (denormalizzato per robustezza)
    richiedente_legacy_id = models.IntegerField(null=True, blank=True, db_index=True)
    richiedente_nome = models.CharField(max_length=200)
    richiedente_email = models.CharField(max_length=200, blank=True, default="")
    richiedente_reparto = models.CharField(max_length=100, blank=True, default="")

    note_gestione = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dpi_richieste_create",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Richiesta DPI"
        verbose_name_plural = "Richieste DPI"

    def save(self, *args, **kwargs):
        if self.numero:
            return super().save(*args, **kwargs)
        max_attempts = 5
        for attempt in range(max_attempts):
            self.numero = _next_numero_dpi()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.numero = ""
                if not self._state.adding or attempt == max_attempts - 1:
                    raise

    def __str__(self) -> str:
        return f"[{self.numero}] {self.richiedente_nome} — {self.categoria}"

    @property
    def label_stato(self) -> str:
        return dict(StatoRichiesta.choices).get(self.stato, self.stato)

    @property
    def is_aperta(self) -> bool:
        return self.stato in (StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA)

    @property
    def is_chiusa(self) -> bool:
        return self.stato in (StatoRichiesta.CONSEGNATA, StatoRichiesta.RIFIUTATA, StatoRichiesta.ANNULLATA)

    @property
    def is_scaduta(self) -> bool:
        """True se la consegna è scaduta (vita utile superata)."""
        try:
            if self.stato == StatoRichiesta.CONSEGNATA and hasattr(self, "consegna"):
                sc = self.consegna.data_scadenza_stimata
                if sc:
                    return sc < timezone.localdate()
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Consegna DPI (registrata al momento della consegna)
# ---------------------------------------------------------------------------

class ConsegnaDPI(models.Model):
    richiesta = models.OneToOneField(
        RichiestaDPI,
        on_delete=models.CASCADE,
        related_name="consegna",
    )
    data_consegna = models.DateField()
    consegnato_da_nome = models.CharField(max_length=200, blank=True, default="")
    note_consegna = models.TextField(blank=True, default="")
    firmato_ricevuta = models.BooleanField(default=False)
    data_scadenza_stimata = models.DateField(
        null=True, blank=True,
        help_text="Scadenza stimata per rinnovo (calcolata automaticamente da vita utile categoria)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Consegna DPI"
        verbose_name_plural = "Consegne DPI"

    def __str__(self) -> str:
        return f"Consegna {self.richiesta.numero} — {self.data_consegna}"


# ---------------------------------------------------------------------------
# Commenti / note sulla richiesta
# ---------------------------------------------------------------------------

class RichiestaDPICommento(models.Model):
    richiesta = models.ForeignKey(
        RichiestaDPI,
        on_delete=models.CASCADE,
        related_name="commenti",
    )
    autore_nome = models.CharField(max_length=200)
    testo = models.TextField()
    is_interno = models.BooleanField(default=False, help_text="Nota interna (non visibile al richiedente)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Commento richiesta DPI"
        verbose_name_plural = "Commenti richieste DPI"

    def __str__(self) -> str:
        return f"Commento su {self.richiesta.numero}"
