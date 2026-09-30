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

import os

from django.core.exceptions import ValidationError
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


# ---------------------------------------------------------------------------
# Audit interni EN 9100 (MOD.034 / MOD.035A / MOD.035B)
# ---------------------------------------------------------------------------


def default_sede_audit() -> str:
    """Sede predefinita configurabile, senza incorporare dati aziendali nel codice."""
    return str(os.environ.get("SISTEMA_GESTIONE_AUDIT_SEDE", "") or "").strip()


class Auditor(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="qualifiche_auditor_sistema_gestione",
    )
    nome_esterno = models.CharField(max_length=200, blank=True, default="")
    ente_esterno = models.CharField(max_length=200, blank=True, default="")
    interno = models.BooleanField(default=True)
    req_diploma = models.BooleanField(default=False)
    req_norme = models.BooleanField(default=False)
    req_tecniche_audit = models.BooleanField(default=False)
    req_settore = models.BooleanField(default=False)
    req_esperienza_2_anni = models.BooleanField(default=False)
    requisiti_verificati_il = models.DateField(null=True, blank=True)
    audit_svolti_pregressi = models.PositiveIntegerField(default=0)
    approvato_ceo_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    approvato_ceo_il = models.DateTimeField(null=True, blank=True)
    formazione_processi_il = models.DateField(null=True, blank=True)
    attivo = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-attivo", "nome_esterno", "user__last_name", "user__first_name"]
        verbose_name = "Auditor interno/esterno"
        verbose_name_plural = "Auditor interni/esterni"

    def __str__(self) -> str:
        return self.nome

    def clean(self):
        super().clean()
        if self.interno and not self.user_id:
            raise ValidationError({"user": "Un auditor interno deve essere collegato a un utente del portale."})
        if not self.interno and not self.nome_esterno.strip():
            raise ValidationError({"nome_esterno": "Indica il nome dell'auditor esterno."})
        if not self.interno and not self.ente_esterno.strip():
            raise ValidationError({"ente_esterno": "Indica l'ente dell'auditor esterno."})

    @property
    def nome(self) -> str:
        if self.user_id:
            return (self.user.get_full_name() or self.user.get_username()).strip()
        return self.nome_esterno.strip() or f"Auditor {self.pk or ''}".strip()

    @property
    def audit_svolti(self) -> int:
        if not self.pk:
            return int(self.audit_svolti_pregressi or 0)
        dal_portale = Audit.objects.filter(
            models.Q(lead_auditor=self) | models.Q(auditor=self), stato=Audit.STATO_CHIUSO,
        ).distinct().count()
        return int(self.audit_svolti_pregressi or 0) + dal_portale

    @property
    def qualificato(self) -> bool:
        requisiti = (
            self.req_diploma, self.req_norme, self.req_tecniche_audit,
            self.req_settore, self.req_esperienza_2_anni,
        )
        esterno_approvato = self.interno or bool(self.approvato_ceo_da_id and self.approvato_ceo_il and self.formazione_processi_il)
        return bool(all(requisiti) and self.requisiti_verificati_il and esterno_approvato and self.audit_svolti >= 4)


class ProgrammaAudit(models.Model):
    STATO_BOZZA = "BOZZA"
    STATO_PROPOSTA = "PROPOSTA"
    STATO_APPROVATO = "APPROVATO"
    STATO_SUPERATO = "SUPERATO"
    STATO_CHOICES = [
        (STATO_BOZZA, "Bozza"),
        (STATO_PROPOSTA, "Proposto"),
        (STATO_APPROVATO, "Approvato"),
        (STATO_SUPERATO, "Superato"),
    ]

    anno = models.PositiveSmallIntegerField(db_index=True)
    revisione = models.PositiveSmallIntegerField(default=0)
    stato = models.CharField(max_length=12, choices=STATO_CHOICES, default=STATO_BOZZA, db_index=True)
    motivo_revisione = models.CharField(max_length=255, blank=True, default="")
    rif_riesame = models.CharField(max_length=255, blank=True, default="")
    periodi = models.TextField(blank=True, default="")
    esclusioni_27002 = models.TextField(blank=True, default="")
    preparato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    proposto_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    proposto_il = models.DateTimeField(null=True, blank=True)
    approvato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    approvato_il = models.DateTimeField(null=True, blank=True)
    convalidato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    convalidato_il = models.DateTimeField(null=True, blank=True)
    copia_firmata = models.FileField(
        upload_to="sistema_gestione/audit/programmi/%Y/", storage=PrivateSistemaGestioneStorage(), blank=True,
    )
    copia_firmata_nome = models.CharField(max_length=255, blank=True, default="")
    copia_firmata_caricata_il = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-anno", "-revisione"]
        constraints = [
            models.UniqueConstraint(fields=["anno", "revisione"], name="sg_programma_anno_revisione_unici"),
        ]
        verbose_name = "Programma audit (MOD.034)"
        verbose_name_plural = "Programmi audit (MOD.034)"

    def __str__(self) -> str:
        return f"Programma audit {self.anno} Rev.{self.revisione}"

    @property
    def modificabile(self) -> bool:
        return self.stato == self.STATO_BOZZA


class Processo(models.Model):
    codice = models.CharField(max_length=30, unique=True)
    nome = models.CharField(max_length=200)
    categoria = models.CharField(max_length=20, choices=[
        ("DIREZIONALE", "Direzionale"), ("OPERATIVO", "Operativo"), ("SUPPORTO", "Supporto"),
    ], default="OPERATIVO")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="processi_sgi")
    enti = models.CharField(max_length=255, blank=True)
    scopo = models.TextField(blank=True)
    input = models.TextField(blank=True)
    output = models.TextField(blank=True)
    rischi = models.TextField(blank=True)
    indicatori = models.TextField(blank=True)
    procedure = models.TextField(blank=True)
    fonte_documentale = models.TextField(blank=True, help_text="File, revisione, pagina e impronta della fonte; discrepanze da verificare.")
    punti_9100 = models.CharField(max_length=255, blank=True)
    punti_45001 = models.CharField(max_length=255, blank=True)
    punti_27001 = models.CharField(max_length=255, blank=True)
    punti_pdr125 = models.CharField(max_length=255, blank=True)
    criticita = models.PositiveSmallIntegerField(default=2, choices=[(1,"Bassa"),(2,"Media"),(3,"Alta")])
    frequenza_mesi = models.PositiveSmallIntegerField(default=12)
    attivo = models.BooleanField(default=True)
    revisione = models.PositiveIntegerField(default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["codice"]
        verbose_name_plural = "Processi"

    def __str__(self):
        return f"{self.codice} - {self.nome}"

    def snapshot(self):
        dati = {f.name: getattr(self, f.name) for f in self._meta.fields
                if f.name not in {"responsabile", "updated_at"}}
        dati["responsabile_id"] = self.responsabile_id
        dati["responsabile"] = ((self.responsabile.get_full_name() or self.responsabile.get_username())
                                if self.responsabile_id else "")
        dati["checklist"] = list(self.checklist.filter(attiva=True).values(
            "id", "codice", "norma", "punti", "domanda", "criterio", "suggerimento", "revisione"
        )) if self.pk else []
        return dati


class ProcessoRevisione(models.Model):
    processo = models.ForeignKey(Processo, on_delete=models.PROTECT, related_name="revisioni")
    numero = models.PositiveIntegerField()
    dati = models.JSONField(default=dict)
    motivo = models.CharField(max_length=500)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["processo", "numero"], name="sg_processo_rev_unica")]


class RigaProgramma(models.Model):
    processo = models.ForeignKey(Processo, null=True, blank=True, on_delete=models.PROTECT, related_name="righe")
    programma = models.ForeignKey(ProgrammaAudit, on_delete=models.CASCADE, related_name="righe")
    ordine = models.PositiveIntegerField(default=100)
    area = models.CharField(max_length=255)
    enti = models.CharField(max_length=255, blank=True, default="")
    punti_9100 = models.CharField(max_length=255, blank=True, default="")
    punti_45001 = models.CharField(max_length=255, blank=True, default="")
    punti_27001 = models.CharField(max_length=255, blank=True, default="")
    punti_pdr125 = models.CharField(max_length=255, blank=True, default="")
    altre_normative = models.CharField(max_length=500, blank=True, default="")
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name = "Riga programma audit"
        verbose_name_plural = "Righe programma audit"

    def __str__(self) -> str:
        return self.area


class Audit(models.Model):
    TIPO_SISTEMA = "SISTEMA"
    TIPO_MANDATORIO_CLIENTE = "MANDATORIO_CLIENTE"
    TIPO_STRAORDINARIO = "STRAORDINARIO"
    TIPO_CHOICES = [
        (TIPO_SISTEMA, "Sistema SGI (RAIS)"),
        (TIPO_MANDATORIO_CLIENTE, "Mandatorio cliente (RAI)"),
        (TIPO_STRAORDINARIO, "Straordinario"),
    ]
    STATO_PIANIFICATO = "PIANIFICATO"
    STATO_PIANO_APPROVATO = "PIANO_APPROVATO"
    STATO_IN_CORSO = "IN_CORSO"
    STATO_RAPPORTO = "RAPPORTO"
    STATO_CHIUSO = "CHIUSO"
    STATO_ANNULLATO = "ANNULLATO"
    STATO_CHOICES = [
        (STATO_PIANIFICATO, "Pianificato"),
        (STATO_PIANO_APPROVATO, "Piano approvato"),
        (STATO_IN_CORSO, "In corso"),
        (STATO_RAPPORTO, "Rapporto in valutazione"),
        (STATO_CHIUSO, "Chiuso"),
        (STATO_ANNULLATO, "Annullato"),
    ]
    COM_EMAIL = "EMAIL"
    COM_CALENDARIO = "CALENDARIO"
    COM_CHOICES = [(COM_EMAIL, "Email"), (COM_CALENDARIO, "Email + invito calendario")]

    numero = models.CharField(max_length=40, unique=True)
    programma = models.ForeignKey(
        ProgrammaAudit, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit",
    )
    righe = models.ManyToManyField(RigaProgramma, blank=True, related_name="audit_collegati")
    tipo = models.CharField(max_length=24, choices=TIPO_CHOICES, default=TIPO_SISTEMA)
    en9100 = models.BooleanField(default=True)
    iso45001 = models.BooleanField(default=False)
    iso27001 = models.BooleanField(default=False)
    pdr125 = models.BooleanField(default=False)
    lead_auditor = models.ForeignKey(Auditor, on_delete=models.PROTECT, related_name="audit_come_lead")
    auditor = models.ManyToManyField(Auditor, blank=True, related_name="audit_come_membro")
    processi = models.TextField(blank=True, default="")
    processi_catalogo = models.ManyToManyField(Processo, blank=True, related_name="audit")
    processi_snapshot = models.JSONField(default=list, blank=True)
    punti_norma = models.TextField(blank=True, default="")
    procedure_criteri = models.TextField(blank=True, default="")
    esclusioni = models.TextField(blank=True, default="Nessuna")
    data_inizio = models.DateField()
    data_fine = models.DateField(null=True, blank=True)
    durata_stimata = models.CharField(max_length=100, blank=True, default="")
    sede = models.CharField(max_length=255, blank=True, default=default_sede_audit)
    metodo_intervista = models.BooleanField(default=True)
    metodo_esame_documenti = models.BooleanField(default=True)
    metodo_osservazione_diretta = models.BooleanField(default=False)
    metodo_verifica_evidenze = models.BooleanField(default=True)
    comunicazione_il = models.DateTimeField(null=True, blank=True)
    comunicazione_metodo = models.CharField(max_length=12, choices=COM_CHOICES, blank=True, default="")
    preavviso_deroga_motivo = models.TextField(blank=True, default="")
    imparzialita_deroga_motivo = models.TextField(blank=True, default="")
    stato = models.CharField(max_length=20, choices=STATO_CHOICES, default=STATO_PIANIFICATO, db_index=True)

    piano_approvato_lead_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    piano_approvato_lead_il = models.DateTimeField(null=True, blank=True)
    piano_approvato_direzione_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    piano_approvato_direzione_il = models.DateTimeField(null=True, blank=True)
    rapporto_firmato_auditor_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    rapporto_firmato_auditor_il = models.DateTimeField(null=True, blank=True)
    rapporto_convalidato_ente_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    rapporto_convalidato_ente_il = models.DateTimeField(null=True, blank=True)
    rapporto_valutato_rdd_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    rapporto_valutato_rdd_il = models.DateTimeField(null=True, blank=True)
    riepilogo_generato = models.TextField(blank=True, default="")
    giudizio = models.TextField(blank=True, default="")
    punti_forza = models.TextField(blank=True, default="")
    valutazione_rdd = models.TextField(blank=True, default="")
    car_autorizzate = models.TextField(blank=True, default="")
    copia_firmata_piano = models.FileField(
        upload_to="sistema_gestione/audit/piani/%Y/", storage=PrivateSistemaGestioneStorage(), blank=True,
    )
    copia_firmata_piano_nome = models.CharField(max_length=255, blank=True, default="")
    copia_firmata_rapporto = models.FileField(
        upload_to="sistema_gestione/audit/rapporti/%Y/", storage=PrivateSistemaGestioneStorage(), blank=True,
    )
    copia_firmata_rapporto_nome = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_inizio", "-numero"]
        verbose_name = "Audit interno"
        verbose_name_plural = "Audit interni"

    def __str__(self) -> str:
        return self.numero

    @property
    def norme_label(self) -> str:
        valori = []
        for flag, label in (
            (self.en9100, "EN 9100:2018"), (self.iso45001, "ISO 45001:2018"),
            (self.iso27001, "ISO/IEC 27001:2022"), (self.pdr125, "UNI/PdR 125:2022"),
        ):
            if flag:
                valori.append(label)
        return ", ".join(valori)

    def utente_e_auditor(self, user) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return bool(
            (self.lead_auditor.user_id == user.id)
            or self.auditor.filter(user_id=user.id).exists()
        )


class CellaProgramma(models.Model):
    STATO_PR = "PR"
    STATO_RP = "RP"
    STATO_ST = "ST"
    STATO_CHOICES = [(STATO_PR, "Programmata"), (STATO_RP, "Riprogrammata"), (STATO_ST, "Straordinaria")]

    riga = models.ForeignKey(RigaProgramma, on_delete=models.CASCADE, related_name="celle")
    mese = models.PositiveSmallIntegerField(choices=[(n, str(n)) for n in range(1, 13)])
    stato = models.CharField(max_length=2, choices=STATO_CHOICES, default=STATO_PR)
    audit = models.ForeignKey(Audit, null=True, blank=True, on_delete=models.SET_NULL, related_name="celle_programma")

    class Meta:
        ordering = ["mese"]
        constraints = [
            models.UniqueConstraint(fields=["riga", "mese"], name="sg_cella_unica_riga_mese"),
            models.CheckConstraint(condition=models.Q(mese__gte=1, mese__lte=12), name="sg_cella_mese_1_12"),
        ]
        verbose_name = "Cella programma audit"
        verbose_name_plural = "Celle programma audit"

    def __str__(self) -> str:
        return f"{self.riga} - {self.mese:02d} ({self.stato})"


class AuditPersona(models.Model):
    RUOLO_TEAM = "TEAM"
    RUOLO_AUDITATO = "AUDITATO"
    RUOLO_PROCESSO = "PROCESSO"
    RUOLO_CHOICES = [
        (RUOLO_TEAM, "Team di audit"), (RUOLO_AUDITATO, "Auditato"),
        (RUOLO_PROCESSO, "Responsabile del processo"),
    ]
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="persone")
    nome = models.CharField(max_length=200)
    funzione_ente = models.CharField(max_length=200, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    ruolo = models.CharField(max_length=12, choices=RUOLO_CHOICES)
    data_intervista = models.DateField(null=True, blank=True)
    intervistato = models.BooleanField(default=False)

    class Meta:
        ordering = ["ruolo", "nome"]

    def __str__(self) -> str:
        return self.nome


class AuditAgenda(models.Model):
    processo = models.ForeignKey(Processo, null=True, blank=True, on_delete=models.PROTECT, related_name="attivita_audit")
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="agenda")
    quando = models.DateTimeField()
    processo_area = models.CharField(max_length=255)
    attivita = models.TextField(blank=True, default="")
    auditor = models.CharField(max_length=200, blank=True, default="")
    ordine = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["quando", "ordine", "id"]

    def __str__(self) -> str:
        return f"{self.quando:%d/%m/%Y %H:%M} - {self.processo_area}"


class ChecklistModello(models.Model):
    CODICE_EN9100_FOLDER_B = "EN9100_FOLDER_B"
    codice = models.CharField(max_length=40)
    norma = models.CharField(max_length=100)
    revisione = models.PositiveSmallIntegerField(default=0)
    titolo = models.CharField(max_length=255)
    origine = models.CharField(max_length=255, blank=True, default="")
    attivo = models.BooleanField(default=True, db_index=True)
    importato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["codice", "-revisione"]
        constraints = [
            models.UniqueConstraint(fields=["codice", "revisione"], name="sg_checklist_codice_revisione_unici"),
        ]

    def __str__(self) -> str:
        return f"{self.titolo} Rev.{self.revisione}"


class ChecklistSezione(models.Model):
    modello = models.ForeignKey(ChecklistModello, on_delete=models.CASCADE, related_name="sezioni")
    codice = models.CharField(max_length=20)
    titolo = models.CharField(max_length=255)
    criteri = models.TextField(blank=True, default="")
    ordine = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["ordine", "id"]
        constraints = [
            models.UniqueConstraint(fields=["modello", "codice"], name="sg_checklist_sezione_unica"),
        ]

    def __str__(self) -> str:
        return f"{self.codice} - {self.titolo}"


class ChecklistDomanda(models.Model):
    sezione = models.ForeignKey(ChecklistSezione, on_delete=models.CASCADE, related_name="domande")
    punti = models.CharField(max_length=100)
    testo = models.TextField()
    ordine = models.PositiveIntegerField(default=100)
    attiva = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordine", "id"]

    def __str__(self) -> str:
        return f"{self.punti} - {self.testo[:60]}"


class ChecklistProcesso(models.Model):
    processo = models.ForeignKey(Processo, on_delete=models.PROTECT, related_name="checklist")
    codice = models.CharField(max_length=30)
    norma = models.CharField(max_length=12, choices=[("en9100", "EN 9100"), ("iso45001", "ISO 45001"), ("iso27001", "ISO/IEC 27001"), ("pdr125", "UNI/PdR 125")], default="en9100")
    punti = models.CharField(max_length=100)
    domanda = models.TextField()
    criterio = models.TextField()
    suggerimento = models.TextField(blank=True)
    ordine = models.PositiveIntegerField(default=100)
    revisione = models.PositiveIntegerField(default=1)
    attiva = models.BooleanField(default=True)
    aggiornata_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "codice"]
        constraints = [models.UniqueConstraint(fields=["processo", "codice"], name="sg_check_processo_codice")]

    def __str__(self):
        return f"{self.processo.codice}/{self.codice} Rev.{self.revisione}"


class AuditEsito(models.Model):
    ESITO_CONFORME = "CONFORME"
    ESITO_OFI = "OFI"
    ESITO_NC = "NC"
    ESITO_NA = "NA"
    ESITO_CHOICES = [
        (ESITO_CONFORME, "Conforme"), (ESITO_OFI, "OFI"),
        (ESITO_NC, "NC"), (ESITO_NA, "N/A"),
    ]
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="esiti")
    processo = models.ForeignKey(Processo, null=True, blank=True, on_delete=models.PROTECT, related_name="esiti_audit")
    modello_processo = models.ForeignKey(ChecklistProcesso, null=True, blank=True, on_delete=models.PROTECT)
    domanda_snapshot = models.JSONField(default=dict, blank=True)
    strutturato = models.BooleanField(default=False)
    versione = models.PositiveIntegerField(default=0)
    documento = models.CharField(max_length=255, blank=True)
    revisione_documento = models.CharField(max_length=100, blank=True)
    campione = models.TextField(blank=True)
    data_verifica = models.DateField(null=True, blank=True)
    requisito_atteso = models.TextField(blank=True)
    scostamento = models.TextField(blank=True)
    responsabile_azione = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="rilievi_audit_assegnati")
    scadenza_azione = models.DateField(null=True, blank=True)
    domanda = models.ForeignKey(
        ChecklistDomanda, null=True, blank=True, on_delete=models.PROTECT, related_name="esiti",
    )
    sezione = models.ForeignKey(
        ChecklistSezione, null=True, blank=True, on_delete=models.PROTECT, related_name="esiti_aggiuntivi",
    )
    punti_aggiuntivi = models.CharField(max_length=100, blank=True, default="")
    testo_aggiuntivo = models.TextField(blank=True, default="")
    esito = models.CharField(max_length=10, choices=ESITO_CHOICES, blank=True, default="")
    evidenze = models.TextField(blank=True, default="")
    ofi = models.ForeignKey(
        "gestione_specifiche.RegistroOFI", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    aggiornato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domanda__sezione__ordine", "domanda__ordine", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["audit", "domanda"],
                condition=models.Q(domanda__isnull=False),
                name="sg_esito_unico_audit_domanda",
            ),
            models.UniqueConstraint(fields=["audit", "modello_processo"], condition=models.Q(modello_processo__isnull=False), name="sg_esito_unico_processo"),
        ]

    def clean(self):
        super().clean()
        if not self.domanda_id and not self.testo_aggiuntivo.strip():
            raise ValidationError({"testo_aggiuntivo": "Descrivi la domanda aggiuntiva."})

    @property
    def sezione_effettiva(self):
        return self.domanda.sezione if self.domanda_id else self.sezione

    @property
    def punti(self) -> str:
        return self.domanda_snapshot.get("punti") or (self.domanda.punti if self.domanda_id else self.punti_aggiuntivi)

    @property
    def testo(self) -> str:
        return self.domanda_snapshot.get("domanda") or (self.domanda.testo if self.domanda_id else self.testo_aggiuntivo)


class AuditSezioneCar(models.Model):
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="car_sezioni")
    sezione = models.ForeignKey(ChecklistSezione, on_delete=models.PROTECT, related_name="car_audit")
    car_aperta = models.BooleanField(default=False)

    class Meta:
        ordering = ["sezione__ordine"]
        constraints = [
            models.UniqueConstraint(fields=["audit", "sezione"], name="sg_car_unica_audit_sezione"),
        ]


class AuditAllegato(models.Model):
    esito = models.ForeignKey(AuditEsito, on_delete=models.PROTECT, related_name="allegati")
    file = models.FileField(upload_to="sistema_gestione/evidenze/%Y/%m/", storage=PrivateSistemaGestioneStorage())
    nome = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    dimensione = models.PositiveIntegerField()
    caricato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    caricato_il = models.DateTimeField(auto_now_add=True)


class AuditVerificaEfficacia(models.Model):
    esito = models.ForeignKey(AuditEsito, on_delete=models.PROTECT, related_name="verifiche_efficacia")
    risultato = models.CharField(max_length=16, choices=[("EFFICACE", "Efficace"), ("NON_EFFICACE", "Non efficace"), ("DA_RIVERIFICARE", "Da riverificare")])
    metodo = models.TextField()
    evidenza = models.TextField()
    data_verifica = models.DateField()
    prossima_verifica = models.DateField(null=True, blank=True)
    verificato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    registrato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-registrato_il", "-pk"]


class AuditRapportoVersione(models.Model):
    audit = models.ForeignKey(Audit, on_delete=models.PROTECT, related_name="versioni_rapporto")
    numero = models.PositiveIntegerField()
    motivo = models.CharField(max_length=500)
    snapshot = models.JSONField(default=dict)
    pdf = models.FileField(upload_to="sistema_gestione/revisioni/%Y/", storage=PrivateSistemaGestioneStorage())
    copia_firmata = models.FileField(blank=True, storage=PrivateSistemaGestioneStorage())
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["audit", "numero"], name="sg_rapporto_versione_unica")]


class AuditPreparazione(models.Model):
    audit = models.OneToOneField(Audit, on_delete=models.CASCADE, related_name="preparazione")
    audit_precedenti = models.TextField("Audit precedenti: riferimenti ed esame, oppure assenza motivata")
    car_cliente = models.TextField("CAR cliente: riferimenti e stato, oppure assenza motivata")
    documenti_registrazioni = models.TextField("Documenti e registrazioni da campionare, revisioni e disponibilita")
    obiettivi_carenze = models.TextField("Obiettivi della verifica e carenze da approfondire")
    verificato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    verificato_il = models.DateTimeField(auto_now=True)


class AzioneCorrettivaAudit(models.Model):
    registro = models.OneToOneField("gestione_specifiche.RegistroOFI", on_delete=models.PROTECT, related_name="car_procedurale")
    data_richiesta = models.DateField("Data richiesta CAR")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="car_assegnate")
    causa = models.TextField("Analisi della causa radice", blank=True)
    contenimento = models.TextField("Azione di contenimento", blank=True)
    azione = models.TextField("Azione correttiva e modifiche documentali", blank=True)
    analizzata_il = models.DateField("Data valutazione cause e azioni", null=True, blank=True)
    evidenza_attuazione = models.TextField("Evidenza di attuazione", blank=True)
    evidenza_efficacia = models.TextField("Metodo, campione e risultato della verifica di efficacia", blank=True)
    proroga_al = models.DateField(null=True, blank=True)
    motivo_proroga = models.TextField(blank=True)
    proroga_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    proroga_il = models.DateTimeField(null=True)
    approvata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    approvata_il = models.DateTimeField(null=True)
    approvazione_esterna = models.CharField("Riferimento approvazione cliente/ente, se richiesta esterna", max_length=250, blank=True)
    origine_esterna = models.BooleanField("CAR richiesta da cliente/ente", default=False)
    chiusa_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    chiusa_il = models.DateTimeField(null=True)
    versione = models.PositiveIntegerField(default=0)

    @property
    def scadenza_analisi(self):
        from .services.audit_automation import aggiungi_mesi
        return aggiungi_mesi(self.data_richiesta, 1)

    @property
    def scadenza_chiusura(self):
        from .services.audit_automation import aggiungi_mesi
        return self.proroga_al or aggiungi_mesi(self.data_richiesta, 3)


class RilevazioneKpi(models.Model):
    processo = models.ForeignKey(Processo, on_delete=models.PROTECT, related_name="rilevazioni_kpi")
    codice = models.CharField(max_length=40)
    periodo_da = models.DateField()
    periodo_a = models.DateField()
    formula = models.CharField(max_length=20, choices=[("PERCENTUALE", "Numeratore / denominatore x 100"), ("RAPPORTO", "Numeratore / denominatore"), ("VENDOR", "Vendor Rating: OTD x 0,30 + OQD x 0,70")])
    numeratore = models.DecimalField("Numeratore (per VR: consegne puntuali)", max_digits=18, decimal_places=4)
    denominatore = models.DecimalField("Denominatore (per VR: consegne totali)", max_digits=18, decimal_places=4)
    pezzi_nc = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    pezzi_totali = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    fonte_filtri = models.TextField("Fonte, campo data, filtri ed esclusioni applicati")
    target = models.DecimalField(max_digits=18, decimal_places=4)
    verso = models.CharField(max_length=3, choices=[("MIN", "Valore almeno pari al target"), ("MAX", "Valore al massimo pari al target")])
    valore_precedente = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    confrontabile = models.BooleanField(default=True)
    motivo_non_confrontabilita = models.TextField(blank=True)
    commento = models.TextField("Analisi, cause e azioni proposte")
    riferimento_riesame = models.CharField("Riferimento VRS / obiettivo approvato", max_length=250)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-periodo_a", "-pk"]
