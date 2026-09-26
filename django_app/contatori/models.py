"""Modelli per la centrale MFC e il monitoraggio SNMP read-only."""
from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

# I quattro contatori usati ovunque: (campo, etichetta)
CONTATORI = (("a4_bn", "A4 BN"), ("a3_bn", "A3 BN"),
             ("a4_col", "A4 COL"), ("a3_col", "A3 COL"))


class StatoSNMP(models.TextChoices):
    MAI = "MAI", "Mai interrogato"
    OK = "OK", "Operativo"
    WARNING = "WARNING", "Attenzione"
    ERROR = "ERROR", "Errore"


class Macchina(models.Model):
    """Una multifunzione. Macchine con lo stesso `contratto` sono fatturate in pool."""
    class Fornitore(models.TextChoices):
        BASE = "BASE", "BASE SPA"
        COPYLAB = "COPYLAB", "Copylab"

    class Modello(models.TextChoices):
        """Modelli con una counter_map SNMP verificata (vedi snmp.COUNTER_MAP).

        Validato di proposito: con testo libero si poteva inserire la marca
        ('CANON') o un typo, e la lookup esatta su COUNTER_MAP falliva a runtime.
        Aggiungere un modello qui SOLO dopo aver verificato i numeri contatore
        (management command `snmp_discover`), altrimenti si leggono contatori
        sbagliati e la riconciliazione fatture ne risente.
        """
        C5535I = "iR-ADV C5535i", "Canon iR-ADV C5535i"
        DX_C5840I = "iR-ADV DX C5840i", "Canon iR-ADV DX C5840i"
        DX_C3822I = "iR-ADV DX C3822i", "Canon iR-ADV DX C3822i"

    reparto = models.CharField(max_length=60)
    matricola = models.CharField(max_length=40, unique=True)
    modello = models.CharField(max_length=60, blank=True, choices=Modello.choices,
                               help_text="Modello con contatori SNMP mappati. "
                                         "Non inserire la marca: serve il modello esatto.")
    contratto = models.CharField(max_length=20, blank=True,
                                 help_text="Stesso contratto = fatturazione in pool")
    fornitore = models.CharField(max_length=10, choices=Fornitore.choices,
                                 default=Fornitore.BASE)
    host = models.GenericIPAddressField(null=True, blank=True,
                                        help_text="IP per lettura SNMP")
    attiva = models.BooleanField(default=True)
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="contatori_macchine",
        help_text="Asset del registro HUB collegato (match matricola↔serial / host↔IP).",
    )
    snmp_stato = models.CharField(
        max_length=10, choices=StatoSNMP.choices, default=StatoSNMP.MAI,
    )
    snmp_ultimo_controllo = models.DateTimeField(null=True, blank=True)
    snmp_tempo_risposta_ms = models.PositiveIntegerField(null=True, blank=True)
    snmp_ultimo_errore = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["reparto"]
        verbose_name_plural = "Macchine"

    def __str__(self):
        return f"{self.reparto} ({self.matricola})"


class DispositivoSNMP(models.Model):
    """Nodo SNMP generico monitorato dalla centrale.

    Le credenziali restano nel singleton :class:`ImpostazioniSNMP`: il record
    non replica community o segreti e tutte le operazioni sono esclusivamente GET.
    """

    class Categoria(models.TextChoices):
        LETTORE = "LETTORE", "Lettore / terminale"
        STAMPANTE = "STAMPANTE", "Stampante / MFC extra"
        RETE = "RETE", "Rete"
        UPS = "UPS", "UPS / alimentazione"
        AMBIENTE = "AMBIENTE", "Sensore ambiente"
        ALTRO = "ALTRO", "Altro dispositivo"

    class Versione(models.TextChoices):
        GLOBALE = "", "Usa configurazione globale"
        V1 = "v1", "SNMPv1"
        V2C = "v2c", "SNMPv2c"

    nome = models.CharField(max_length=100)
    categoria = models.CharField(
        max_length=16, choices=Categoria.choices, default=Categoria.LETTORE,
    )
    host = models.GenericIPAddressField(unique=True)
    porta = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text="Vuoto = porta SNMP globale.",
    )
    versione = models.CharField(
        max_length=4, blank=True, choices=Versione.choices,
        help_text="Vuoto = versione SNMP globale.",
    )
    posizione = models.CharField(max_length=120, blank=True)
    produttore = models.CharField(max_length=80, blank=True)
    modello = models.CharField(max_length=120, blank=True)
    matricola = models.CharField(max_length=80, blank=True)
    note = models.TextField(blank=True)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dispositivi_snmp",
    )
    attivo = models.BooleanField(default=True)
    snmp_stato = models.CharField(
        max_length=10, choices=StatoSNMP.choices, default=StatoSNMP.MAI,
    )
    snmp_ultimo_controllo = models.DateTimeField(null=True, blank=True)
    snmp_tempo_risposta_ms = models.PositiveIntegerField(null=True, blank=True)
    snmp_ultimo_errore = models.CharField(max_length=500, blank=True)
    sys_name = models.CharField(max_length=255, blank=True)
    sys_description = models.TextField(blank=True)
    sys_object_id = models.CharField(max_length=255, blank=True)
    sys_uptime_seconds = models.PositiveBigIntegerField(null=True, blank=True)
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria", "nome"]
        verbose_name = "Dispositivo SNMP"
        verbose_name_plural = "Dispositivi SNMP"

    def __str__(self):
        return f"{self.nome} ({self.host})"


_oid_validator = RegexValidator(
    regex=r"^\d+(?:\.\d+)+$",
    message="Inserisci un OID numerico puntato, ad esempio 1.3.6.1.2.1.1.3.0.",
)


class SondaSNMP(models.Model):
    """Lettore configurabile di un singolo OID su un dispositivo."""

    class TipoValore(models.TextChoices):
        NUMERO = "NUMERO", "Numero"
        TESTO = "TESTO", "Testo"
        TIMETICKS = "TIMETICKS", "Tempo (TimeTicks)"

    dispositivo = models.ForeignKey(
        DispositivoSNMP, on_delete=models.CASCADE, related_name="sonde",
    )
    nome = models.CharField(max_length=100)
    oid = models.CharField(max_length=255, validators=[_oid_validator])
    tipo_valore = models.CharField(
        max_length=10, choices=TipoValore.choices, default=TipoValore.NUMERO,
    )
    unita = models.CharField(max_length=24, blank=True)
    fattore = models.DecimalField(
        max_digits=14, decimal_places=6, default=Decimal("1"),
        help_text="Moltiplicatore applicato al valore numerico grezzo.",
    )
    soglia_warning_min = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    soglia_warning_max = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    soglia_critica_min = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    soglia_critica_max = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True,
    )
    attiva = models.BooleanField(default=True)
    ordine = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordine", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["dispositivo", "oid"], name="contatori_sonda_oid_unico",
            ),
        ]
        verbose_name = "Sonda SNMP"
        verbose_name_plural = "Sonde SNMP"

    def __str__(self):
        return f"{self.dispositivo.nome} · {self.nome}"

    def stato_per_valore(self, valore):
        if valore is None:
            return StatoSNMP.ERROR
        if ((self.soglia_critica_min is not None and valore < self.soglia_critica_min)
                or (self.soglia_critica_max is not None and valore > self.soglia_critica_max)):
            return StatoSNMP.ERROR
        if ((self.soglia_warning_min is not None and valore < self.soglia_warning_min)
                or (self.soglia_warning_max is not None and valore > self.soglia_warning_max)):
            return StatoSNMP.WARNING
        return StatoSNMP.OK


class RilevazioneSNMP(models.Model):
    """Esito immutabile di un'interrogazione di un dispositivo generico."""

    dispositivo = models.ForeignKey(
        DispositivoSNMP, on_delete=models.CASCADE, related_name="rilevazioni",
    )
    rilevata_il = models.DateTimeField(default=timezone.now, db_index=True)
    stato = models.CharField(max_length=10, choices=StatoSNMP.choices)
    tempo_risposta_ms = models.PositiveIntegerField(null=True, blank=True)
    errore = models.CharField(max_length=500, blank=True)
    sys_name = models.CharField(max_length=255, blank=True)
    sys_description = models.TextField(blank=True)
    sys_object_id = models.CharField(max_length=255, blank=True)
    sys_uptime_seconds = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-rilevata_il", "-pk"]
        verbose_name = "Rilevazione SNMP"
        verbose_name_plural = "Rilevazioni SNMP"


class ValoreSNMP(models.Model):
    """Valore storicizzato di una sonda durante una rilevazione."""

    rilevazione = models.ForeignKey(
        RilevazioneSNMP, on_delete=models.CASCADE, related_name="valori",
    )
    sonda = models.ForeignKey(
        SondaSNMP, on_delete=models.CASCADE, related_name="valori",
    )
    valore_numero = models.DecimalField(
        max_digits=30, decimal_places=6, null=True, blank=True,
    )
    valore_testo = models.TextField(blank=True)
    stato = models.CharField(max_length=10, choices=StatoSNMP.choices)
    errore = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["sonda__ordine", "sonda__nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["rilevazione", "sonda"], name="contatori_valore_sonda_rilevazione_unico",
            ),
        ]
        verbose_name = "Valore SNMP"
        verbose_name_plural = "Valori SNMP"

    @property
    def valore_display(self):
        if self.valore_numero is not None:
            valore = format(self.valore_numero.normalize(), "f")
            return f"{valore} {self.sonda.unita}".strip()
        return self.valore_testo or "—"


class LetturaContatori(models.Model):
    """Snapshot dei 4 contatori di una macchina in un dato trimestre."""
    class Fonte(models.TextChoices):
        SNMP = "SNMP", "SNMP"
        MANUALE = "MANUALE", "Manuale"
        FATTURA = "FATTURA", "Da fattura"

    macchina = models.ForeignKey(Macchina, on_delete=models.CASCADE, related_name="letture")
    trimestre = models.CharField(max_length=8, help_text='Es. "2026-Q2"')
    data = models.DateField(help_text="Data della rilevazione")
    a4_bn = models.PositiveIntegerField(default=0)
    a3_bn = models.PositiveIntegerField(default=0)
    a4_col = models.PositiveIntegerField(default=0)
    a3_col = models.PositiveIntegerField(default=0)
    fonte = models.CharField(max_length=10, choices=Fonte.choices, default=Fonte.MANUALE)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-trimestre", "macchina__reparto"]
        unique_together = ("macchina", "trimestre")
        verbose_name = "Lettura contatori"
        verbose_name_plural = "Letture contatori"

    def __str__(self):
        return f"{self.macchina.reparto} {self.trimestre}"

    @property
    def totale(self):
        return self.a4_bn + self.a3_bn + self.a4_col + self.a3_col


class Fattura(models.Model):
    """Testata fattura fornitore relativa a un trimestre."""
    numero = models.CharField(max_length=30)
    data = models.DateField()
    fornitore = models.CharField(max_length=10, default="BASE")
    trimestre = models.CharField(max_length=8, help_text='Es. "2026-Q2"')
    periodo_dal = models.DateField(null=True, blank=True)
    periodo_al = models.DateField(help_text="Data di chiusura letture fornitore")

    class Meta:
        ordering = ["-periodo_al"]
        unique_together = ("numero", "trimestre")

    def __str__(self):
        return f"{self.numero} ({self.trimestre})"


class ImpostazioniSNMP(models.Model):
    """Parametri SNMP globali della flotta. Singleton: esiste una sola riga (pk=1)."""
    class Versione(models.TextChoices):
        V1 = "v1", "SNMPv1"
        V2C = "v2c", "SNMPv2c"

    community = models.CharField(max_length=60, default="novicromprinter",
                                 help_text="Nome community/gruppo SNMP (in lettura)")
    port = models.PositiveIntegerField(default=161)
    timeout = models.PositiveIntegerField(default=3, help_text="Secondi di attesa per macchina")
    version = models.CharField(max_length=4, choices=Versione.choices, default=Versione.V1)

    class Meta:
        verbose_name = "Impostazioni SNMP"
        verbose_name_plural = "Impostazioni SNMP"

    def __str__(self):
        return f"SNMP {self.version} · {self.community}:{self.port}"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RigaFattura(models.Model):
    """
    Un'unità di fatturazione (un contratto) con le letture del fornitore alla
    chiusura del periodo. Per il pool 2020/124 la riga contiene le letture cumulate
    di CQF+CQI, come le stampa la fattura.
    """
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="righe")
    contratto = models.CharField(max_length=20)
    descrizione = models.CharField(max_length=120, blank=True)
    a4_bn = models.PositiveIntegerField(default=0)
    a3_bn = models.PositiveIntegerField(default=0)
    a4_col = models.PositiveIntegerField(default=0)
    a3_col = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["contratto"]
        unique_together = ("fattura", "contratto")
        verbose_name = "Riga fattura"
        verbose_name_plural = "Righe fattura"

    def __str__(self):
        return f"{self.fattura.numero} · {self.contratto}"
