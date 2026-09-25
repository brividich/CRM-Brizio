"""Sistema di gestione: Dichiarazione di applicabilità ISO 27001 (MOD.165) e threat intelligence.

La SoA replica il foglio «Control Matrix» del MOD.165 - RAR: per ogni controllo
dell'Allegato A il livello di applicazione (0-4, 4 = pienamente applicato, 0 =
non applicato/escluso), la vulnerabilità residua, i riferimenti documentali, la
giustificazione e la fonte dell'obbligo; in più l'azione del piano di
trattamento (foglio «Threat Monitoring»), collegabile a una voce del Registro OFI.

Ogni revisione è un documento: si prepara in bozza, si propone, la approva la
Direzione. Una revisione approvata non si modifica più; la successiva nasce
come copia.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .catalogo_27002 import TEMI
from .storage import PrivateSistemaGestioneStorage


class ControlloIso27002(models.Model):
    codice = models.CharField(max_length=8, unique=True)
    tema = models.CharField(max_length=3, choices=TEMI)
    titolo = models.CharField(max_length=200)
    ordine = models.PositiveIntegerField(db_index=True)

    class Meta:
        ordering = ["ordine"]
        verbose_name = "Controllo ISO/IEC 27002"
        verbose_name_plural = "Controlli ISO/IEC 27002"

    def __str__(self) -> str:
        return f"{self.codice} {self.titolo}"


class SoaRevisione(models.Model):
    STATO_BOZZA = "BOZZA"
    STATO_PROPOSTA = "PROPOSTA"
    STATO_APPROVATA = "APPROVATA"
    STATO_SUPERATA = "SUPERATA"
    STATO_CHOICES = [
        (STATO_BOZZA, "Bozza"),
        (STATO_PROPOSTA, "Proposta alla Direzione"),
        (STATO_APPROVATA, "Approvata (in vigore)"),
        (STATO_SUPERATA, "Superata"),
    ]
    STATI_MODIFICABILI = (STATO_BOZZA,)

    numero = models.PositiveIntegerField(unique=True, help_text="Indice di revisione del MOD.165")
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_BOZZA, db_index=True)
    motivo = models.CharField(max_length=255, blank=True, default="", help_text="Descrizione della revisione")
    origine = models.CharField(max_length=255, blank=True, default="", help_text="Es. import dal PDF MOD.165")

    preparata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    proposta_il = models.DateTimeField(null=True, blank=True)
    approvata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    approvata_il = models.DateTimeField(null=True, blank=True)

    copia_firmata = models.FileField(
        upload_to="sistema_gestione/soa/%Y/", storage=PrivateSistemaGestioneStorage(), blank=True,
    )
    copia_firmata_nome = models.CharField(max_length=255, blank=True, default="")
    copia_firmata_caricata_il = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-numero"]
        verbose_name = "Revisione SoA"
        verbose_name_plural = "Revisioni SoA"

    def __str__(self) -> str:
        return f"SoA Rev.{self.numero} ({self.get_stato_display()})"

    @property
    def modificabile(self) -> bool:
        return self.stato in self.STATI_MODIFICABILI


class SoaVoce(models.Model):
    LIVELLO_CHOICES = [
        (0, "0 - Non applicato"),
        (1, "1"),
        (2, "2"),
        (3, "3"),
        (4, "4 - Pienamente applicato"),
    ]
    VULNERABILITA_CHOICES = [(0, "0"), (1, "1 - Bassa"), (2, "2"), (3, "3"), (4, "4 - Alta")]
    # Corrispondenza usata dal MOD.165: più il controllo è applicato, più bassa la vulnerabilità.
    VULNERABILITA_DA_LIVELLO = {0: 0, 1: 4, 2: 3, 3: 2, 4: 1}

    revisione = models.ForeignKey(SoaRevisione, on_delete=models.CASCADE, related_name="voci")
    controllo = models.ForeignKey(ControlloIso27002, on_delete=models.PROTECT, related_name="voci")
    livello = models.PositiveSmallIntegerField(choices=LIVELLO_CHOICES, default=0)
    vulnerabilita = models.PositiveSmallIntegerField(choices=VULNERABILITA_CHOICES, default=0)
    riferimenti = models.TextField(blank=True, default="", help_text="Procedure, moduli, evidenze interne")
    giustificazione = models.TextField(blank=True, default="", help_text="Motivo dell'inclusione o dell'esclusione")

    # «Required by» del MOD.165
    obbligo_legislativo = models.BooleanField(default=False)
    obbligo_normativo = models.BooleanField(default=False)
    obbligo_regolatorio = models.BooleanField(default=False)
    obbligo_cliente = models.BooleanField(default=False)
    buona_pratica = models.BooleanField(default=False)

    # Piano di trattamento (foglio «Threat Monitoring»)
    azione = models.TextField(blank=True, default="")
    responsabile = models.CharField(max_length=150, blank=True, default="")
    scadenza = models.DateField(null=True, blank=True)
    livello_atteso = models.PositiveSmallIntegerField(choices=LIVELLO_CHOICES, null=True, blank=True)
    ofi = models.ForeignKey(
        "gestione_specifiche.RegistroOFI", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    aggiornata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["controllo__ordine"]
        constraints = [
            models.UniqueConstraint(fields=["revisione", "controllo"], name="sg_soa_voce_unica_per_revisione"),
        ]
        verbose_name = "Voce SoA"
        verbose_name_plural = "Voci SoA"

    def __str__(self) -> str:
        return f"Rev.{self.revisione.numero} · {self.controllo.codice}"

    @property
    def applicabile(self) -> bool:
        return self.livello > 0

    @property
    def obblighi_label(self) -> str:
        etichette = [
            label for flag, label in (
                (self.obbligo_legislativo, "Legislativo"),
                (self.obbligo_normativo, "Normativo"),
                (self.obbligo_regolatorio, "Regolatorio"),
                (self.obbligo_cliente, "Cliente"),
                (self.buona_pratica, "Buona pratica"),
            ) if flag
        ]
        return ", ".join(etichette)

    @property
    def ha_azione_aperta(self) -> bool:
        return bool((self.azione or "").strip()) and (self.livello_atteso is None or self.livello < self.livello_atteso)

    def azione_scaduta(self, oggi=None) -> bool:
        oggi = oggi or timezone.localdate()
        return self.ha_azione_aperta and bool(self.scadenza) and self.scadenza < oggi


class ThreatIntelligence(models.Model):
    """Registro annuale delle attività di threat intelligence (MOD.165, ultimo foglio; controllo 5.7)."""

    ESITO_ACQUISITA = "ACQUISITA"
    ESITO_NON_PERTINENTE = "NON_PERTINENTE"
    ESITO_AZIONE = "AZIONE"
    ESITO_CHOICES = [
        (ESITO_ACQUISITA, "Informazione acquisita"),
        (ESITO_NON_PERTINENTE, "Non pertinente"),
        (ESITO_AZIONE, "Richiede azione"),
    ]

    data = models.DateField(default=timezone.localdate, db_index=True)
    fonte = models.CharField(max_length=150)
    informazione = models.TextField(help_text="Informazione o minaccia")
    esito = models.CharField(max_length=15, choices=ESITO_CHOICES, default=ESITO_ACQUISITA)
    azione = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    ofi = models.ForeignKey(
        "gestione_specifiche.RegistroOFI", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    registrato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]
        verbose_name = "Attività di threat intelligence"
        verbose_name_plural = "Registro threat intelligence"

    def __str__(self) -> str:
        return f"{self.data:%d/%m/%Y} · {self.fonte}"
