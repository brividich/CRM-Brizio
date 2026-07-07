"""MOD.128 MPQ — Mansionario Processi Qualificati (strato additivo).

Modulo *additivo* dentro l'app ``anagrafica``: digitalizza il MOD.128 MPQ
(processi qualificati/speciali cliente-specifici, personale abilitato per ruolo,
doppia scadenza aziendale/individuale, distribuzione a reparto) **riusando** i
modelli Qualifiche/Reparti esistenti via **FK opzionali**, senza modificarli.

Convenzioni del progetto rispettate (come ``models_skillmatrix``):
- dipendente agganciato via ``legacy_anagrafica_id`` (IntegerField), **nessuna FK**
  al modello dipendente; risolto a valle con ``core.legacy_anagrafica.fetch_anagrafica_rows``;
- compatibilità SQL Server (mssql-django): nessun indice parziale, nessun
  ``UniqueConstraint`` con ``condition``, nessun campo ``unique`` nullable;
- FK verso gli altri modelli via *string reference* per evitare import ciclici.

Importato in ``anagrafica/models.py`` con ``from .models_mpq import *``.

Regole di riferimento: MT CN 06 Rev.21 §7.2 (gestione Qualità), §8.2.1 (requisiti
minimi processi qualificati/speciali), §11.2/§11.4 (processi speciali e
requisiti cliente-specifici). Il MOD.128 **non** è motore di autorizzazione alla
firma (quella resta ai timbri fisici + Skill Matrix).
"""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from .storage import PrivateAnagraficaStorage

__all__ = [
    "ClienteQualificante",
    "ProcessoQualificato",
    "RiferimentoProcesso",
    "AbilitazioneProcesso",
    "CertificazioneIndividuale",
    "MpqStorico",
]


def _add_months(d: date, months: int) -> date:
    """Aggiunge ``months`` mesi calendariali a ``d`` (clamp a fine mese).

    Duplicato locale dell'helper di ``models.py``/``import_asr`` per evitare
    import ciclici in fase di caricamento dei modelli.
    """
    if not d or months <= 0:
        return d
    month_index = (d.month - 1) + int(months)
    year = d.year + (month_index // 12)
    month = (month_index % 12) + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day_of_month)
    return date(year, month, day)


def _certificazione_individuale_upload_to(instance, filename: str) -> str:
    legacy_id = getattr(getattr(instance, "abilitazione", None), "legacy_anagrafica_id", None) or "tmp"
    suffix = Path(filename or "").suffix.lower()[:20] or ".bin"
    stem = Path(filename or "").stem[:80] or "certificato"
    now = timezone.now()
    return (
        f"anagrafica/dipendenti/{legacy_id}/mpq_certificazioni/"
        f"{now.strftime('%Y%m')}/{now.strftime('%Y%m%d_%H%M%S')}_{stem}{suffix}"
    )


# ---------------------------------------------------------------------------
# Anagrafica cliente / ente qualificante (leggera). Non esiste un modello
# Cliente riusabile: in gestione_specifiche il cliente è solo una stringa.
# Include enti esterni e relativi organismi di certificazione (self-FK).
# ---------------------------------------------------------------------------
class ClienteQualificante(models.Model):
    TIPO_CLIENTE = "CLIENTE"
    TIPO_ENTE_ACCREDITAMENTO = "ENTE_ACCREDITAMENTO"
    TIPO_ENTE_ESTERNO = "ENTE_ESTERNO"
    TIPO_ORGANISMO_CERTIFICAZIONE = "ORGANISMO_CERTIFICAZIONE"
    TIPO_CHOICES = [
        (TIPO_CLIENTE, "Cliente"),
        (TIPO_ENTE_ACCREDITAMENTO, "Ente di accreditamento"),
        (TIPO_ENTE_ESTERNO, "Ente esterno"),
        (TIPO_ORGANISMO_CERTIFICAZIONE, "Organismo di certificazione"),
    ]

    nome = models.CharField(max_length=200, unique=True)
    tipo = models.CharField(max_length=24, choices=TIPO_CHOICES, default=TIPO_CLIENTE, db_index=True)
    codice = models.CharField(max_length=60, blank=True, default="")
    # Organismo che certifica/accredita questo ente o schema (es. ente esterno
    # con relativo certificatore). Self-FK opzionale.
    certificatore = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="enti_certificati",
        help_text="Organismo che certifica/accredita questo ente (opzionale).",
    )
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tipo", "nome"]
        verbose_name = "Cliente/ente qualificante (MPQ)"
        verbose_name_plural = "Clienti/enti qualificanti (MPQ)"

    def __str__(self) -> str:
        return self.nome


# ---------------------------------------------------------------------------
# Processo qualificato / speciale (la "riga" del MOD.128, grana = cliente×processo)
# ---------------------------------------------------------------------------
class ProcessoQualificato(models.Model):
    # Stato del processo (illimitato pilotato dallo stato: revoca/sospensione).
    STATO_ATTIVO = "ATTIVO"
    STATO_SOSPESO = "SOSPESO"
    STATO_REVOCATO = "REVOCATO"
    STATO_DISMESSO = "DISMESSO"
    STATO_NON_RINNOVATO = "NON_RINNOVATO"
    STATO_CHOICES = [
        (STATO_ATTIVO, "Attivo"),
        (STATO_SOSPESO, "Sospeso"),
        (STATO_REVOCATO, "Revocato"),
        (STATO_DISMESSO, "Dismesso"),
        (STATO_NON_RINNOVATO, "Non più rinnovato"),
    ]

    VALIDITA_ILLIMITATA = "ILLIMITATA"
    VALIDITA_PERIODO = "PERIODO"
    VALIDITA_DATA = "DATA"
    VALIDITA_CHOICES = [
        (VALIDITA_ILLIMITATA, "Illimitata (salvo revoca/sospensione)"),
        (VALIDITA_PERIODO, "Periodo (durata in mesi)"),
        (VALIDITA_DATA, "Data di scadenza esplicita"),
    ]

    REGIME_PART145 = "PART145"
    REGIME_NADCAP = "NADCAP"
    REGIME_CLIENTE = "CLIENTE_SPECIFICO"
    REGIME_SPECIALE = "SPECIALE"
    REGIME_CHOICES = [
        (REGIME_PART145, "EASA Part 145"),
        (REGIME_NADCAP, "NADCAP"),
        (REGIME_CLIENTE, "Cliente-specifico"),
        (REGIME_SPECIALE, "Processo speciale"),
    ]

    MODALITA_NOMINALE = "NOMINALE"
    MODALITA_ORGANIZZATIVO = "ORGANIZZATIVO"
    MODALITA_CHOICES = [
        (MODALITA_NOMINALE, "Nominale (elenco persone)"),
        (MODALITA_ORGANIZZATIVO, "Organizzativa (rimando a dichiarazione)"),
    ]

    nome = models.CharField(max_length=255)
    cliente = models.ForeignKey(
        ClienteQualificante, on_delete=models.PROTECT, related_name="processi",
    )
    # Riconoscimento condiviso: lo stesso processo riconosciuto da più clienti/enti (raro).
    clienti_addizionali = models.ManyToManyField(
        ClienteQualificante, blank=True, related_name="processi_condivisi",
    )
    ente_certificatore = models.ForeignKey(
        ClienteQualificante, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="processi_certificati",
        help_text="Ente/organismo che certifica o accredita il processo (opzionale).",
    )
    livello = models.CharField(max_length=40, blank=True, default="", help_text="Es. LVL2/LVL3.")
    regime = models.CharField(max_length=20, choices=REGIME_CHOICES, default=REGIME_SPECIALE)
    reparti = models.ManyToManyField(
        "anagrafica.Reparto", blank=True, related_name="processi_qualificati",
        verbose_name="Distribuzione a reparto",
    )
    tipo_qualifica = models.ForeignKey(
        "anagrafica.TipoQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="processi_mpq",
        help_text="Tipo qualifica di catalogo collegato (opzionale).",
    )

    # Requisiti per l'idoneità al processo (come le mansioni di rischio): corsi di
    # formazione, DPI e visite mediche necessari a chi è abilitato. Alimentano la
    # verifica di conformità (services/mpq_conformita).
    corsi_richiesti = models.ManyToManyField(
        "anagrafica.TrainingCourse", blank=True, related_name="processi_richiedenti",
        help_text="Corsi di formazione richiesti per l'idoneità al processo.",
    )
    dpi_richiesti = models.ManyToManyField(
        "dpi.CategoriaDPI", blank=True, related_name="processi_richiedenti",
        help_text="Categorie DPI obbligatorie per il processo.",
    )
    visite_richieste = models.ManyToManyField(
        "anagrafica.TipoVisitaMedica", blank=True, related_name="processi_richiedenti",
        help_text="Tipologie di visita medica obbligatorie per il processo.",
    )

    # Scadenza a livello processo/attestato (aziendale).
    tipo_validita = models.CharField(max_length=12, choices=VALIDITA_CHOICES, default=VALIDITA_DATA)
    data_conseguimento = models.DateField(null=True, blank=True)
    durata_mesi = models.PositiveSmallIntegerField(null=True, blank=True)
    data_scadenza = models.DateField(null=True, blank=True)

    # Personale nominale vs organizzativo (rimando a dichiarazione aziendale).
    personale_modalita = models.CharField(
        max_length=14, choices=MODALITA_CHOICES, default=MODALITA_NOMINALE,
    )
    riferimento_dichiarazione = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Per modalità organizzativa: rif. dichiarazione/approvazione.",
    )

    # Stato + tracciamento dismissione/revoca (audit).
    stato = models.CharField(max_length=14, choices=STATO_CHOICES, default=STATO_ATTIVO, db_index=True)
    motivo_stato = models.CharField(max_length=255, blank=True, default="")
    riferimento_stato = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Riferimento a supporto del cambio stato (es. comunicazione).",
    )

    # Versione del modulo (registro vivo, MT CN 06 §7.2/§11.4). NON il workflow
    # di firma RDD del MOD.187 §8.5.
    numero_revisione = models.CharField(max_length=20, blank=True, default="")
    responsabile_qualita = models.CharField(max_length=150, blank=True, default="")
    data_revisione = models.DateField(null=True, blank=True)

    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cliente__nome", "nome"]
        verbose_name = "Processo qualificato (MPQ)"
        verbose_name_plural = "Processi qualificati (MPQ)"

    def __str__(self) -> str:
        return f"{self.cliente_id} — {self.nome}"

    @property
    def scadenza_effettiva(self):
        """Scadenza processo: None se illimitata; data esplicita; oppure calcolata."""
        if self.tipo_validita == self.VALIDITA_ILLIMITATA:
            return None
        if self.data_scadenza:
            return self.data_scadenza
        if self.durata_mesi and self.data_conseguimento:
            return _add_months(self.data_conseguimento, self.durata_mesi)
        return None


class RiferimentoProcesso(models.Model):
    """Codice/riferimento di approvazione o specifica del processo (≥1 per processo)."""

    TIPO_APPROVAZIONE = "APPROVAZIONE"
    TIPO_SPECIFICA = "SPECIFICA"
    TIPO_CERTIFICATO = "CERTIFICATO"
    TIPO_DICHIARAZIONE = "DICHIARAZIONE"
    TIPO_CHOICES = [
        (TIPO_APPROVAZIONE, "Approvazione"),
        (TIPO_SPECIFICA, "Specifica"),
        (TIPO_CERTIFICATO, "Certificato"),
        (TIPO_DICHIARAZIONE, "Dichiarazione"),
    ]

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="riferimenti",
    )
    codice = models.CharField(max_length=200)
    tipo = models.CharField(max_length=14, choices=TIPO_CHOICES, default=TIPO_APPROVAZIONE)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["processo", "id"]
        verbose_name = "Riferimento processo (MPQ)"
        verbose_name_plural = "Riferimenti processo (MPQ)"

    def __str__(self) -> str:
        return self.codice


# ---------------------------------------------------------------------------
# Abilitazione persona × processo (ruoli: qualificato/addetto/controllore/part145)
# ---------------------------------------------------------------------------
class AbilitazioneProcesso(models.Model):
    STATO_ATTIVA = "ATTIVA"
    STATO_SOSPESA = "SOSPESA"
    STATO_REVOCATA = "REVOCATA"
    STATO_DISMESSA = "DISMESSA"
    STATO_CHOICES = [
        (STATO_ATTIVA, "Attiva"),
        (STATO_SOSPESA, "Sospesa"),
        (STATO_REVOCATA, "Revocata"),
        (STATO_DISMESSA, "Dismessa"),
    ]

    # Dipendente interno via legacy_anagrafica_id; per i **qualificatori esterni**
    # (persona non a organico, es. Livello 3 NDT esterno) usare
    # ``legacy_anagrafica_id=0`` + ``nominativo_esterno`` (nessun dipendente).
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    nominativo_esterno = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Qualificatore esterno (non a organico): usato al posto di legacy_anagrafica_id.",
    )
    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="abilitazioni",
    )
    # Ruoli sul processo (booleani, come nel modulo). Qualificato = essere in lista.
    is_qualificato = models.BooleanField(default=True)
    is_addetto = models.BooleanField(default=False)
    is_controllore = models.BooleanField(default=False)
    is_part145 = models.BooleanField(default=False)

    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_ATTIVA, db_index=True)
    data_ingresso = models.DateField(null=True, blank=True)
    data_dismissione = models.DateField(null=True, blank=True)
    motivo = models.CharField(max_length=255, blank=True, default="")

    # Riuso della qualifica individuale già gestita (numero/scadenza/documento/storico).
    dipendente_qualifica = models.ForeignKey(
        "anagrafica.DipendenteQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="abilitazioni_mpq",
    )
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["processo", "legacy_anagrafica_id"]
        verbose_name = "Abilitazione processo (MPQ)"
        verbose_name_plural = "Abilitazioni processo (MPQ)"
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_anagrafica_id", "nominativo_esterno", "processo"],
                name="mpq_uniq_abilitazione_persona_processo",
            ),
        ]

    def __str__(self) -> str:
        who = self.nominativo_esterno or self.legacy_anagrafica_id
        return f"[{who}] {self.processo_id}"

    @property
    def is_esterno(self) -> bool:
        """True se è un qualificatore esterno (non a organico)."""
        return bool(self.nominativo_esterno)


class CertificazioneIndividuale(models.Model):
    """Certificazione individuale (schema+numero+scadenza propri; ≥1 per abilitazione).

    Modella il caso "una persona → più certificati con scadenze diverse"
    (es. schema ITA + schema ASNT sullo stesso processo). È la **seconda
    scadenza** (individuale) accanto a quella del processo.
    """

    STATO_ATTIVA = "ATTIVA"
    STATO_SOSPESA = "SOSPESA"
    STATO_REVOCATA = "REVOCATA"
    STATO_CHOICES = [
        (STATO_ATTIVA, "Attiva"),
        (STATO_SOSPESA, "Sospesa"),
        (STATO_REVOCATA, "Revocata"),
    ]

    abilitazione = models.ForeignKey(
        AbilitazioneProcesso, on_delete=models.CASCADE, related_name="certificazioni",
    )
    schema = models.CharField(max_length=60, help_text="Schema di certificazione (es. ITA, ASNT).")
    numero = models.CharField(max_length=120, blank=True, default="")
    livello = models.CharField(max_length=40, blank=True, default="")
    data_scadenza = models.DateField(null=True, blank=True)
    ente_certificatore = models.ForeignKey(
        ClienteQualificante, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="certificazioni",
    )
    dipendente_qualifica = models.ForeignKey(
        "anagrafica.DipendenteQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="certificazioni_mpq",
    )
    documento = models.FileField(
        upload_to=_certificazione_individuale_upload_to,
        storage=PrivateAnagraficaStorage(),
        null=True, blank=True,
        help_text="Scansione/PDF del certificato individuale (evidenza).",
    )
    documento_nome_originale = models.CharField(max_length=255, blank=True, default="")
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_ATTIVA)
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["abilitazione", "schema"]
        verbose_name = "Certificazione individuale (MPQ)"
        verbose_name_plural = "Certificazioni individuali (MPQ)"

    def __str__(self) -> str:
        return f"{self.schema} {self.numero}".strip()


class MpqStorico(models.Model):
    """Storico append-only dei cambiamenti su processo/abilitazione (audit EN 9100)."""

    class Origine(models.TextChoices):
        MANUALE = "MANUALE", "Manuale"
        IMPORT = "IMPORT", "Import"
        SISTEMA = "SISTEMA", "Sistema"

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, null=True, blank=True,
        related_name="storico",
    )
    abilitazione = models.ForeignKey(
        AbilitazioneProcesso, on_delete=models.CASCADE, null=True, blank=True,
        related_name="storico",
    )
    evento = models.CharField(max_length=200)
    dettaglio = models.TextField(blank=True, default="")
    origine = models.CharField(max_length=10, choices=Origine.choices, default=Origine.MANUALE)
    registrato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    registrato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-registrato_il", "-id"]
        verbose_name = "Storico MPQ"
        verbose_name_plural = "Storico MPQ"

    def __str__(self) -> str:
        return f"{self.evento} ({self.registrato_il:%Y-%m-%d})" if self.registrato_il else self.evento
