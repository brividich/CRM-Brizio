"""Modelli per la gestione contatori MFC Canon e riconciliazione fatture."""
from django.db import models

# I quattro contatori usati ovunque: (campo, etichetta)
CONTATORI = (("a4_bn", "A4 BN"), ("a3_bn", "A3 BN"),
             ("a4_col", "A4 COL"), ("a3_col", "A3 COL"))


class Macchina(models.Model):
    """Una multifunzione. Macchine con lo stesso `contratto` sono fatturate in pool."""
    class Fornitore(models.TextChoices):
        BASE = "BASE", "BASE SPA"
        COPYLAB = "COPYLAB", "Copylab"

    reparto = models.CharField(max_length=60)
    matricola = models.CharField(max_length=40, unique=True)
    modello = models.CharField(max_length=60, blank=True)
    contratto = models.CharField(max_length=20, blank=True,
                                 help_text="Stesso contratto = fatturazione in pool")
    fornitore = models.CharField(max_length=10, choices=Fornitore.choices,
                                 default=Fornitore.BASE)
    host = models.GenericIPAddressField(null=True, blank=True,
                                        help_text="IP per lettura SNMP")
    attiva = models.BooleanField(default=True)

    class Meta:
        ordering = ["reparto"]
        verbose_name_plural = "Macchine"

    def __str__(self):
        return f"{self.reparto} ({self.matricola})"


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
