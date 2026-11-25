"""Documenti di produzione degli OP.

Gli OP stanno nella tabella ``ordini_produzione`` (vedi ``core/ordini_produzione.py``),
che non appartiene a nessun modulo: qui un documento cita l'OP col suo titolo, come
fanno Gestione anomalie e il Registro FAI. I FAI restano nel Registro FAI e la scheda
dell'OP li mostra insieme a questi documenti.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class TipoDocumento(models.Model):
    """Tipi di documento di produzione, decisi in Impostazioni."""

    etichetta = models.CharField(max_length=80, unique=True)
    descrizione = models.CharField(max_length=255, blank=True, default="")
    ordine = models.PositiveIntegerField(default=100)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "etichetta"]
        verbose_name = "Tipo di documento di produzione"
        verbose_name_plural = "Tipi di documento di produzione"

    def __str__(self) -> str:
        return self.etichetta


class DocumentoOP(models.Model):
    op = models.CharField(max_length=100, db_index=True, verbose_name="OP")
    tipo = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name="documenti")
    titolo = models.CharField(max_length=200, blank=True, default="", verbose_name="Titolo o numero")
    revisione = models.CharField(max_length=40, blank=True, default="", verbose_name="Rev.")
    data = models.DateField(null=True, blank=True, verbose_name="Data")
    percorso = models.CharField(max_length=500, blank=True, default="", verbose_name="Cartella o file di rete")
    note = models.TextField(blank=True, default="", max_length=2000)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    creato_il = models.DateTimeField(auto_now_add=True)
    modificato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tipo__ordine", "tipo__etichetta", "-data", "-id"]
        verbose_name = "Documento di produzione"
        verbose_name_plural = "Documenti di produzione"

    def __str__(self) -> str:
        return f"{self.tipo} {self.titolo}".strip()


class CartellaReportCMM(models.Model):
    """Cartella di un P/N nella share dei report CMM e quando è stata letta l'ultima volta."""

    pn = models.CharField(max_length=100, db_index=True, verbose_name="P/N")
    percorso = models.CharField(max_length=500, unique=True)
    letta_il = models.DateTimeField(null=True, blank=True)
    errore = models.CharField(max_length=300, blank=True, default="")
    in_lettura_dal = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Cartella report CMM"
        verbose_name_plural = "Cartelle report CMM"

    def __str__(self) -> str:
        return self.percorso


class ReportCMM(models.Model):
    """Un report CMM in PDF della share, letto con il lettore di Gestione anomalie."""

    cartella = models.ForeignKey(CartellaReportCMM, on_delete=models.CASCADE, related_name="report")
    pn = models.CharField(max_length=100, db_index=True, verbose_name="P/N")
    op = models.CharField(max_length=100, db_index=True, blank=True, default="", verbose_name="OP")
    percorso = models.CharField(max_length=500, unique=True)
    file = models.CharField(max_length=255)
    dimensione = models.BigIntegerField(default=0)
    modificato = models.FloatField(default=0)
    fase = models.CharField(max_length=40, blank=True, default="")
    programma = models.CharField(max_length=200, blank=True, default="", verbose_name="Programma")
    programma_base = models.CharField(max_length=200, blank=True, default="", db_index=True,
                                      verbose_name="Programma senza revisione")
    seriale = models.CharField(max_length=100, blank=True, default="", verbose_name="S/N")
    data = models.DateField(null=True, blank=True)
    pn_report = models.CharField(max_length=100, blank=True, default="", verbose_name="P/N nel report")
    righe = models.PositiveIntegerField(default=0)
    fuori = models.PositiveIntegerField(default=0)
    da_verificare = models.PositiveIntegerField(default=0)
    errore = models.CharField(max_length=300, blank=True, default="")
    letto_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data", "-id"]
        indexes = [models.Index(fields=["pn", "programma_base"], name="prod_rcmm_pn_prog")]
        verbose_name = "Report CMM"
        verbose_name_plural = "Report CMM"

    def __str__(self) -> str:
        return self.file


class MisuraCMM(models.Model):
    """Una riga di misura di un report CMM. ``chiave`` = nome della quota senza spazi, maiuscolo."""

    report = models.ForeignKey(ReportCMM, on_delete=models.CASCADE, related_name="misure")
    indice = models.PositiveIntegerField(default=0)
    pagina = models.PositiveIntegerField(default=0)
    sezione = models.CharField(max_length=200, blank=True, default="")
    nome = models.CharField(max_length=200)
    chiave = models.CharField(max_length=200, db_index=True)
    tipo = models.CharField(max_length=40, blank=True, default="")
    misurato = models.FloatField()
    nominale = models.FloatField()
    tol_sup = models.FloatField()
    tol_inf = models.FloatField(help_text="Col suo segno: limite inferiore = nominale + tol_inf.")
    fuori = models.BooleanField(default=False)
    fuori_di = models.FloatField(null=True, blank=True)
    da_verificare = models.BooleanField(default=False)

    class Meta:
        ordering = ["report_id", "indice"]
        verbose_name = "Misura CMM"
        verbose_name_plural = "Misure CMM"

    def __str__(self) -> str:
        return self.nome
