from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .storage import PrivateAnagraficaStorage


def _add_months(d: date, months: int) -> date:
    """Aggiunge ``months`` mesi calendariali a ``d``, mantenendo il giorno
    quando possibile (lo clampa al fine mese se il mese di destinazione è
    più corto). Indipendente da python-dateutil.
    """
    if months <= 0:
        return d
    month_index = (d.month - 1) + int(months)
    year = d.year + (month_index // 12)
    month = (month_index % 12) + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day_of_month)
    return date(year, month, day)


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


def _dipendente_foto_upload_to(instance, filename: str) -> str:
    legacy_id = instance.legacy_anagrafica_id or "tmp"
    suffix = Path(filename or "").suffix.lower()[:12] or ".jpg"
    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"anagrafica/dipendenti/{legacy_id}/foto/{stamp}{suffix}"


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


# ---------------------------------------------------------------------------
# Ruoli operativi aziendali (preposto, RSPP, squadra antincendio, ecc.)
# ---------------------------------------------------------------------------

class RuoloOperativo(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descrizione = models.TextField(blank=True, default="")
    colore = models.CharField(max_length=7, default="#64748b", help_text="Colore esadecimale es. #1d4ed8")
    icona = models.CharField(max_length=10, blank=True, default="", help_text="Emoji o testo breve")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Ruolo Operativo"
        verbose_name_plural = "Ruoli Operativi"

    def __str__(self) -> str:
        return self.nome


class DipendenteRuoloOperativo(models.Model):
    """Assegnazione di un ruolo operativo a un dipendente (via ID legacy anagrafica)."""
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    ruolo = models.ForeignKey(RuoloOperativo, on_delete=models.CASCADE, related_name="assegnazioni")
    assegnato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ruoli_operativi_assegnati",
    )
    assegnato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("legacy_anagrafica_id", "ruolo")]
        verbose_name = "Ruolo operativo dipendente"
        verbose_name_plural = "Ruoli operativi dipendenti"

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] → {self.ruolo.nome}"


# ---------------------------------------------------------------------------
# Layout widget statistiche scheda dipendente (personalizzabile per utente)
# ---------------------------------------------------------------------------

class DipendenteStatLayout(models.Model):
    """Layout e visibilità widget statistiche nella scheda dipendente, per utente loggato."""
    viewer_user_id = models.IntegerField(unique=True, db_index=True)
    hidden = models.JSONField(default=list, blank=True, help_text="Lista widget_id nascosti")
    order = models.JSONField(default=list, blank=True, help_text="Ordine dei widget_id")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Layout widget statistiche dipendente"
        verbose_name_plural = "Layout widget statistiche dipendente"


# ---------------------------------------------------------------------------
# Impostazioni permessi sezione statistiche anagrafica (singleton)
# ---------------------------------------------------------------------------

class AnagraficaStatPermission(models.Model):
    """Singleton: chi può vedere la sezione statistiche nella scheda dipendente."""
    ACCESSO_TUTTI = "TUTTI"
    ACCESSO_ADMIN = "ADMIN"
    ACCESSO_RUOLI = "RUOLI"

    ACCESSO_CHOICES = [
        (ACCESSO_TUTTI, "Tutti gli utenti autenticati"),
        (ACCESSO_ADMIN, "Solo amministratori"),
        (ACCESSO_RUOLI, "Ruoli ACL specifici"),
    ]

    accesso = models.CharField(max_length=20, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    ruolo_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista ruolo_id ACL legacy abilitati (usato solo se accesso=RUOLI)",
    )

    class Meta:
        verbose_name = "Permessi statistiche anagrafica"
        verbose_name_plural = "Permessi statistiche anagrafica"

    def __str__(self) -> str:
        return f"Permessi statistiche ({self.get_accesso_display()})"

    @classmethod
    def get_instance(cls) -> "AnagraficaStatPermission":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"accesso": cls.ACCESSO_ADMIN})
        return obj


# ---------------------------------------------------------------------------
# Mansioni aziendali (catalogo job title — sincronizza con campo legacy)
# ---------------------------------------------------------------------------

class Mansione(models.Model):
    CAT_OPERAIO = "OPERAIO"
    CAT_IMPIEGATO = "IMPIEGATO"
    CAT_QUADRO = "QUADRO"
    CAT_DIRIGENTE = "DIRIGENTE"
    CAT_ALTRO = "ALTRO"

    CATEGORIA_CHOICES = [
        (CAT_OPERAIO, "Operaio"),
        (CAT_IMPIEGATO, "Impiegato"),
        (CAT_QUADRO, "Quadro"),
        (CAT_DIRIGENTE, "Dirigente"),
        (CAT_ALTRO, "Altro"),
    ]

    # Livello di rischio (Accordo Stato-Regioni): determina le ore della
    # formazione generale/specifica lavoratori e il rinnovo quinquennale.
    RISCHIO_BASSO = "B"
    RISCHIO_MEDIO = "M"
    RISCHIO_ALTO  = "A"
    LIVELLO_RISCHIO_CHOICES = [
        (RISCHIO_BASSO, "Basso (8h)"),
        (RISCHIO_MEDIO, "Medio (12h)"),
        (RISCHIO_ALTO,  "Alto (16h)"),
    ]
    ORE_PER_LIVELLO = {RISCHIO_BASSO: 8, RISCHIO_MEDIO: 12, RISCHIO_ALTO: 16}
    RINNOVO_FORMAZIONE_MESI = 60  # ASR: aggiornamento ogni 5 anni

    nome = models.CharField(max_length=100, unique=True)
    categoria = models.CharField(
        max_length=20, choices=CATEGORIA_CHOICES, blank=True, default=""
    )
    descrizione = models.TextField(blank=True, default="")
    colore = models.CharField(max_length=7, default="#64748b", help_text="Colore esadecimale es. #1d4ed8")
    livello_rischio = models.CharField(
        max_length=1, choices=LIVELLO_RISCHIO_CHOICES, blank=True, default="",
        help_text="Livello di rischio mansione (ASR): B=basso 8h, M=medio 12h, A=alto 16h.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Profilo "mansione di rischio" (requisiti diretti) ─────────────────
    # Requisiti DPI / visite richiesti esplicitamente da questa mansione. Si
    # uniscono a quelli ereditati dai FattoreRischio collegati via
    # EsposizioneRischio. La formazione obbligatoria resta su
    # TrainingRequirementRule(mansione=...). Vedi services/mansionario.py.
    dpi_richiesti = models.ManyToManyField(
        "dpi.CategoriaDPI", blank=True, related_name="mansioni_richiedenti",
        help_text="Categorie DPI obbligatorie per questa mansione.",
    )
    visite_richieste = models.ManyToManyField(
        "anagrafica.TipoVisitaMedica", blank=True, related_name="mansioni_richiedenti",
        help_text="Tipologie di visita medica obbligatorie per questa mansione.",
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "Mansione"
        verbose_name_plural = "Mansioni"

    def __str__(self) -> str:
        return self.nome

    @property
    def ore_formazione_generale(self) -> int | None:
        """Ore di formazione generale/specifica lavoratori in base al rischio."""
        return self.ORE_PER_LIVELLO.get(self.livello_rischio)


# ---------------------------------------------------------------------------
# Qualifiche professionali (catalogo tipi + assegnazioni per dipendente)
# ---------------------------------------------------------------------------

class TipoQualifica(models.Model):
    CAT_SICUREZZA = "SICUREZZA"
    CAT_PROFESSIONALE = "PROFESSIONALE"
    CAT_GESTIONALE = "GESTIONALE"
    CAT_ALTRO = "ALTRO"

    CATEGORIA_CHOICES = [
        (CAT_SICUREZZA, "Sicurezza"),
        (CAT_PROFESSIONALE, "Professionale"),
        (CAT_GESTIONALE, "Gestionale"),
        (CAT_ALTRO, "Altro"),
    ]

    nome = models.CharField(max_length=150, unique=True)
    categoria = models.CharField(
        max_length=20, choices=CATEGORIA_CHOICES, default=CAT_ALTRO
    )
    durata_mesi = models.PositiveSmallIntegerField(
        default=0, help_text="Durata validità in mesi. 0 = nessuna scadenza automatica."
    )
    descrizione = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["categoria", "nome"]
        verbose_name = "Tipo qualifica"
        verbose_name_plural = "Tipi qualifica"

    def __str__(self) -> str:
        return self.nome


def _dipendente_qualifica_evidenza_upload_to(instance, filename: str) -> str:
    legacy_id = instance.legacy_anagrafica_id or "tmp"
    suffix = Path(filename or "").suffix.lower()[:20] or ".bin"
    stem = Path(filename or "").stem[:80] or "certificato"
    now = timezone.now()
    return (
        f"anagrafica/dipendenti/{legacy_id}/qualifiche/"
        f"{now.strftime('%Y%m')}/{now.strftime('%Y%m%d_%H%M%S')}_{stem}{suffix}"
    )


class DipendenteQualifica(models.Model):
    """Qualifica/certificazione assegnata a un dipendente (via ID legacy anagrafica)."""
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    tipo = models.ForeignKey(
        TipoQualifica, on_delete=models.CASCADE, related_name="assegnazioni"
    )
    data_conseguimento = models.DateField(null=True, blank=True)
    data_scadenza = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, default="")
    assegnato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qualifiche_assegnate",
    )
    # Sessione di rilascio/rinnovo collettivo (opzionale): traccia in quale
    # evento la qualifica è stata conseguita/rinnovata, come per i corsi.
    sessione = models.ForeignKey(
        "QualificaSessione",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qualifiche",
    )
    # Evidenza formativa (competency management): il completamento del corso da
    # cui deriva questa qualifica posseduta. Collega lo stato "competenza" alla
    # sua prova; le date possono esserne derivate. Null = inserita a mano/import.
    record_formazione = models.ForeignKey(
        "anagrafica.TrainingEmployeeRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qualifiche_collegate",
    )
    # ── Fase 2: estremi del certificato/abilitazione (competency management) ──
    numero = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Numero del certificato/patentino.",
    )
    livello = models.CharField(
        max_length=80, blank=True, default="",
        help_text="Livello/categoria (es. antincendio liv. 2).",
    )
    ente = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Ente/organismo che ha rilasciato l'abilitazione.",
    )
    # Evidenza documentale: storage privato fuori webroot, servita da view protetta.
    documento = models.FileField(
        upload_to=_dipendente_qualifica_evidenza_upload_to,
        storage=PrivateAnagraficaStorage(),
        null=True, blank=True,
        help_text="Scansione/PDF del certificato (evidenza).",
    )
    documento_nome_originale = models.CharField(max_length=255, blank=True, default="")
    # Verifica HR dell'evidenza caricata.
    verificata = models.BooleanField(default=False)
    verificata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="qualifiche_verificate",
    )
    verificata_il = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data_scadenza", "tipo__nome"]
        verbose_name = "Qualifica dipendente"
        verbose_name_plural = "Qualifiche dipendente"

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.tipo.nome}"

    @property
    def is_scaduta(self) -> bool:
        if self.data_scadenza is None:
            return False
        return self.data_scadenza < timezone.localdate()

    @property
    def in_scadenza(self) -> bool:
        """Scade entro 60 giorni e non è ancora scaduta."""
        if self.data_scadenza is None:
            return False
        from datetime import timedelta
        oggi = timezone.localdate()
        return oggi <= self.data_scadenza <= oggi + timedelta(days=60)


class QualificaSessione(models.Model):
    """Sessione di rilascio/rinnovo collettivo di una qualifica/abilitazione.

    Raggruppa il conferimento di una stessa ``TipoQualifica`` a più dipendenti
    nella stessa data (es. corso carrellisti svolto il 14/06 da un ente). Ogni
    partecipante genera/aggiorna una ``DipendenteQualifica`` collegata via FK.
    Pattern speculare a ``TrainingSession`` (corsi) ma leggero: niente lezioni.
    """
    tipo = models.ForeignKey(TipoQualifica, on_delete=models.PROTECT, related_name="sessioni")
    data_conseguimento = models.DateField()
    data_scadenza = models.DateField(
        null=True, blank=True,
        help_text="Scadenza comune; se vuota è calcolata da durata_mesi del tipo.",
    )
    ente = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Ente/provider che ha erogato o rilasciato l'abilitazione.",
    )
    # Se la sessione coincide con una sessione corso (un solo evento, non due),
    # il legame le tiene collegate: la sessione di rinnovo qualifica È l'edizione
    # del corso che la rilascia. Null = sessione qualifica autonoma.
    training_session = models.ForeignKey(
        "anagrafica.TrainingSession",
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sessioni_qualifica",
    )
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_conseguimento", "-id"]
        verbose_name = "Sessione qualifica"
        verbose_name_plural = "Sessioni qualifica"

    def __str__(self) -> str:
        return f"{self.tipo.nome} — {self.data_conseguimento}"

    @property
    def scadenza_effettiva(self):
        """Scadenza esplicita oppure calcolata dal ``durata_mesi`` del tipo."""
        if self.data_scadenza:
            return self.data_scadenza
        if self.tipo_id and self.tipo.durata_mesi:
            return _add_months(self.data_conseguimento, self.tipo.durata_mesi)
        return None


# ---------------------------------------------------------------------------
# Aree aziendali (raggruppamento di alto livello: es. "Produzione", "Uffici")
# ---------------------------------------------------------------------------

class AreaAziendale(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descrizione = models.TextField(blank=True, default="")
    colore = models.CharField(max_length=7, default="#64748b", help_text="Colore esadecimale es. #1d4ed8")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "anagrafica_area_aziendale"
        ordering = ["nome"]
        verbose_name = "Area aziendale"
        verbose_name_plural = "Aree aziendali"

    def __str__(self) -> str:
        return self.nome


# ---------------------------------------------------------------------------
# Reparti (sotto-unità dell'area aziendale, con caporeparto)
# La tabella DB mantiene il nome storico ``anagrafica_areaaziendale`` per
# compatibilità con migrazioni esistenti.
# ---------------------------------------------------------------------------

class Reparto(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descrizione = models.TextField(blank=True, default="")
    area_aziendale = models.ForeignKey(
        AreaAziendale,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reparti",
        verbose_name="Area aziendale",
    )
    caporeparto_legacy_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Caporeparto",
        help_text="ID legacy del dipendente assegnato come caporeparto.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "anagrafica_areaaziendale"
        ordering = ["nome"]
        verbose_name = "Reparto"
        verbose_name_plural = "Reparti"

    def __str__(self) -> str:
        return self.nome


# ---------------------------------------------------------------------------
# Catalogo ruoli aziendali (dropdown per DipendenteAnagraficaAziendale.ruolo_aziendale)
# ---------------------------------------------------------------------------

class RuoloAziendale(models.Model):
    nome = models.CharField(max_length=200, unique=True)
    descrizione = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Ruolo aziendale"
        verbose_name_plural = "Ruoli aziendali"

    def __str__(self) -> str:
        return self.nome


# ---------------------------------------------------------------------------
# Anagrafica civile dipendente (dati personali/privati)
# ---------------------------------------------------------------------------

class DipendenteAnagraficaCivile(models.Model):
    GENERE_M = "M"
    GENERE_F = "F"
    GENERE_A = "A"
    GENERE_CHOICES = [
        (GENERE_M, "Maschile"),
        (GENERE_F, "Femminile"),
        (GENERE_A, "Non specificato"),
    ]

    TITOLO_PRIMO_GRADO = "PRIMO_GRADO"
    TITOLO_SECONDO_GRADO = "SECONDO_GRADO"
    TITOLO_LAUREA_TRIENNALE = "LAUREA_TRIENNALE"
    TITOLO_LAUREA_MAGISTRALE = "LAUREA_MAGISTRALE"
    TITOLO_LAUREA_CICLO_UNICO = "LAUREA_CICLO_UNICO"
    TITOLO_CHOICES = [
        (TITOLO_PRIMO_GRADO, "Istruzione primo grado"),
        (TITOLO_SECONDO_GRADO, "Istruzione secondo grado"),
        (TITOLO_LAUREA_TRIENNALE, "Laurea triennale"),
        (TITOLO_LAUREA_MAGISTRALE, "Laurea magistrale"),
        (TITOLO_LAUREA_CICLO_UNICO, "Laurea magistrale ciclo unico"),
    ]

    legacy_anagrafica_id = models.IntegerField(unique=True, db_index=True)
    foto = models.ImageField(
        upload_to=_dipendente_foto_upload_to,
        storage=PrivateAnagraficaStorage(),
        blank=True,
        default="",
        verbose_name="Foto dipendente",
        help_text=(
            "Dato personale: salvata in ANAGRAFICA_PRIVATE_ROOT (fuori webroot). "
            "Servita solo dalla view protetta anagrafica:foto_dipendente."
        ),
    )

    data_nascita = models.DateField(null=True, blank=True)
    luogo_nascita = models.CharField(max_length=200, blank=True, default="")
    provincia_nascita = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Provincia di nascita: accetta sia sigla (2 lettere) sia nome esteso.",
    )
    nazionalita = models.CharField(max_length=100, blank=True, default="", verbose_name="Nazionalità")
    genere = models.CharField(max_length=1, choices=GENERE_CHOICES, blank=True, default="")

    indirizzo_residenza = models.CharField(max_length=300, blank=True, default="")
    citta_residenza = models.CharField(max_length=100, blank=True, default="", verbose_name="Città residenza")
    provincia_residenza = models.CharField(max_length=5, blank=True, default="")
    nazione_residenza = models.CharField(max_length=100, blank=True, default="Italia")
    cap_residenza = models.CharField(max_length=10, blank=True, default="", verbose_name="CAP residenza")

    indirizzo_domicilio = models.CharField(max_length=300, blank=True, default="")
    citta_domicilio = models.CharField(max_length=100, blank=True, default="", verbose_name="Città domicilio")
    nazione_domicilio = models.CharField(max_length=100, blank=True, default="")
    cap_domicilio = models.CharField(max_length=10, blank=True, default="", verbose_name="CAP domicilio")

    codice_fiscale = models.CharField(max_length=16, blank=True, default="")
    titolo_studio = models.CharField(max_length=20, choices=TITOLO_CHOICES, blank=True, default="")

    email_privata = models.EmailField(blank=True, default="")
    telefono_privato = models.CharField(max_length=30, blank=True, default="")
    patente_auto = models.BooleanField(default=False)
    figli_a_carico = models.BooleanField(
        default=False,
        verbose_name="Figli a carico",
        help_text="Indica se il dipendente ha figli a carico. La quantità è data dai figli registrati.",
    )

    # Dati sensibili — accesso limitato a ruolo HR
    nome_banca = models.CharField(max_length=200, blank=True, default="")
    iban = models.CharField(max_length=34, blank=True, default="", verbose_name="IBAN")
    intestatario_conto = models.CharField(max_length=200, blank=True, default="")
    categoria_protetta = models.BooleanField(default=False)
    categoria_disabili = models.BooleanField(default=False)
    percentuale_disabilita = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name="Percentuale disabilità",
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anagrafica_civile_aggiornate",
    )

    class Meta:
        verbose_name = "Anagrafica civile dipendente"
        verbose_name_plural = "Anagrafiche civili dipendenti"

    def __str__(self) -> str:
        return f"Anagrafica civile [{self.legacy_anagrafica_id}]"

    @property
    def iban_mascherato(self) -> str:
        """Restituisce IBAN con la parte centrale mascherata per il display."""
        v = self.iban.replace(" ", "")
        if len(v) < 8:
            return v
        return f"{v[:4]} **** **** **** {v[-4:]}"

    @property
    def numero_figli(self) -> int:
        """Quantità di figli a carico, derivata dai record registrati."""
        return self.figli.count()


def _calcola_eta(data_nascita: date | None, riferimento: date | None = None) -> int | None:
    """Calcola l'età in anni compiuti alla data di riferimento (default: oggi)."""
    if not data_nascita:
        return None
    rif = riferimento or timezone.localdate()
    eta = rif.year - data_nascita.year - (
        (rif.month, rif.day) < (data_nascita.month, data_nascita.day)
    )
    return max(eta, 0)


class FiglioACarico(models.Model):
    """Figlio a carico di un dipendente. L'età è derivata dalla data di nascita."""

    anagrafica = models.ForeignKey(
        DipendenteAnagraficaCivile,
        on_delete=models.CASCADE,
        related_name="figli",
        verbose_name="Anagrafica civile",
    )
    nome = models.CharField(max_length=120, blank=True, default="", verbose_name="Nome")
    data_nascita = models.DateField(verbose_name="Data di nascita")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Figlio a carico"
        verbose_name_plural = "Figli a carico"
        ordering = ["data_nascita"]

    def __str__(self) -> str:
        return self.nome or f"Figlio nato il {self.data_nascita:%d-%m-%Y}"

    @property
    def eta(self) -> int | None:
        """Età del figlio in anni compiuti."""
        return _calcola_eta(self.data_nascita)


# ---------------------------------------------------------------------------
# Anagrafica aziendale dipendente (dati contrattuali/organizzativi)
# ---------------------------------------------------------------------------

class DipendenteAnagraficaAziendale(models.Model):
    CONTRATTO_INDETERMINATO = "INDETERMINATO"
    CONTRATTO_DETERMINATO = "DETERMINATO"
    CONTRATTO_APPRENDISTATO = "APPRENDISTATO"
    CONTRATTO_SOMMINISTRAZIONE = "SOMMINISTRAZIONE"
    CONTRATTO_COLLABORAZIONE = "COLLABORAZIONE"
    CONTRATTO_STAGE = "STAGE"
    CONTRATTO_ALTRO = "ALTRO"
    CONTRATTO_CHOICES = [
        (CONTRATTO_INDETERMINATO, "Tempo indeterminato"),
        (CONTRATTO_DETERMINATO, "Tempo determinato"),
        (CONTRATTO_APPRENDISTATO, "Apprendistato"),
        (CONTRATTO_SOMMINISTRAZIONE, "Somministrazione"),
        (CONTRATTO_COLLABORAZIONE, "Collaborazione"),
        (CONTRATTO_STAGE, "Stage / Tirocinio"),
        (CONTRATTO_ALTRO, "Altro"),
    ]

    TAGLIA_XS = "XS"
    TAGLIA_S = "S"
    TAGLIA_M = "M"
    TAGLIA_L = "L"
    TAGLIA_XL = "XL"
    TAGLIA_XXL = "XXL"
    TAGLIA_XXXL = "XXXL"
    TAGLIA_MAGLIA_CHOICES = [
        (TAGLIA_XS, "XS"),
        (TAGLIA_S, "S"),
        (TAGLIA_M, "M"),
        (TAGLIA_L, "L"),
        (TAGLIA_XL, "XL"),
        (TAGLIA_XXL, "XXL"),
        (TAGLIA_XXXL, "XXXL"),
    ]

    legacy_anagrafica_id = models.IntegerField(unique=True, db_index=True)

    badge = models.CharField(max_length=30, blank=True, default="", db_index=True, verbose_name="Badge")

    area = models.CharField(max_length=100, blank=True, default="", verbose_name="Reparto")
    area_aziendale_nome = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Area aziendale",
        help_text="Compilato automaticamente dall'area aziendale del reparto assegnato.",
    )
    caporeparto_legacy_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Caporeparto",
        help_text="ID legacy del caporeparto, compilato automaticamente dal reparto assegnato.",
    )
    ruolo_aziendale = models.CharField(max_length=200, blank=True, default="", verbose_name="Ruolo aziendale")

    taglia_scarpe = models.CharField(max_length=10, blank=True, default="")
    taglia_pantalone = models.CharField(max_length=20, blank=True, default="")
    taglia_maglia = models.CharField(max_length=10, choices=TAGLIA_MAGLIA_CHOICES, blank=True, default="")

    consenso_privacy = models.BooleanField(default=False)
    data_consenso_privacy = models.DateField(null=True, blank=True)

    data_prima_assunzione = models.DateField(null=True, blank=True)
    data_assunzione_ultima = models.DateField(
        null=True, blank=True,
        verbose_name="Data assunzione corrente",
        help_text="Inizio del rapporto di lavoro corrente (se diversa dalla prima assunzione)",
    )
    data_cessazione = models.DateField(
        null=True, blank=True,
        verbose_name="Data cessazione",
        help_text="Data di fine rapporto. Se valorizzata, il dipendente è considerato cessato.",
    )
    utente_id_pre_offboarding = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Account portale pre-offboarding",
        help_text="ID legacy dell'account portale da ricollegare se il dipendente viene rimesso in forza.",
    )
    prova_data_inizio = models.DateField(null=True, blank=True, verbose_name="Inizio periodo di prova")
    prova_data_fine = models.DateField(null=True, blank=True, verbose_name="Fine periodo di prova")
    tipologia_contratto = models.CharField(
        max_length=20, choices=CONTRATTO_CHOICES, blank=True, default=""
    )
    livello_inquadramento = models.CharField(max_length=50, blank=True, default="")

    email_aziendale = models.EmailField(blank=True, default="")
    telefono_aziendale = models.CharField(max_length=30, blank=True, default="")

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anagrafica_aziendale_aggiornate",
    )

    class Meta:
        verbose_name = "Anagrafica aziendale dipendente"
        verbose_name_plural = "Anagrafiche aziendali dipendenti"

    def __str__(self) -> str:
        return f"Anagrafica aziendale [{self.legacy_anagrafica_id}]"


class OffboardingPratica(models.Model):
    """Pratica operativa di uscita dipendente.

    La pratica raccoglie i task di restituzione/chiusura prima della cessazione
    effettiva del rapporto nel record aziendale e legacy.
    """
    STATO_IN_CORSO = "IN_CORSO"
    STATO_CHIUSA = "CHIUSA"
    STATO_CHIUSA_CON_ECCEZIONI = "CHIUSA_CON_ECCEZIONI"
    STATO_ANNULLATA = "ANNULLATA"
    STATO_CHOICES = [
        (STATO_IN_CORSO, "In corso"),
        (STATO_CHIUSA, "Chiusa"),
        (STATO_CHIUSA_CON_ECCEZIONI, "Chiusa con eccezioni"),
        (STATO_ANNULLATA, "Annullata"),
    ]
    STATI_APERTI = (STATO_IN_CORSO,)

    MOTIVO_LICENZIAMENTO = "licenziamento"
    MOTIVO_DIMISSIONI = "dimissioni"
    MOTIVO_FINE_CONTRATTO = "fine_contratto"
    MOTIVO_PENSIONAMENTO = "pensionamento"
    MOTIVO_ALTRO = "altro"
    MOTIVO_CHOICES = [
        (MOTIVO_LICENZIAMENTO, "Licenziamento"),
        (MOTIVO_DIMISSIONI, "Dimissioni"),
        (MOTIVO_FINE_CONTRATTO, "Fine contratto"),
        (MOTIVO_PENSIONAMENTO, "Pensionamento"),
        (MOTIVO_ALTRO, "Altro"),
    ]

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    dipendente_nome = models.CharField(max_length=250, blank=True, default="")
    reparto = models.CharField(max_length=200, blank=True, default="")
    mansione = models.CharField(max_length=200, blank=True, default="")
    motivo = models.CharField(max_length=30, choices=MOTIVO_CHOICES, default=MOTIVO_LICENZIAMENTO)
    data_cessazione_prevista = models.DateField()
    ultimo_giorno_operativo = models.DateField(null=True, blank=True)
    note_hr = models.TextField(blank=True, default="")
    stato = models.CharField(max_length=30, choices=STATO_CHOICES, default=STATO_IN_CORSO, db_index=True)
    utente_id_pre_offboarding = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offboarding_pratiche_create",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offboarding_pratiche_aggiornate",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offboarding_pratiche_chiuse",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "stato", "-created_at"]),
        ]
        verbose_name = "Pratica offboarding"
        verbose_name_plural = "Pratiche offboarding"

    def __str__(self) -> str:
        nome = self.dipendente_nome or f"#{self.legacy_anagrafica_id}"
        return f"Offboarding {nome} - {self.get_stato_display()}"

    @property
    def is_aperta(self) -> bool:
        return self.stato in self.STATI_APERTI


class OffboardingTask(models.Model):
    CATEGORIA_HR = "HR"
    CATEGORIA_IT = "IT"
    CATEGORIA_RESPONSABILE = "RESPONSABILE"
    CATEGORIA_DPI = "DPI"
    CATEGORIA_AMMINISTRAZIONE = "AMMINISTRAZIONE"
    CATEGORIA_ALTRO = "ALTRO"
    CATEGORIA_CHOICES = [
        (CATEGORIA_HR, "HR"),
        (CATEGORIA_IT, "IT / Sistemi informatici"),
        (CATEGORIA_RESPONSABILE, "Responsabile reparto"),
        (CATEGORIA_DPI, "DPI / Sicurezza"),
        (CATEGORIA_AMMINISTRAZIONE, "Amministrazione"),
        (CATEGORIA_ALTRO, "Altro"),
    ]

    STATO_DA_FARE = "DA_FARE"
    STATO_COMPLETATO = "COMPLETATO"
    STATO_ECCEZIONE = "ECCEZIONE"
    STATO_CHOICES = [
        (STATO_DA_FARE, "Da fare"),
        (STATO_COMPLETATO, "Completato"),
        (STATO_ECCEZIONE, "Eccezione"),
    ]

    pratica = models.ForeignKey(OffboardingPratica, on_delete=models.CASCADE, related_name="tasks")
    codice = models.CharField(max_length=60)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES, default=CATEGORIA_HR, db_index=True)
    titolo = models.CharField(max_length=200)
    descrizione = models.TextField(blank=True, default="")
    stato = models.CharField(max_length=20, choices=STATO_CHOICES, default=STATO_DA_FARE, db_index=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offboarding_task_completati",
    )

    class Meta:
        ordering = ["categoria", "id"]
        unique_together = [("pratica", "codice")]
        indexes = [
            models.Index(fields=["pratica", "stato"]),
            models.Index(fields=["categoria", "stato"]),
        ]
        verbose_name = "Task offboarding"
        verbose_name_plural = "Task offboarding"

    def __str__(self) -> str:
        return f"{self.titolo} ({self.get_stato_display()})"


class OnboardingPratica(models.Model):
    """Pratica operativa di inserimento dipendente (onboarding).

    Speculare a ``OffboardingPratica``: raccoglie la checklist di attivazione
    (account, badge, DPI da mansionario, corsi obbligatori, visita preassuntiva)
    generata da ``services.onboarding``. A differenza dell'offboarding la
    chiusura NON ha effetti sul record legacy/aziendale: serve solo a tracciare
    il completamento della presa in carico del nuovo assunto.
    """
    STATO_IN_CORSO = "IN_CORSO"
    STATO_CHIUSA = "CHIUSA"
    STATO_CHIUSA_CON_ECCEZIONI = "CHIUSA_CON_ECCEZIONI"
    STATO_ANNULLATA = "ANNULLATA"
    STATO_CHOICES = [
        (STATO_IN_CORSO, "In corso"),
        (STATO_CHIUSA, "Chiusa"),
        (STATO_CHIUSA_CON_ECCEZIONI, "Chiusa con eccezioni"),
        (STATO_ANNULLATA, "Annullata"),
    ]
    STATI_APERTI = (STATO_IN_CORSO,)

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    dipendente_nome = models.CharField(max_length=250, blank=True, default="")
    reparto = models.CharField(max_length=200, blank=True, default="")
    mansione = models.CharField(max_length=200, blank=True, default="")
    data_assunzione = models.DateField(null=True, blank=True)
    note_hr = models.TextField(blank=True, default="")
    stato = models.CharField(max_length=30, choices=STATO_CHOICES, default=STATO_IN_CORSO, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_pratiche_create",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_pratiche_aggiornate",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_pratiche_chiuse",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "stato", "-created_at"]),
        ]
        verbose_name = "Pratica onboarding"
        verbose_name_plural = "Pratiche onboarding"

    def __str__(self) -> str:
        nome = self.dipendente_nome or f"#{self.legacy_anagrafica_id}"
        return f"Onboarding {nome} - {self.get_stato_display()}"

    @property
    def is_aperta(self) -> bool:
        return self.stato in self.STATI_APERTI


class OnboardingTask(models.Model):
    CATEGORIA_HR = "HR"
    CATEGORIA_IT = "IT"
    CATEGORIA_RESPONSABILE = "RESPONSABILE"
    CATEGORIA_DPI = "DPI"
    CATEGORIA_AMMINISTRAZIONE = "AMMINISTRAZIONE"
    CATEGORIA_ALTRO = "ALTRO"
    CATEGORIA_CHOICES = [
        (CATEGORIA_HR, "HR"),
        (CATEGORIA_IT, "IT / Sistemi informatici"),
        (CATEGORIA_RESPONSABILE, "Responsabile reparto"),
        (CATEGORIA_DPI, "DPI / Sicurezza"),
        (CATEGORIA_AMMINISTRAZIONE, "Amministrazione"),
        (CATEGORIA_ALTRO, "Altro"),
    ]

    STATO_DA_FARE = "DA_FARE"
    STATO_COMPLETATO = "COMPLETATO"
    STATO_ECCEZIONE = "ECCEZIONE"
    STATO_CHOICES = [
        (STATO_DA_FARE, "Da fare"),
        (STATO_COMPLETATO, "Completato"),
        (STATO_ECCEZIONE, "Eccezione"),
    ]

    pratica = models.ForeignKey(OnboardingPratica, on_delete=models.CASCADE, related_name="tasks")
    codice = models.CharField(max_length=60)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES, default=CATEGORIA_HR, db_index=True)
    titolo = models.CharField(max_length=200)
    descrizione = models.TextField(blank=True, default="")
    stato = models.CharField(max_length=20, choices=STATO_CHOICES, default=STATO_DA_FARE, db_index=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_task_completati",
    )

    class Meta:
        ordering = ["categoria", "id"]
        unique_together = [("pratica", "codice")]
        indexes = [
            models.Index(fields=["pratica", "stato"]),
            models.Index(fields=["categoria", "stato"]),
        ]
        verbose_name = "Task onboarding"
        verbose_name_plural = "Task onboarding"

    def __str__(self) -> str:
        return f"{self.titolo} ({self.get_stato_display()})"


class OnboardingOffboardingCampo(models.Model):
    """Associazione configurabile tra campi del form nuovo dipendente e workflow."""

    FASE_ONBOARDING = "ONBOARDING"
    FASE_OFFBOARDING = "OFFBOARDING"
    FASE_CHOICES = [
        (FASE_ONBOARDING, "Onboarding"),
        (FASE_OFFBOARDING, "Offboarding"),
    ]

    CATEGORIA_HR = "HR"
    CATEGORIA_IT = "IT"
    CATEGORIA_RESPONSABILE = "RESPONSABILE"
    CATEGORIA_DPI = "DPI"
    CATEGORIA_AMMINISTRAZIONE = "AMMINISTRAZIONE"
    CATEGORIA_ALTRO = "ALTRO"
    CATEGORIA_CHOICES = [
        (CATEGORIA_HR, "HR"),
        (CATEGORIA_IT, "IT / Sistemi informatici"),
        (CATEGORIA_RESPONSABILE, "Responsabile reparto"),
        (CATEGORIA_DPI, "DPI / Sicurezza"),
        (CATEGORIA_AMMINISTRAZIONE, "Amministrazione"),
        (CATEGORIA_ALTRO, "Altro"),
    ]

    fase = models.CharField(max_length=20, choices=FASE_CHOICES, db_index=True)
    campo_key = models.CharField(max_length=120)
    campo_label = models.CharField(max_length=160)
    sezione = models.CharField(max_length=120, blank=True, default="")
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES, default=CATEGORIA_HR, db_index=True)
    obbligatorio = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    ordine = models.PositiveIntegerField(default=50)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anagrafica_workflow_campi_aggiornati",
    )

    class Meta:
        ordering = ["fase", "ordine", "campo_label"]
        unique_together = [("fase", "campo_key")]
        indexes = [
            models.Index(fields=["fase", "is_active", "ordine"]),
        ]
        verbose_name = "Campo onboarding/offboarding"
        verbose_name_plural = "Campi onboarding/offboarding"

    def __str__(self) -> str:
        return f"{self.get_fase_display()} - {self.campo_label}"


# ---------------------------------------------------------------------------
# Voci retributive — importazione mensile da studio paghe (CSV)
# ---------------------------------------------------------------------------

def _classify_pay_item(key: str) -> str:
    """Classifica una voce retributiva nelle tre macro-sezioni."""
    k = key.strip().lower()
    FISSI = (
        "retribuzione base", "scatti di anzianit", "terzo elemento",
        "cottimo", "premio professionale", "superminimo individuale",
        "scatti congelati", "acconto scatti futuri", "acconto futuri aumenti",
        "ad personam", "premio categoria",
    )
    VARIABILI = (
        "premio produzione operai", "premio produzione impiegati",
        "premio di anzianita", "indennita' di funzione", "indennita di funzione",
        "trasferta italia",
    )
    TOTALI = ("retribuzione di fatto", "totale elementi variabili", "rml", "ral")
    for prefix in FISSI:
        if k.startswith(prefix):
            return "fisso"
    for prefix in VARIABILI:
        if k.startswith(prefix):
            return "variabile"
    for prefix in TOTALI:
        if k == prefix:
            return "totale"
    return "altro"


class ImportazioneRetributiva(models.Model):
    """Traccia ogni importazione mensile CSV dallo studio paghe."""
    ORIGINE_CSV = "CSV"
    ORIGINE_MANUALE = "MANUALE"
    ORIGINE_CHOICES = [
        (ORIGINE_CSV, "Import CSV studio paghe"),
        (ORIGINE_MANUALE, "Inserimento manuale HR"),
    ]

    data_importazione = models.DateTimeField(auto_now_add=True)
    data_competenza = models.DateField(
        help_text="Primo giorno del mese di competenza (es. 2026-04-01)"
    )
    origine = models.CharField(
        max_length=10, choices=ORIGINE_CHOICES, default=ORIGINE_CSV, db_index=True
    )
    importato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="importazioni_retributive",
    )
    file_nome = models.CharField(max_length=255, blank=True, default="")
    righe_totali = models.IntegerField(default=0)
    righe_ok = models.IntegerField(default=0)
    righe_errore = models.IntegerField(default=0)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-data_competenza", "-data_importazione"]
        verbose_name = "Importazione retributiva"
        verbose_name_plural = "Importazioni retributive"

    def __str__(self) -> str:
        mese = self.data_competenza.strftime("%B %Y") if self.data_competenza else "?"
        return f"Importazione {mese} ({self.righe_ok} voci)"


class VoceRetributiva(models.Model):
    """Singola voce retributiva di un dipendente per un periodo di competenza."""
    CAT_FISSO = "fisso"
    CAT_VARIABILE = "variabile"
    CAT_TOTALE = "totale"
    CAT_ALTRO = "altro"

    CATEGORIA_CHOICES = [
        (CAT_FISSO, "Elementi Fissi"),
        (CAT_VARIABILE, "Elementi Variabili"),
        (CAT_TOTALE, "Totali Elementi"),
        (CAT_ALTRO, "Altro"),
    ]

    importazione = models.ForeignKey(
        ImportazioneRetributiva, on_delete=models.CASCADE, related_name="voci"
    )
    tax_code = models.CharField(max_length=16, db_index=True)
    legacy_anagrafica_id = models.IntegerField(null=True, blank=True, db_index=True)
    data_competenza = models.DateField()
    pay_item = models.CharField(max_length=150)
    pay_item_key = models.CharField(max_length=150, db_index=True)
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default=CAT_ALTRO)
    importo = models.DecimalField(max_digits=12, decimal_places=2)
    is_changed = models.BooleanField(default=False)
    importo_precedente = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    manuale = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True se voce inserita manualmente da utente HR (override delle voci CSV con stesso pay_item_key)",
    )
    note = models.CharField(max_length=300, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="voci_retributive_modificate",
    )

    class Meta:
        ordering = ["-data_competenza", "tax_code", "categoria", "pay_item_key"]
        indexes = [
            models.Index(fields=["tax_code", "pay_item_key", "-data_competenza"]),
            models.Index(fields=["legacy_anagrafica_id", "-data_competenza"]),
        ]
        verbose_name = "Voce retributiva"
        verbose_name_plural = "Voci retributive"

    def __str__(self) -> str:
        return f"{self.tax_code} — {self.pay_item} ({self.data_competenza})"


# ---------------------------------------------------------------------------
# Permessi accesso dati HR riservati (singleton)
# ---------------------------------------------------------------------------

class AnagraficaHRPermission(models.Model):
    """Singleton: chi può vedere i dati HR riservati (IBAN, codice fiscale, disabilità)."""
    ACCESSO_TUTTI = "TUTTI"
    ACCESSO_ADMIN = "ADMIN"
    ACCESSO_RUOLI = "RUOLI"

    ACCESSO_CHOICES = [
        (ACCESSO_TUTTI, "Tutti gli utenti autenticati"),
        (ACCESSO_ADMIN, "Solo amministratori"),
        (ACCESSO_RUOLI, "Ruoli ACL specifici"),
    ]

    accesso = models.CharField(max_length=20, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    ruolo_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista ruolo_id ACL legacy abilitati (usato solo se accesso=RUOLI)",
    )

    class Meta:
        verbose_name = "Permessi dati HR riservati"
        verbose_name_plural = "Permessi dati HR riservati"

    def __str__(self) -> str:
        return f"Permessi HR ({self.get_accesso_display()})"

    @classmethod
    def get_instance(cls) -> "AnagraficaHRPermission":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"accesso": cls.ACCESSO_ADMIN})
        return obj


# ---------------------------------------------------------------------------
# Storico contrattuale — evoluzione contratto, livello e qualifica professionale
# ---------------------------------------------------------------------------

class TipologiaContratto(models.Model):
    """Catalogo tipologie di contratto — sostituisce CONTRATTO_CHOICES hardcoded."""
    codice = models.CharField(max_length=20, unique=True)
    nome = models.CharField(max_length=100)
    ordine = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "codice"]
        verbose_name = "Tipologia contratto"
        verbose_name_plural = "Tipologie contratto"

    def __str__(self) -> str:
        return self.nome


class LivelloContrattuale(models.Model):
    """Catalogo livelli contrattuali (A1, B3 … DIR) con descrizione testuale."""
    codice = models.CharField(max_length=10, unique=True)
    descrizione = models.CharField(max_length=200, blank=True, default="")
    ordine = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "codice"]
        verbose_name = "Livello contrattuale"
        verbose_name_plural = "Livelli contrattuali"

    def __str__(self) -> str:
        return f"{self.codice} — {self.descrizione}" if self.descrizione else self.codice


class DipendenteCambiamentoOrganizzativo(models.Model):
    """Storico cambiamenti organizzativi interni (mansione, reparto, area, ruolo aziendale).

    Generato automaticamente dagli hook delle view di modifica. Lo storico contrattuale
    CCNL (tipologia contratto, livello, qualifica) vive invece in StoricoContratto.
    """
    TIPO_MANSIONE = "MANSIONE"
    TIPO_REPARTO = "REPARTO"
    TIPO_AREA = "AREA"
    TIPO_RUOLO_AZIENDALE = "RUOLO_AZIENDALE"

    TIPO_CHOICES = [
        (TIPO_MANSIONE, "Mansione"),
        (TIPO_REPARTO, "Reparto (legacy)"),
        (TIPO_AREA, "Reparto"),
        (TIPO_RUOLO_AZIENDALE, "Ruolo aziendale"),
    ]

    TIPO_COLORI = {
        TIPO_MANSIONE: "#1d4ed8",
        TIPO_REPARTO: "#0891b2",
        TIPO_AREA: "#7c3aed",
        TIPO_RUOLO_AZIENDALE: "#db2777",
    }

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, db_index=True)
    valore_precedente = models.CharField(max_length=300, blank=True, default="")
    valore_nuovo = models.CharField(max_length=300, blank=True, default="")
    data_effetto = models.DateField(
        help_text="Data da cui vale il nuovo valore (default: oggi)"
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="cambiamenti_organizzativi_registrati",
    )

    class Meta:
        ordering = ["-data_effetto", "-created_at"]
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "tipo", "-data_effetto"]),
        ]
        verbose_name = "Cambiamento organizzativo"
        verbose_name_plural = "Storico cambiamenti organizzativi"

    def __str__(self) -> str:
        prev = self.valore_precedente or "(vuoto)"
        new = self.valore_nuovo or "(vuoto)"
        return f"[{self.legacy_anagrafica_id}] {self.get_tipo_display()}: {prev} → {new}"

    @property
    def colore(self) -> str:
        return self.TIPO_COLORI.get(self.tipo, "#64748b")


class StoricoContratto(models.Model):
    legacy_anagrafica_id = models.IntegerField(null=True, blank=True, db_index=True)
    tax_code = models.CharField(max_length=16, blank=True, default="", db_index=True)

    data_inizio = models.DateField()
    data_fine = models.DateField(null=True, blank=True)

    tipologia_contratto = models.CharField(max_length=20, blank=True, default="")
    qualifica_nome = models.CharField(max_length=150, blank=True, default="")
    codice_livello = models.CharField(max_length=10, blank=True, default="")
    ccnl = models.CharField(max_length=100, blank=True, default="")
    descrizione_livello = models.CharField(max_length=200, blank=True, default="")

    importato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="contratti_importati",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_inizio", "-created_at"]
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "data_inizio"]),
            models.Index(fields=["tax_code", "data_inizio"]),
        ]
        verbose_name = "Storico contrattuale"
        verbose_name_plural = "Storico contrattuale"

    def __str__(self) -> str:
        fine = self.data_fine.strftime("%d-%m-%Y") if self.data_fine else "in corso"
        return f"{self.tax_code} {self.data_inizio.strftime('%d-%m-%Y')} – {fine}"

    @property
    def is_in_corso(self) -> bool:
        return self.data_fine is None


# ---------------------------------------------------------------------------
# Ratei ferie/ROL/ex-festività — importazione mensile da cedolini paga (XLSX)
# ---------------------------------------------------------------------------

class ImportazioneCedolini(models.Model):
    """Batch di importazione mensile saldi ore da file cedolini (XLSX)."""
    ORIGINE_XLSX = "XLSX"
    ORIGINE_SQL = "SQL"
    ORIGINE_CHOICES = [
        (ORIGINE_XLSX, "Import XLSX cedolini"),
        (ORIGINE_SQL, "Import diretto SQL"),
    ]

    data_importazione = models.DateTimeField(auto_now_add=True)
    data_competenza = models.DateField(
        help_text="Ultimo giorno del mese di competenza (es. 2026-05-31)"
    )
    origine = models.CharField(
        max_length=10, choices=ORIGINE_CHOICES, default=ORIGINE_XLSX, db_index=True
    )
    importato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="importazioni_cedolini",
    )
    file_nome = models.CharField(max_length=255, blank=True, default="")
    righe_totali = models.IntegerField(default=0)
    righe_ok = models.IntegerField(default=0)
    righe_errore = models.IntegerField(default=0)
    righe_non_trovate = models.IntegerField(default=0)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-data_competenza", "-data_importazione"]
        verbose_name = "Importazione cedolini"
        verbose_name_plural = "Importazioni cedolini"

    def __str__(self) -> str:
        mese = self.data_competenza.strftime("%B %Y") if self.data_competenza else "?"
        return f"Cedolini {mese} ({self.righe_ok} righe)"


class SaldoCedolino(models.Model):
    """Saldi ore mensili per dipendente estratti dal cedolino paga.

    Chiave logica: (tax_code, data_competenza) — unica per dipendente×mese.
    Usato per visualizzare l'evoluzione di ferie/ROL/ex-festività nella scheda
    dipendente e nella vista aggregata Anagrafica > Ratei Ferie/Permessi.
    """
    importazione = models.ForeignKey(
        ImportazioneCedolini,
        on_delete=models.CASCADE,
        related_name="saldi",
        null=True, blank=True,
    )
    tax_code = models.CharField(max_length=16, db_index=True, verbose_name="Codice fiscale")
    legacy_anagrafica_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="Risolto al momento dell'import da DipendenteAnagraficaCivile.codice_fiscale",
    )
    data_competenza = models.DateField(
        db_index=True,
        help_text="Ultimo giorno del mese di competenza (es. 2026-05-31)",
    )

    anzianita_anni = models.SmallIntegerField(null=True, blank=True, verbose_name="Anzianità (anni)")
    anzianita_mesi = models.SmallIntegerField(null=True, blank=True, verbose_name="Anzianità (mesi aggiuntivi)")

    # FERIE (ore con 2 decimali)
    ferie_anni_prec = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ferie anni prec.")
    ferie_maturati  = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ferie maturate")
    ferie_goduti    = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ferie godute")
    ferie_residui   = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ferie residue")

    # ROL
    rol_anni_prec = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="ROL anni prec.")
    rol_maturati  = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="ROL maturati")
    rol_goduti    = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="ROL goduti")
    rol_residui   = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="ROL residui")

    # EX FESTIVITÀ
    ex_fest_anni_prec = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ex-fest. anni prec.")
    ex_fest_maturati  = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ex-fest. maturate")
    ex_fest_goduti    = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ex-fest. godute")
    ex_fest_residui   = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Ex-fest. residue")

    # PERMESSI (inclusi per completezza, attualmente 0 nei cedolini)
    permessi_anni_prec = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Permessi anni prec.")
    permessi_maturati  = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Permessi maturati")
    permessi_goduti    = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Permessi goduti")
    permessi_residui   = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Permessi residui")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_competenza", "tax_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["tax_code", "data_competenza"],
                name="anagrafica_saldo_cedolino_tax_competenza_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "-data_competenza"]),
            models.Index(fields=["data_competenza"]),
        ]
        verbose_name = "Saldo cedolino"
        verbose_name_plural = "Saldi cedolini"

    def __str__(self) -> str:
        mese = self.data_competenza.strftime("%m-%Y") if self.data_competenza else "?"
        return f"{self.tax_code} — {mese}"


# ---------------------------------------------------------------------------
# Navigazione subnav anagrafica — categorie e link configurabili
# ---------------------------------------------------------------------------

class SubnavCategoriaAnagrafica(models.Model):
    """Categoria (dropdown) nella subnav del modulo anagrafica.

    I link senza categoria appaiono come voci dirette nel menu orizzontale.
    Le categorie con almeno un link attivo generano un dropdown.
    """

    nome = models.CharField(max_length=80)
    icona = models.CharField(max_length=20, blank=True, default="", help_text="Emoji o testo breve mostrato prima del nome.")
    ordine = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Categoria subnav anagrafica"
        verbose_name_plural = "Categorie subnav anagrafica"

    def __str__(self) -> str:
        return self.nome


class SubnavLinkAnagrafica(models.Model):
    """Voce di navigazione nella subnav del modulo anagrafica.

    Un link può essere:
    - Diretto nella barra (``categoria=None``)
    - Dentro un dropdown (``categoria`` impostata)

    I link di sistema (``is_sistema=True``) non possono essere eliminati ma
    possono essere nascosti, rinominati o riordinati.
    """

    class UrlType(models.TextChoices):
        NAMED = "named", "URL Django (nome view)"
        RAW = "raw", "URL diretto (path o esterno)"

    categoria = models.ForeignKey(
        SubnavCategoriaAnagrafica,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="links",
    )
    etichetta = models.CharField(max_length=80)
    icona = models.CharField(max_length=20, blank=True, default="")
    url_type = models.CharField(max_length=10, choices=UrlType.choices, default=UrlType.NAMED)
    url_value = models.CharField(
        max_length=255,
        help_text="Nome view Django (es. 'anagrafica:dipendenti_list') oppure path/URL assoluto.",
    )
    active_view_names = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Nomi view che rendono il link attivo (comma-separated). Solo per url_type=named.",
    )
    ordine = models.PositiveSmallIntegerField(default=0)
    apri_nuova_tab = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_sistema = models.BooleanField(
        default=False,
        help_text="Se True il link è di sistema: non eliminabile, solo nascondibile/rinominabile.",
    )

    class Meta:
        ordering = ["ordine", "etichetta"]
        verbose_name = "Link subnav anagrafica"
        verbose_name_plural = "Link subnav anagrafica"

    def __str__(self) -> str:
        return self.etichetta


# ---------------------------------------------------------------------------
# Cartelle documenti dipendente (catalogo "scheletro" uguale per tutti)
# ---------------------------------------------------------------------------

class CartellaDocumentoDipendente(models.Model):
    """Cartella virtuale che definisce lo scheletro documentale uguale per tutti i dipendenti.

    Gestita da Impostazioni → tab Documenti. I documenti caricati manualmente
    vengono assegnati a una cartella; i documenti di sistema (DPI, visite) ne
    sono esclusi (``cartella=None``).
    """

    nome = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="figlie",
        help_text="Cartella superiore. Vuoto = cartella di primo livello.",
    )
    descrizione = models.CharField(max_length=300, blank=True, default="")
    ordine = models.PositiveSmallIntegerField(default=0, help_text="Ordinamento nella lista.")
    attiva = models.BooleanField(default=True, help_text="Se False non appare nel form di upload.")
    retention_anni = models.PositiveSmallIntegerField(
        default=10,
        help_text="Anni di conservazione GDPR per i documenti manuali di questa cartella "
                  "(impostazione del container; default 10). Applicata ai nuovi documenti.",
    )
    solo_admin = models.BooleanField(
        default=False,
        help_text="Cartella riservata: nell'archivio i suoi documenti sono visibili solo ai "
                  "super-amministratori (nascosti agli altri ruoli HR).",
    )

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Cartella documenti dipendente"
        verbose_name_plural = "Cartelle documenti dipendente"
        unique_together = [("parent", "nome")]

    def __str__(self) -> str:
        if self.parent_id:
            return f"{self.parent.nome} / {self.nome}"
        return self.nome


# ---------------------------------------------------------------------------
# Documenti dipendente (spazio documenti privato: consegne DPI, referti visite, ecc.)
# ---------------------------------------------------------------------------

def _documento_dipendente_upload_to(instance, filename: str) -> str:
    legacy_id = instance.legacy_anagrafica_id or "tmp"
    suffix = Path(filename or "").suffix.lower()[:20] or ".bin"
    stem = Path(filename or "").stem[:80] or "documento"
    now = timezone.now()
    return (
        f"anagrafica/dipendenti/{legacy_id}/documenti/"
        f"{now.strftime('%Y%m')}/{now.strftime('%Y%m%d_%H%M%S')}_{stem}{suffix}"
    )


class DocumentoDipendente(models.Model):
    """Documento archiviato nello spazio privato del dipendente.

    Storage: ``PrivateAnagraficaStorage`` → file fuori webroot. Accesso solo
    via view protetta ``anagrafica:documento_download`` con ACL e audit.
    Il campo ``oggetto_riferimento_*`` consente di puntare a una entity di
    origine (es. ``dpi.consegna`` con id) senza ricorrere a GenericForeignKey.
    """

    class Tipo(models.TextChoices):
        DPI_CONSEGNA = "DPI_CONSEGNA", "Modulo consegna DPI"
        VISITA_MEDICA_REFERTO = "VISITA_MEDICA_REFERTO", "Referto visita medica"
        CERTIFICATO_FORMAZIONE = "CERTIFICATO_FORMAZIONE", "Attestato formazione"
        MANUALE = "MANUALE", "Documento manuale"
        ALTRO = "ALTRO", "Altro"

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    tipo = models.CharField(
        max_length=30, choices=Tipo.choices, default=Tipo.MANUALE, db_index=True
    )
    cartella = models.ForeignKey(
        CartellaDocumentoDipendente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documenti",
        help_text="Cartella virtuale di appartenenza. Null per documenti di sistema (DPI, referti).",
    )
    file = models.FileField(
        upload_to=_documento_dipendente_upload_to,
        storage=PrivateAnagraficaStorage(),
    )
    nome_originale = models.CharField(max_length=255, blank=True, default="")
    tipo_mime = models.CharField(max_length=100, blank=True, default="")
    dimensione_bytes = models.PositiveIntegerField(default=0)
    descrizione = models.CharField(max_length=300, blank=True, default="")

    oggetto_riferimento_tipo = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Riferimento sintetico all'entity di origine (es. 'dpi.consegna').",
    )
    oggetto_riferimento_id = models.IntegerField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documenti_dipendente_caricati",
    )
    created_by_display = models.CharField(max_length=200, blank=True, default="")

    # GDPR – data limite di conservazione (calcolata automaticamente al salvataggio).
    # Null = non ancora calcolata (documenti pre-migrazione). Il management command
    # `cleanup_expired_documents` elimina solo i doc scaduti di dipendenti cessati.
    retention_until = models.DateField(
        null=True, blank=True, db_index=True,
        verbose_name="Conservare fino al",
        help_text="Data limite GDPR. Calcolata automaticamente; modificabile manualmente.",
    )

    # Anni di conservazione per tipo documento (riferimento normativo italiano).
    # Referti/DPI/Formazione: D.Lgs. 81/2008 – almeno 10 anni post-cessazione.
    # Contratti/Cedolini: Art. 2220 c.c. + D.P.R. 445/2000 – 10 anni.
    _RETENTION_ANNI = {
        Tipo.VISITA_MEDICA_REFERTO: 10,
        Tipo.DPI_CONSEGNA: 10,
        Tipo.CERTIFICATO_FORMAZIONE: 10,
        Tipo.MANUALE: 10,
        Tipo.ALTRO: 10,
    }

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "tipo"]),
            models.Index(fields=["oggetto_riferimento_tipo", "oggetto_riferimento_id"]),
            models.Index(fields=["retention_until"]),
        ]
        verbose_name = "Documento dipendente"
        verbose_name_plural = "Documenti dipendente"

    def __str__(self) -> str:
        nome = self.nome_originale or Path(self.file.name or "").name or "documento"
        return f"[{self.legacy_anagrafica_id}] {self.get_tipo_display()} — {nome}"

    def save(self, *args, **kwargs):
        if self.retention_until is None and self.tipo:
            anni = self._RETENTION_ANNI.get(self.tipo, 10)
            # Override per-cartella (container manager): i documenti manuali ereditano
            # la retention configurata sulla cartella, se valorizzata.
            if self.tipo == self.Tipo.MANUALE and self.cartella_id:
                try:
                    if self.cartella and self.cartella.retention_anni:
                        anni = self.cartella.retention_anni
                except Exception:
                    pass
            # Per record già esistenti usa created_at; per i nuovi (pk non ancora
            # assegnato) created_at non è ancora scritto → usa date.today().
            base = self.created_at.date() if self.pk and self.created_at else date.today()
            self.retention_until = _add_months(base, anni * 12)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        storage = self.file.storage if self.file else None
        file_name = self.file.name if self.file else ""
        super().delete(*args, **kwargs)
        if storage and file_name:
            try:
                if storage.exists(file_name):
                    storage.delete(file_name)
            except Exception:
                # storage.exists/delete possono fallire per file mancanti: ignora
                pass


# ---------------------------------------------------------------------------
# Visite mediche (catalogo tipi + registrazioni per dipendente)
# ---------------------------------------------------------------------------

class TipoVisitaMedica(models.Model):
    """Catalogo tipologie di visita medica configurabili dall'utente.

    Ogni tipologia ha una periodicità fissa in mesi e può essere associata
    a uno o più ruoli operativi: i dipendenti con almeno uno dei ruoli
    collegati devono effettuare quella visita con la cadenza indicata.
    """

    nome = models.CharField(max_length=150, unique=True)
    descrizione = models.TextField(blank=True, default="")
    durata_mesi = models.PositiveSmallIntegerField(
        default=12,
        help_text="Periodicità in mesi: la scadenza parte dalla data dell'ultima visita.",
    )
    ruoli_operativi = models.ManyToManyField(
        RuoloOperativo,
        blank=True,
        related_name="tipi_visita_medica",
        help_text="Ruoli operativi per cui questa visita è obbligatoria.",
    )
    obbligatoria = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Tipo visita medica"
        verbose_name_plural = "Tipi visita medica"

    def __str__(self) -> str:
        return self.nome


class VisitaMedica(models.Model):
    """Registrazione di una visita medica effettuata da un dipendente."""

    class Esito(models.TextChoices):
        IDONEO                    = "IDONEO",            "Idoneo"
        IDONEO_MANSIONE           = "IDONEO_MANS",       "Idoneo mansione specifica"
        IDONEO_CON_PRESCRIZIONI   = "IDONEO_PRESCR",     "Idoneo con prescrizioni"
        IDONEO_CON_LIMITAZIONI    = "IDONEO_LIM",        "Idoneo con limitazioni"
        IDONEO_LIM_PRESCR         = "IDONEO_LIM_PRESCR", "Idoneo con limitazioni e prescrizioni"
        NON_IDONEO_TEMPORANEO     = "NON_IDONEO_TEMP",   "Non idoneo (temporaneo)"
        NON_IDONEO_DEFINITIVO     = "NON_IDONEO_DEF",    "Non idoneo (definitivo)"

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    tipo = models.ForeignKey(
        TipoVisitaMedica,
        on_delete=models.PROTECT,
        related_name="visite",
    )
    data_svolgimento = models.DateField()
    data_scadenza = models.DateField(
        null=True, blank=True,
        help_text="Calcolata automaticamente: data_svolgimento + durata_mesi del tipo.",
    )
    esito = models.CharField(
        max_length=20, choices=Esito.choices, default=Esito.IDONEO
    )
    prescrizioni = models.TextField(blank=True, default="")
    medico_competente = models.CharField(max_length=200, blank=True, default="")
    note = models.TextField(blank=True, default="")
    referto_documento = models.ForeignKey(
        DocumentoDipendente,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="DocumentoDipendente di tipo VISITA_MEDICA_REFERTO collegato.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="visite_mediche_create",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="visite_mediche_modificate",
    )

    class Meta:
        ordering = ["-data_svolgimento", "-id"]
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "data_scadenza"]),
            models.Index(fields=["tipo", "data_scadenza"]),
        ]
        verbose_name = "Visita medica"
        verbose_name_plural = "Visite mediche"

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.tipo.nome} — {self.data_svolgimento}"

    def save(self, *args, **kwargs):
        if self.data_svolgimento and self.tipo_id:
            durata = self.tipo.durata_mesi or 0
            self.data_scadenza = _add_months(self.data_svolgimento, durata) if durata > 0 else None
        super().save(*args, **kwargs)

    @property
    def is_scaduta(self) -> bool:
        if self.data_scadenza is None:
            return False
        return self.data_scadenza < timezone.localdate()

    @property
    def in_scadenza(self) -> bool:
        """Scade entro 60 giorni e non è ancora scaduta."""
        if self.data_scadenza is None:
            return False
        oggi = timezone.localdate()
        return oggi <= self.data_scadenza <= oggi + timedelta(days=60)


# ---------------------------------------------------------------------------
# Permessi accesso visite mediche (singleton — dato sanitario sensibile)
# ---------------------------------------------------------------------------

class AnagraficaVisiteMedichePermission(models.Model):
    """Singleton: chi può vedere/registrare le visite mediche.

    Il default è ADMIN: i dati di idoneità lavorativa sono sanitari e vanno
    trattati con la massima riservatezza (RSPP / medico competente / HR sanitario).
    """

    ACCESSO_TUTTI = "TUTTI"
    ACCESSO_ADMIN = "ADMIN"
    ACCESSO_RUOLI = "RUOLI"

    ACCESSO_CHOICES = [
        (ACCESSO_TUTTI, "Tutti gli utenti autenticati"),
        (ACCESSO_ADMIN, "Solo amministratori"),
        (ACCESSO_RUOLI, "Ruoli ACL specifici"),
    ]

    accesso = models.CharField(max_length=20, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    ruolo_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista ruolo_id ACL legacy abilitati (usato solo se accesso=RUOLI)",
    )

    class Meta:
        verbose_name = "Permessi visite mediche"
        verbose_name_plural = "Permessi visite mediche"

    def __str__(self) -> str:
        return f"Permessi visite mediche ({self.get_accesso_display()})"

    @classmethod
    def get_instance(cls) -> "AnagraficaVisiteMedichePermission":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"accesso": cls.ACCESSO_ADMIN})
        return obj


# ---------------------------------------------------------------------------
# Modelli safety (FattoreRischio / CategoriaCorso / EsposizioneRischio) e
# Modelli formazione HR (file separati — non modificare l'ordine).
# `models_rischi` viene PRIMA di `models_formazione` perché `TrainingCourse`
# referenzia `CategoriaCorso`.
# ---------------------------------------------------------------------------

from .models_rischi import *      # noqa: E402, F401, F403
from .models_formazione import *  # noqa: E402, F401, F403
