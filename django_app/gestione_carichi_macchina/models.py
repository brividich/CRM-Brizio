"""Modello dati dell'app Gestione Carichi Macchina.

Profilo di pianificazione che si APPOGGIA agli asset esistenti (assets.Asset):
le macchine NON sono una nuova anagrafica, l'app referenzia l'asset via OneToOne in
sola lettura e aggiunge solo gli attributi di pianificazione.

Vincoli SQL Server (mssql-django) rispettati:
- nessun indice parziale / UniqueConstraint con condition;
- nessun ArrayField (le liste di alias stanno in tabelle dedicate);
- nessun campo unique nullable (su SQL Server ammette un solo NULL: evitato).
I test girano su sqlite (DB_ENGINE=sqlite).
"""
from decimal import Decimal

from django.db import models


class Macchina(models.Model):
    """Profilo di pianificazione di una macchina.

    L'identita' (codice, descrizione, reparto, costruttore) vive sull'asset e si
    LEGGE da li': qui non si duplica. Si aggiungono solo attributi di pianificazione.
    """

    CAT_4AXIS = "4_axis"
    CAT_5AXIS = "5_axis"
    CAT_TORNI = "torni"
    CAT_TORNI_FRESA = "torni_fresa"
    CAT_ALESATRICI = "alesatrici"
    CATEGORIA_CHOICES = [
        (CAT_4AXIS, "Macchine 4 assi"),
        (CAT_5AXIS, "Macchine 5 assi"),
        (CAT_TORNI, "Torni"),
        (CAT_TORNI_FRESA, "Torni fresa"),
        (CAT_ALESATRICI, "Alesatrici"),
    ]

    ATTACCO_HSK = "HSK"
    ATTACCO_ISO40 = "ISO40"
    ATTACCO_NA = "-"
    ATTACCO_CHOICES = [
        (ATTACCO_HSK, "HSK"),
        (ATTACCO_ISO40, "ISO40"),
        (ATTACCO_NA, "Non applicabile"),
    ]

    STATO_ATTIVA = "attiva"
    STATO_GUASTO = "guasto"
    STATO_MANUTENZIONE = "manutenzione"
    STATO_CHOICES = [
        (STATO_ATTIVA, "Attiva"),
        (STATO_GUASTO, "Guasto"),
        (STATO_MANUTENZIONE, "Manutenzione"),
    ]

    # Aggancio all'asset esistente (sola lettura, nessun coupling inverso).
    # PROTECT: non lasciare che la cancellazione di un asset elimini in silenzio il
    # piano collegato; il problema va reso esplicito.
    asset = models.OneToOneField(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="profilo_carichi",
        help_text="Asset esistente che questa riga di pianificazione rappresenta.",
    )

    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, db_index=True)
    attacco = models.CharField(max_length=8, choices=ATTACCO_CHOICES, default=ATTACCO_NA)
    n_assi = models.PositiveSmallIntegerField(null=True, blank=True)
    ha_turno_notte = models.BooleanField(default=False)
    ore_giorno_disponibili = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal("8.0")
    )

    # Stato di pianificazione LOCALE: non viene scritto sull'asset. In futuro potra'
    # essere derivato da assets (Asset.status == IN_REPAIR, WorkOrder aperti,
    # MaintenanceRule): gancio predisposto, NON implementato ora.
    stato_pianificazione = models.CharField(
        max_length=16, choices=STATO_CHOICES, default=STATO_ATTIVA, db_index=True
    )

    # Ordine della riga dentro la sezione, per replicare il layout del foglio Excel.
    ordine_sezione = models.PositiveIntegerField(default=0)
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Macchina (profilo carichi)"
        verbose_name_plural = "Macchine (profili carichi)"
        ordering = ["categoria", "ordine_sezione", "id"]
        indexes = [
            models.Index(fields=["categoria", "ordine_sezione"]),
        ]

    def __str__(self) -> str:
        return f"{self.codice} ({self.get_categoria_display()})"

    @property
    def codice(self) -> str:
        """Codice identificativo letto dall'asset (asset_tag)."""
        return self.asset.asset_tag if self.asset_id else ""

    @property
    def descrizione(self) -> str:
        """Descrizione/nome letti dall'asset."""
        return self.asset.name if self.asset_id else ""


class MacchinaAlias(models.Model):
    """Mappa un codice-officina del foglio (es. MZ5, DM3) verso una Macchina.

    Serve perche' i codici del foglio non hanno un campo unico autorevole negli
    asset (stanno parte in asset_tag, parte nel name, con formati incoerenti).
    """

    FONTE_ASSET_TAG = "asset_tag"
    FONTE_NAME = "name"
    FONTE_MANUALE = "manuale"
    FONTE_CHOICES = [
        (FONTE_ASSET_TAG, "Da asset_tag"),
        (FONTE_NAME, "Da name"),
        (FONTE_MANUALE, "Manuale"),
    ]

    macchina = models.ForeignKey(
        Macchina, on_delete=models.CASCADE, related_name="alias"
    )
    # Normalizzato a monte (uppercase, senza spazi). Globalmente univoco.
    codice_foglio = models.CharField(max_length=64, db_index=True)
    fonte = models.CharField(max_length=16, choices=FONTE_CHOICES, default=FONTE_MANUALE)
    da_confermare = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Alias macchina"
        verbose_name_plural = "Alias macchina"
        constraints = [
            models.UniqueConstraint(
                fields=["codice_foglio"], name="gcm_uniq_alias_codice_foglio"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.codice_foglio} -> {self.macchina_id}"


class FamigliaPezzo(models.Model):
    """Famiglia di pezzi (soprannome canonico: gimbal, sombrero, campane, ragni...)."""

    nome = models.CharField(max_length=80, unique=True)  # normalizzato lowercase
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Famiglia pezzo"
        verbose_name_plural = "Famiglie pezzo"
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome


class FamigliaAlias(models.Model):
    """Soprannome equivalente di una FamigliaPezzo (no array nativo su SQL Server)."""

    famiglia = models.ForeignKey(
        FamigliaPezzo, on_delete=models.CASCADE, related_name="alias"
    )
    alias = models.CharField(max_length=80, db_index=True)

    class Meta:
        verbose_name = "Alias famiglia"
        verbose_name_plural = "Alias famiglia"
        constraints = [
            models.UniqueConstraint(fields=["alias"], name="gcm_uniq_famiglia_alias"),
        ]

    def __str__(self) -> str:
        return f"{self.alias} -> {self.famiglia_id}"


class MacchinaFamigliaAffinita(models.Model):
    """Affinita' storica macchina<->famiglia (la 'memoria' del sistema).

    pool_equivalenza: etichetta condivisa dalle macchine intercambiabili sulla stessa
    famiglia (rilevato dall'importer, da confermare a mano).
    """

    macchina = models.ForeignKey(
        Macchina, on_delete=models.CASCADE, related_name="affinita"
    )
    famiglia = models.ForeignKey(
        FamigliaPezzo, on_delete=models.CASCADE, related_name="affinita"
    )
    occorrenze = models.PositiveIntegerField(default=0)
    ore_medie = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    ultima_data = models.DateField(null=True, blank=True)
    pool_equivalenza = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    da_confermare = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Affinita' macchina/famiglia"
        verbose_name_plural = "Affinita' macchina/famiglia"
        ordering = ["-occorrenze"]
        constraints = [
            models.UniqueConstraint(
                fields=["macchina", "famiglia"],
                name="gcm_uniq_affinita_macchina_famiglia",
            ),
        ]
        indexes = [
            models.Index(fields=["pool_equivalenza"]),
        ]

    def __str__(self) -> str:
        return f"{self.macchina_id}/{self.famiglia_id} x{self.occorrenze}"


class Commessa(models.Model):
    """Ordine/commessa dal backlog del foglio (cliente, quantita', pezzo, consegna)."""

    PRIORITA_BASSA = 1
    PRIORITA_NORMALE = 2
    PRIORITA_ALTA = 3
    PRIORITA_URGENTE = 4
    PRIORITA_CHOICES = [
        (PRIORITA_BASSA, "Bassa"),
        (PRIORITA_NORMALE, "Normale"),
        (PRIORITA_ALTA, "Alta"),
        (PRIORITA_URGENTE, "Urgente"),
    ]

    STATO_APERTA = "aperta"
    STATO_IN_CORSO = "in_corso"
    STATO_CHIUSA = "chiusa"
    STATO_SOSPESA = "sospesa"
    STATO_CHOICES = [
        (STATO_APERTA, "Aperta"),
        (STATO_IN_CORSO, "In corso"),
        (STATO_CHIUSA, "Chiusa"),
        (STATO_SOSPESA, "Sospesa"),
    ]

    # Non unique: il backlog reale e' free-form; la dedup la fa l'importer.
    numero = models.CharField(max_length=64, blank=True, default="", db_index=True)
    nome = models.CharField(max_length=200, blank=True, default="")
    cliente = models.CharField(max_length=200, blank=True, default="")
    pezzo = models.CharField(max_length=200, blank=True, default="")
    quantita = models.PositiveIntegerField(null=True, blank=True)
    data_consegna = models.DateField(null=True, blank=True, db_index=True)
    priorita = models.PositiveSmallIntegerField(
        choices=PRIORITA_CHOICES, default=PRIORITA_NORMALE
    )
    stato = models.CharField(max_length=16, choices=STATO_CHOICES, default=STATO_APERTA)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Commessa"
        verbose_name_plural = "Commesse"
        ordering = ["-priorita", "data_consegna", "id"]

    def __str__(self) -> str:
        return self.numero or self.nome or f"Commessa #{self.pk}"


class CicloStandard(models.Model):
    """Routing standard di una famiglia (sequenza di Operazione). Sorgente: CICLI del foglio."""

    famiglia = models.ForeignKey(
        FamigliaPezzo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cicli",
    )
    codice = models.CharField(max_length=64, blank=True, default="", db_index=True)
    nome = models.CharField(max_length=200, blank=True, default="")
    note = models.TextField(blank=True, default="")
    attivo = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ciclo standard"
        verbose_name_plural = "Cicli standard"
        ordering = ["codice", "id"]

    def __str__(self) -> str:
        return self.codice or self.nome or f"Ciclo #{self.pk}"


class Operazione(models.Model):
    """Riga di un CicloStandard: op1, op2... con macchina preferita e alternative."""

    ciclo = models.ForeignKey(
        CicloStandard, on_delete=models.CASCADE, related_name="operazioni"
    )
    seq = models.PositiveSmallIntegerField(help_text="Numero op (op1, op2...).")
    macchina_preferita = models.ForeignKey(
        Macchina,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operazioni_preferite",
    )
    macchine_alternative = models.ManyToManyField(
        Macchina, blank=True, related_name="operazioni_alternative"
    )
    # Testo libero della regola di sostituzione (es. "DM3 oppure DM11 con stessi coni").
    regola_sostituzione = models.TextField(blank=True, default="")
    tempo_cent_cad = models.PositiveIntegerField(
        null=True, blank=True, help_text="Tempo standard in centesimi d'ora a pezzo."
    )
    note = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Operazione"
        verbose_name_plural = "Operazioni"
        ordering = ["ciclo", "seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["ciclo", "seq"], name="gcm_uniq_operazione_ciclo_seq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.ciclo_id} op{self.seq}"


class Pianificazione(models.Model):
    """La cella/barra del Gantt: un lavoro su una macchina in un giorno/turno.

    stato (workflow) e fase (lavorazione) sono DUE dimensioni ortogonali, campi distinti.
    """

    TURNO_GIORNO = "giorno"
    TURNO_NOTTE = "notte"
    TURNO_CHOICES = [
        (TURNO_GIORNO, "Giorno"),
        (TURNO_NOTTE, "Notte"),
    ]

    STATO_PIANIFICATA = "pianificata"
    STATO_IN_CORSO = "in_corso"
    STATO_COMPLETATA = "completata"
    STATO_CHOICES = [
        (STATO_PIANIFICATA, "Pianificata"),
        (STATO_IN_CORSO, "In corso"),
        (STATO_COMPLETATA, "Completata"),
    ]

    FASE_NA = ""
    FASE_SGR = "sgr"
    FASE_FIN = "fin"
    FASE_RIP = "rip"
    FASE_ASS = "ass"
    FASE_CHOICES = [
        (FASE_NA, "—"),
        (FASE_SGR, "Sgrossatura"),
        (FASE_FIN, "Finitura"),
        (FASE_RIP, "Ripresa"),
        (FASE_ASS, "Assemblaggio"),
    ]

    FONTE_IMPORT = "import"
    FONTE_MANUALE = "manuale"
    FONTE_AI = "ai"
    FONTE_CHOICES = [
        (FONTE_IMPORT, "Import"),
        (FONTE_MANUALE, "Manuale"),
        (FONTE_AI, "AI"),
    ]

    macchina = models.ForeignKey(
        Macchina, on_delete=models.CASCADE, related_name="pianificazioni"
    )
    data = models.DateField(db_index=True)
    turno = models.CharField(max_length=8, choices=TURNO_CHOICES, default=TURNO_GIORNO)

    commessa = models.ForeignKey(
        Commessa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pianificazioni",
    )
    operazione = models.ForeignKey(
        Operazione,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pianificazioni",
    )
    famiglia = models.ForeignKey(
        FamigliaPezzo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pianificazioni",
    )

    qta = models.PositiveIntegerField(null=True, blank=True)
    ore = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    stato = models.CharField(
        max_length=16, choices=STATO_CHOICES, default=STATO_PIANIFICATA, db_index=True
    )
    fase = models.CharField(max_length=8, choices=FASE_CHOICES, blank=True, default=FASE_NA)

    testo_originale = models.TextField(blank=True, default="")
    settimane_presente = models.PositiveIntegerField(default=1)
    fonte = models.CharField(max_length=8, choices=FONTE_CHOICES, default=FONTE_IMPORT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pianificazione"
        verbose_name_plural = "Pianificazioni"
        ordering = ["data", "macchina", "turno"]
        indexes = [
            models.Index(fields=["macchina", "data"]),
            models.Index(fields=["data", "turno"]),
        ]

    def __str__(self) -> str:
        return f"{self.macchina_id} {self.data} {self.turno}"
