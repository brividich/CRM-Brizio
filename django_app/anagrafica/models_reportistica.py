"""Reportistica componibile di anagrafica: modelli salvati, blocchi, archivio.

Un *modello* e' un documento pronto all'uso (es. «Qualifica del personale per
cliente», «Parità di genere UNI/PdR 125»): intestazione, perimetro di persone,
periodo e una sequenza ordinata di *blocchi* (testo libero, sezione dati,
interruzione di pagina, firme). La generazione legge i dati vivi del portale e
produce PDF/Excel; ogni file consegnato resta nell'*archivio* con chi l'ha
generato e con quali parametri (evidenza per audit e per il cliente).

I JSONField contengono sempre dict/list, mai scalari: SQL Server li protegge con
un vincolo ISJSON che rifiuta i valori scalari.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

__all__ = ["ReportModello", "ReportBlocco", "ReportGenerato"]


class ReportModello(models.Model):
    PERIODO_ULTIMI_12_MESI = "ULTIMI_12_MESI"
    PERIODO_ANNO_CORRENTE = "ANNO_CORRENTE"
    PERIODO_ANNO_PRECEDENTE = "ANNO_PRECEDENTE"
    PERIODO_TRIMESTRE_PRECEDENTE = "TRIMESTRE_PRECEDENTE"
    PERIODO_MESE_PRECEDENTE = "MESE_PRECEDENTE"
    PERIODO_PERSONALIZZATO = "PERSONALIZZATO"
    PERIODO_CHOICES = [
        (PERIODO_ULTIMI_12_MESI, "Ultimi 12 mesi"),
        (PERIODO_ANNO_CORRENTE, "Anno in corso"),
        (PERIODO_ANNO_PRECEDENTE, "Anno precedente"),
        (PERIODO_TRIMESTRE_PRECEDENTE, "Trimestre precedente"),
        (PERIODO_MESE_PRECEDENTE, "Mese precedente"),
        (PERIODO_PERSONALIZZATO, "Date personalizzate"),
    ]

    RISERVATEZZA_PUBBLICO = "PUBBLICO"
    RISERVATEZZA_INTERNO = "INTERNO"
    RISERVATEZZA_RISERVATO = "RISERVATO"
    RISERVATEZZA_PERSONALE = "DATI_PERSONALI"
    RISERVATEZZA_CHOICES = [
        (RISERVATEZZA_PUBBLICO, "Pubblico"),
        (RISERVATEZZA_INTERNO, "Uso interno"),
        (RISERVATEZZA_RISERVATO, "Riservato"),
        (RISERVATEZZA_PERSONALE, "Riservato – contiene dati personali"),
    ]

    nome = models.CharField(max_length=150)
    descrizione = models.CharField(max_length=300, blank=True, default="")
    codice_sistema = models.CharField(
        max_length=50, blank=True, default="", db_index=True,
        help_text="Valorizzato solo sui modelli predefiniti (ripristinabili).",
    )
    titolo_documento = models.CharField(max_length=200)
    sottotitolo = models.CharField(max_length=200, blank=True, default="")
    destinatario = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Cliente, ente di certificazione o funzione interna a cui è destinato il documento.",
    )
    norme = models.JSONField(default=list, blank=True)
    riservatezza = models.CharField(max_length=20, choices=RISERVATEZZA_CHOICES, default=RISERVATEZZA_INTERNO)
    periodo_tipo = models.CharField(max_length=25, choices=PERIODO_CHOICES, default=PERIODO_ULTIMI_12_MESI)
    data_da = models.DateField(null=True, blank=True)
    data_a = models.DateField(null=True, blank=True)
    filtri = models.JSONField(default=dict, blank=True)
    redatto_da = models.CharField(max_length=120, blank=True, default="")
    verificato_da = models.CharField(max_length=120, blank=True, default="")
    approvato_da = models.CharField(max_length=120, blank=True, default="")

    # ── Impaginazione e controllo documentale ──
    ORIENTAMENTO_ORIZZONTALE = "ORIZZONTALE"
    ORIENTAMENTO_VERTICALE = "VERTICALE"
    ORIENTAMENTO_CHOICES = [(ORIENTAMENTO_ORIZZONTALE, "Orizzontale"), (ORIENTAMENTO_VERTICALE, "Verticale")]
    FORMATO_CHOICES = [("pdf", "PDF"), ("xlsx", "Excel")]

    codice_documento = models.CharField(max_length=50, blank=True, default="",
                                        help_text="Codice del modulo di sistema, es. MOD.230.")
    revisione = models.CharField(max_length=20, blank=True, default="")
    orientamento = models.CharField(max_length=12, choices=ORIENTAMENTO_CHOICES, default=ORIENTAMENTO_ORIZZONTALE)
    formato_predefinito = models.CharField(max_length=5, choices=FORMATO_CHOICES, default="pdf")
    mostra_frontespizio = models.BooleanField(default=True)
    mostra_indice = models.BooleanField(default=False)
    mostra_riferimenti = models.BooleanField(default=True)
    mostra_note_calcolo = models.BooleanField(default=True)
    filigrana = models.CharField(max_length=40, blank=True, default="", help_text="Es. BOZZA o COPIA NON CONTROLLATA.")
    piede_pagina = models.CharField(max_length=200, blank=True, default="")
    nome_file = models.CharField(max_length=150, blank=True, default="",
                                 help_text="Ammessi i segnaposto, es. {titolo}_{destinatario}_{data}.")
    excel_foglio_indicatori = models.BooleanField(default=True)
    excel_foglio_documento = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "Modello di report"
        verbose_name_plural = "Modelli di report"

    def __str__(self) -> str:
        return self.nome


class ReportBlocco(models.Model):
    TIPO_TESTO = "TESTO"
    TIPO_SEZIONE = "SEZIONE"
    TIPO_PAGINA = "PAGINA"
    TIPO_FIRME = "FIRME"
    TIPO_CHOICES = [
        (TIPO_TESTO, "Testo libero"),
        (TIPO_SEZIONE, "Sezione dati"),
        (TIPO_PAGINA, "Interruzione di pagina"),
        (TIPO_FIRME, "Riquadro firme"),
    ]

    modello = models.ForeignKey(ReportModello, on_delete=models.CASCADE, related_name="blocchi")
    ordine = models.PositiveIntegerField(default=0)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default=TIPO_TESTO)
    titolo = models.CharField(max_length=200, blank=True, default="")
    testo = models.TextField(blank=True, default="")
    sezione = models.CharField(max_length=60, blank=True, default="")
    # {"colonne": [...], "mostra_indicatori": bool, "mostra_tabella": bool, "mostra_note": bool}
    opzioni = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name = "Blocco di report"
        verbose_name_plural = "Blocchi di report"

    def __str__(self) -> str:
        return f"{self.modello_id}#{self.ordine} {self.tipo}"


class ReportGenerato(models.Model):
    FORMATO_PDF = "pdf"
    FORMATO_XLSX = "xlsx"
    FORMATO_CHOICES = [(FORMATO_PDF, "PDF"), (FORMATO_XLSX, "Excel")]

    modello = models.ForeignKey(
        ReportModello, on_delete=models.SET_NULL, null=True, blank=True, related_name="generati",
    )
    modello_nome = models.CharField(max_length=150, blank=True, default="")
    titolo = models.CharField(max_length=200)
    destinatario = models.CharField(max_length=200, blank=True, default="")
    formato = models.CharField(max_length=5, choices=FORMATO_CHOICES)
    data_da = models.DateField(null=True, blank=True)
    data_a = models.DateField(null=True, blank=True)
    parametri = models.JSONField(default=dict, blank=True)
    contiene_dati_personali = models.BooleanField(default=False)
    nome_file = models.CharField(max_length=200)
    contenuto = models.BinaryField()
    dimensione = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=300, blank=True, default="")
    generato_il = models.DateTimeField(auto_now_add=True, db_index=True)
    generato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-generato_il", "-id"]
        verbose_name = "Report generato"
        verbose_name_plural = "Report generati"

    def __str__(self) -> str:
        return self.nome_file
