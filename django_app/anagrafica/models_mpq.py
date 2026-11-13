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
    "RequisitoQualifica",
    "AbilitazioneProcesso",
    "CertificazioneIndividuale",
    "MpqStorico",
    "RuoloProcesso",
    "RequisitoPersona",
    "EvidenzaRequisitoPersona",
    "QualificaMacchina",
    "RequisitoMacchina",
    "ParametroVerificaMacchina",
    "VerificaMacchina",
    "VerificaMacchinaMisura",
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
    perimetro_part145 = models.BooleanField(
        default=False, verbose_name="Rientra nel perimetro Part 145",
        help_text="Processo speciale autorizzato per le attività Part 145 (es. elenco DQP dell'accordo "
                  "con l'organizzazione di manutenzione): compare nel Dossier PART 145.",
    )
    reparti = models.ManyToManyField(
        "anagrafica.Reparto", blank=True, related_name="processi_qualificati",
        verbose_name="Distribuzione a reparto",
    )
    tipo_qualifica = models.ForeignKey(
        "anagrafica.TipoQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="processi_mpq",
        help_text="Tipo qualifica di catalogo collegato (opzionale).",
    )

    # STORICI, non più letti (migrazione 0225): corsi, DPI e visite richiesti sono
    # diventati righe di «Cosa serve a una persona» (RequisitoPersona), l'unico
    # elenco dei requisiti per persona. Restano per poter tornare indietro.
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

    # Macchine qualificate: ogni quanto va ripetuta la qualifica di una macchina
    # (es. P11TF12: 12 mesi). Proposta alle macchine nuove, modificabile per macchina.
    frequenza_macchine_mesi = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Ripeti la qualifica macchine ogni (mesi)",
        help_text="Vuoto = la qualifica di una macchina non scade (salvo sospensione).",
    )

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
# Requisito generico tipizzato del processo (1-N, ampliamento oltre i 3 M2M)
# ---------------------------------------------------------------------------
class RequisitoQualifica(models.Model):
    """Requisito generico tipizzato di un processo qualificato (≥0 per processo).

    Estende i tre M2M fissi (``corsi_richiesti``/``dpi_richiesti``/
    ``visite_richieste``) con requisiti liberi tipizzati che hanno scadenza/stato
    propri ed evidenza allegabile: audit, certificato, esame, esperienza, test
    visivo, DPI, riferimento normativo, altro (Part 145 / EN 9100 / NADCAP:
    qualifica = insieme di requisiti verificati con evidenza).

    Sono requisiti a livello **processo** (attestazione unica valida per tutti gli
    abilitati, non per-persona): la conformità li valuta sullo stato/scadenza del
    requisito, insieme ai requisiti per-persona (corsi/visite/DPI). L'FK opzionale
    ``tipo_qualifica`` collega il requisito al catalogo qualifiche.
    """

    TIPO_AUDIT = "audit"
    TIPO_CORSO = "corso"
    TIPO_CERTIFICATO = "certificato"
    TIPO_ESAME = "esame"
    TIPO_ESPERIENZA = "esperienza"
    TIPO_VISIONE = "visione"
    TIPO_DPI = "dpi"
    TIPO_RIF_NORMATIVO = "rif_normativo"
    TIPO_CONTRATTO = "contratto"
    TIPO_ALTRO = "altro"
    # Tipi che riguardano la singola persona: sono in «Cosa serve a una persona»
    # (RequisitoPersona). Restano qui solo sui requisiti registrati prima del 13/11.
    TIPI_PER_PERSONA = ("corso", "esame", "esperienza", "visione", "dpi")
    # Tipo corrispondente in RequisitoPersona quando si sposta il requisito.
    TIPO_IN_REQUISITO_PERSONA = {"corso": "corso", "esame": "esame", "esperienza": "esperienza",
                                 "visione": "test_visivo", "dpi": "dpi"}
    TIPO_CHOICES = [
        (TIPO_AUDIT, "Audit"),
        (TIPO_CORSO, "Corso/Formazione"),
        (TIPO_CERTIFICATO, "Certificato"),
        (TIPO_ESAME, "Esame"),
        (TIPO_ESPERIENZA, "Esperienza"),
        (TIPO_VISIONE, "Test visivo"),
        (TIPO_DPI, "DPI"),
        (TIPO_RIF_NORMATIVO, "Riferimento normativo"),
        (TIPO_CONTRATTO, "Contratto / accordo"),
        (TIPO_ALTRO, "Altro"),
    ]

    STATO_DA_VERIFICARE = "DA_VERIFICARE"
    STATO_SODDISFATTO = "SODDISFATTO"
    STATO_SCADUTO = "SCADUTO"
    STATO_NON_APPLICABILE = "NON_APPLICABILE"
    STATO_CHOICES = [
        (STATO_DA_VERIFICARE, "Da verificare"),
        (STATO_SODDISFATTO, "Soddisfatto"),
        (STATO_SCADUTO, "Scaduto"),
        (STATO_NON_APPLICABILE, "Non applicabile"),
    ]

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="requisiti",
    )
    tipo_qualifica = models.ForeignKey(
        "anagrafica.TipoQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requisiti_catalogo",
        help_text="Tipo qualifica di catalogo collegato (opzionale).",
    )
    tipo = models.CharField(max_length=16, choices=TIPO_CHOICES, default=TIPO_ALTRO)
    descrizione = models.CharField(max_length=255)
    obbligatorio = models.BooleanField(
        default=True, help_text="Se falso, la voce è informativa e non degrada l'esito.",
    )
    rif_normativo = models.CharField(max_length=200, blank=True, default="")

    # Scadenza/periodicità propria del requisito (indipendente dal processo).
    stato = models.CharField(
        max_length=16, choices=STATO_CHOICES, default=STATO_DA_VERIFICARE, db_index=True,
    )
    data_conseguimento = models.DateField(null=True, blank=True)
    periodicita_mesi = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Ricorrenza in mesi (vuoto = una tantum).",
    )
    data_scadenza = models.DateField(null=True, blank=True)

    # Evidenza allegabile (link a documento/registro; nessun upload obbligatorio).
    evidenza_url = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Link/riferimento all'evidenza (documento, registro, attestato).",
    )
    note = models.TextField(blank=True, default="")
    ordine = models.PositiveSmallIntegerField(default=0)
    attivo = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["processo", "ordine", "id"]
        verbose_name = "Requisito qualifica (MPQ)"
        verbose_name_plural = "Requisiti qualifica (MPQ)"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.descrizione}"

    @property
    def is_scaduto(self) -> bool:
        """Scaduto per stato esplicito o per ``data_scadenza`` passata."""
        if self.stato == self.STATO_SCADUTO:
            return True
        if self.data_scadenza is not None:
            return self.data_scadenza < timezone.localdate()
        return False


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
    # Ruoli del processo (catalogo per processo, es. Operatore macchina, Presetting,
    # CAR...): decidono quali requisiti persona valgono per chi. Vuoto = solo i
    # requisiti validi per tutti i ruoli.
    ruoli_processo = models.ManyToManyField(
        "anagrafica.RuoloProcesso", blank=True, related_name="abilitazioni",
    )

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


# ===========================================================================
# Persone qualificate e macchine qualificate (13/11/2026)
#
# Ogni processo ha tre livelli con scadenze indipendenti:
# - il processo (approvazione cliente/ente: ``ProcessoQualificato.scadenza_effettiva``);
# - la persona (requisiti per ruolo, una tantum o ricorrenti: ``RequisitoPersona``);
# - la macchina (qualifica, verifiche con misure, manutenzioni: ``QualificaMacchina``).
# Rif. MT CN 69 §7/§9 (P11TF12), MT CN 70 (Part 145), MT CN 07 §6.
# ===========================================================================


def _documento_mpq_upload_to(instance, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()[:20] or ".bin"
    stem = Path(filename or "").stem[:80] or "evidenza"
    now = timezone.now()
    return (
        f"anagrafica/mpq_evidenze/{type(instance).__name__.lower()}/"
        f"{now.strftime('%Y%m')}/{now.strftime('%Y%m%d_%H%M%S')}_{stem}{suffix}"
    )


def numero_breve(valore) -> str:
    """Decimale senza zeri finali, virgola italiana («4,1», «10»)."""
    if valore is None:
        return ""
    testo = format(valore.normalize(), "f") if hasattr(valore, "normalize") else str(valore)
    return testo.replace(".", ",")


def _fine_mese(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


class RuoloProcesso(models.Model):
    """Ruolo sul processo (es. P11TF12: Ingegneria, Programmazione, Operatore macchina...)."""

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="ruoli",
    )
    nome = models.CharField(max_length=120)
    competenza = models.ForeignKey(
        "anagrafica.CompetenzaSkm", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ruoli_processo", verbose_name="Mansione della skill matrix",
        help_text="Facoltativa: collega il ruolo alla mansione lavorativa corrispondente.",
    )
    ordine = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["processo", "ordine", "nome"]
        verbose_name = "Ruolo del processo (MPQ)"
        verbose_name_plural = "Ruoli del processo (MPQ)"
        constraints = [
            models.UniqueConstraint(fields=["processo", "nome"], name="mpq_uniq_ruolo_processo"),
        ]

    def __str__(self) -> str:
        return self.nome


class RequisitoPersona(models.Model):
    """Cosa serve a una persona per essere qualificata sul processo (per ruolo).

    Una tantum (es. formazione iniziale) o ricorrente ogni N mesi (es. corso
    P11TF12 annuale): la scadenza è della persona, non del processo.
    """

    TIPO_CORSO = "corso"
    TIPO_VISITA = "visita"
    TIPO_TEST_VISIVO = "test_visivo"
    TIPO_ESAME = "esame"
    TIPO_ESPERIENZA = "esperienza"
    TIPO_AFFIANCAMENTO = "affiancamento"
    TIPO_CERTIFICATO = "certificato"
    TIPO_QUALIFICA = "qualifica"
    TIPO_DPI = "dpi"
    TIPO_ALTRO = "altro"
    TIPO_CHOICES = [
        (TIPO_CORSO, "Corso di formazione"),
        (TIPO_VISITA, "Visita medica"),
        (TIPO_QUALIFICA, "Qualifica del catalogo"),
        (TIPO_DPI, "DPI consegnato"),
        (TIPO_TEST_VISIVO, "Test visivo"),
        (TIPO_ESAME, "Esame / verifica di competenza"),
        (TIPO_ESPERIENZA, "Ore di esperienza"),
        (TIPO_AFFIANCAMENTO, "Affiancamento"),
        (TIPO_CERTIFICATO, "Certificato"),
        (TIPO_ALTRO, "Altro"),
    ]
    # Tipi la cui evidenza vive altrove (formazione, visite): niente doppioni.
    # Letti dal modulo che li gestisce (Formazione, Visite, Qualifiche, DPI): nessun doppione.
    TIPI_DA_ALTRI_MODULI = (TIPO_CORSO, TIPO_VISITA, TIPO_QUALIFICA, TIPO_DPI)

    RICORRENZA_UNA_TANTUM = "UNA_TANTUM"
    RICORRENZA_RICORRENTE = "RICORRENTE"
    RICORRENZA_CHOICES = [
        (RICORRENZA_UNA_TANTUM, "Una tantum"),
        (RICORRENZA_RICORRENTE, "Ricorrente"),
    ]

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="requisiti_persona",
    )
    ruoli = models.ManyToManyField(
        RuoloProcesso, blank=True, related_name="requisiti",
        help_text="Vuoto = vale per tutti i ruoli del processo.",
    )
    tipo = models.CharField(max_length=16, choices=TIPO_CHOICES, default=TIPO_CORSO)
    descrizione = models.CharField(max_length=255, blank=True, default="")
    corso = models.ForeignKey(
        "anagrafica.TrainingCourse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requisiti_persona_mpq",
    )
    tipo_visita = models.ForeignKey(
        "anagrafica.TipoVisitaMedica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requisiti_persona_mpq",
    )
    tipo_qualifica = models.ForeignKey(
        "anagrafica.TipoQualifica", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requisiti_persona_mpq",
    )
    categoria_dpi = models.ForeignKey(
        "dpi.CategoriaDPI", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requisiti_persona_mpq",
    )
    ricorrenza = models.CharField(
        max_length=12, choices=RICORRENZA_CHOICES, default=RICORRENZA_RICORRENTE,
    )
    frequenza_mesi = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Ogni (mesi)",
        help_text="Solo per i requisiti ricorrenti (es. 12 = ogni anno).",
    )
    scadenza_fine_mese = models.BooleanField(
        default=False, verbose_name="Scade a fine mese",
        help_text="Come le qualifiche CND: la scadenza cade l'ultimo giorno del mese.",
    )
    ore_minime = models.DecimalField(
        max_digits=7, decimal_places=1, null=True, blank=True,
        help_text="Per «Ore di esperienza»: ore da raggiungere.",
    )
    bloccante = models.BooleanField(
        default=True, help_text="Se manca o è scaduto, la persona non è operativa sul processo.",
    )
    # Requisiti alternativi: righe con lo stesso testo = basta una (es. «Livello 2 UT» oppure
    # «Livello 3 UT»). Vale la migliore della persona; non diventano obblighi in Formazione/Visite.
    gruppo_alternativo = models.CharField(
        max_length=30, blank=True, default="", verbose_name="Alternativa (basta una fra…)",
        help_text="Scrivi lo stesso nome su più righe (es. «UT») per dire che basta una di queste. "
                  "Le alternative non diventano obblighi in Formazione e Visite: si vede qui chi manca.",
    )
    attivo = models.BooleanField(default=True)
    ordine = models.PositiveSmallIntegerField(default=0)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["processo", "ordine", "id"]
        verbose_name = "Requisito persona (MPQ)"
        verbose_name_plural = "Requisiti persona (MPQ)"

    def __str__(self) -> str:
        return self.etichetta

    @property
    def etichetta(self) -> str:
        if self.descrizione:
            return self.descrizione
        if self.tipo == self.TIPO_CORSO and self.corso_id:
            return self.corso.titolo
        if self.tipo == self.TIPO_VISITA and self.tipo_visita_id:
            return self.tipo_visita.nome
        if self.tipo == self.TIPO_QUALIFICA and self.tipo_qualifica_id:
            return self.tipo_qualifica.nome
        if self.tipo == self.TIPO_DPI and self.categoria_dpi_id:
            return getattr(self.categoria_dpi, "nome", str(self.categoria_dpi))
        return self.get_tipo_display()

    @property
    def is_ricorrente(self) -> bool:
        return self.ricorrenza == self.RICORRENZA_RICORRENTE and bool(self.frequenza_mesi)

    @property
    def is_obbligo(self) -> bool:
        """Bloccante e non alternativo: diventa un obbligo vero nei moduli collegati."""
        return self.bloccante and not self.gruppo_alternativo

    def scadenza_da(self, data_esecuzione):
        """Scadenza calcolata da una data di esecuzione (None = non scade)."""
        if not data_esecuzione or not self.is_ricorrente:
            return None
        scad = _add_months(data_esecuzione, int(self.frequenza_mesi))
        return _fine_mese(scad) if self.scadenza_fine_mese else scad


class EvidenzaRequisitoPersona(models.Model):
    """Evidenza di un requisito persona (test visivo, esame, ore, affiancamento...).

    Corsi e visite NON passano da qui: si leggono da Formazione e Visite.
    """

    ESITO_SUPERATO = "SUPERATO"
    ESITO_NON_SUPERATO = "NON_SUPERATO"
    ESITO_CHOICES = [
        (ESITO_SUPERATO, "Superato"),
        (ESITO_NON_SUPERATO, "Non superato"),
    ]

    abilitazione = models.ForeignKey(
        AbilitazioneProcesso, on_delete=models.CASCADE, related_name="evidenze",
    )
    requisito = models.ForeignKey(
        RequisitoPersona, on_delete=models.CASCADE, related_name="evidenze",
    )
    data_esecuzione = models.DateField()
    esito = models.CharField(max_length=14, choices=ESITO_CHOICES, default=ESITO_SUPERATO)
    ore = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    data_scadenza = models.DateField(
        null=True, blank=True,
        help_text="Vuoto = calcolata dalla ricorrenza del requisito.",
    )
    documento = models.FileField(
        upload_to=_documento_mpq_upload_to, storage=PrivateAnagraficaStorage(),
        null=True, blank=True,
    )
    documento_nome_originale = models.CharField(max_length=255, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    registrato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_esecuzione", "-id"]
        verbose_name = "Evidenza requisito persona (MPQ)"
        verbose_name_plural = "Evidenze requisito persona (MPQ)"

    def __str__(self) -> str:
        return f"{self.requisito_id} · {self.data_esecuzione}"

    @property
    def scadenza_effettiva(self):
        return self.data_scadenza or self.requisito.scadenza_da(self.data_esecuzione)


class QualificaMacchina(models.Model):
    """Qualifica di una macchina (asset) su un processo, con scadenza propria."""

    STATO_DA_QUALIFICARE = "DA_QUALIFICARE"
    STATO_QUALIFICATA = "QUALIFICATA"
    STATO_DA_VALUTARE = "DA_VALUTARE"
    STATO_SOSPESA = "SOSPESA"
    STATO_DECLASSATA = "DECLASSATA"
    STATO_RITIRATA = "RITIRATA"
    STATO_CHOICES = [
        (STATO_DA_QUALIFICARE, "Da qualificare"),
        (STATO_QUALIFICATA, "Qualificata"),
        (STATO_DA_VALUTARE, "Da valutare dopo manutenzione"),
        (STATO_SOSPESA, "Sospesa"),
        (STATO_DECLASSATA, "Declassata"),
        (STATO_RITIRATA, "Non più usata nel processo"),
    ]
    # Stati con cui la macchina può lavorare il processo (se non scaduta).
    STATI_OPERATIVI = (STATO_QUALIFICATA, STATO_DECLASSATA)

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="qualifiche_macchina",
    )
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.CASCADE, related_name="qualifiche_processo",
    )
    stato = models.CharField(max_length=16, choices=STATO_CHOICES, default=STATO_DA_QUALIFICARE,
                             db_index=True)
    data_qualifica = models.DateField(null=True, blank=True)
    frequenza_mesi = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Ripeti ogni (mesi)",
        help_text="Vuoto = la qualifica non scade (salvo sospensione).",
    )
    data_scadenza = models.DateField(
        null=True, blank=True, help_text="Vuoto = calcolata da data qualifica + frequenza.",
    )
    motivo_stato = models.CharField(max_length=255, blank=True, default="")
    limitazioni = models.TextField(
        blank=True, default="", help_text="Per una macchina declassata: lavorazioni escluse.",
    )
    note = models.TextField(blank=True, default="")
    aggiornato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["processo", "asset__asset_tag"]
        verbose_name = "Qualifica macchina (MPQ)"
        verbose_name_plural = "Qualifiche macchina (MPQ)"
        constraints = [
            models.UniqueConstraint(fields=["processo", "asset"], name="mpq_uniq_qualifica_macchina"),
        ]

    def __str__(self) -> str:
        return f"{self.asset_id} · {self.processo_id} · {self.stato}"

    @property
    def scadenza_effettiva(self):
        if self.data_scadenza:
            return self.data_scadenza
        if self.data_qualifica and self.frequenza_mesi:
            return _add_months(self.data_qualifica, int(self.frequenza_mesi))
        return None

    def is_scaduta(self, oggi=None) -> bool:
        scad = self.scadenza_effettiva
        return bool(scad and scad < (oggi or timezone.localdate()))

    def is_operativa(self, oggi=None) -> bool:
        return self.stato in self.STATI_OPERATIVI and not self.is_scaduta(oggi)


class RequisitoMacchina(models.Model):
    """Cosa serve a una macchina del processo: manutenzioni, tarature, controlli.

    Collegato a un piano del motore manutenzioni: lo stato si legge dalle
    scadenze di quel piano sull'asset (nessuna scadenza duplicata).
    """

    TIPO_VERIFICA = "VERIFICA_PERIODICA"
    TIPO_MANUTENZIONE = "MANUTENZIONE"
    TIPO_TARATURA = "TARATURA"
    TIPO_CONTROLLO = "CONTROLLO_GIORNALIERO"
    TIPO_ALTRO = "ALTRO"
    TIPO_CHOICES = [
        (TIPO_VERIFICA, "Verifica periodica"),
        (TIPO_MANUTENZIONE, "Manutenzione programmata"),
        (TIPO_TARATURA, "Taratura"),
        (TIPO_CONTROLLO, "Controllo a bordo macchina"),
        (TIPO_ALTRO, "Altro"),
    ]

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="requisiti_macchina",
    )
    tipo = models.CharField(max_length=24, choices=TIPO_CHOICES, default=TIPO_MANUTENZIONE)
    descrizione = models.CharField(max_length=255)
    piano = models.ForeignKey(
        "assets.MaintenanceInterventionTemplate", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requisiti_mpq", verbose_name="Piano di manutenzione",
        help_text="Lo stato si legge dalle scadenze di questo piano sulla macchina.",
    )
    ricorrenza = models.CharField(
        max_length=60, blank=True, default="", help_text="Solo descrittiva (es. «ogni giorno»).",
    )
    bloccante = models.BooleanField(
        default=True, help_text="Se scaduto, la macchina non è operativa sul processo.",
    )
    attivo = models.BooleanField(default=True)
    ordine = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["processo", "ordine", "id"]
        verbose_name = "Requisito macchina (MPQ)"
        verbose_name_plural = "Requisiti macchina (MPQ)"

    def __str__(self) -> str:
        return self.descrizione


class ParametroVerificaMacchina(models.Model):
    """Voce della verifica di qualifica (es. MOD.161: giri ±10%, avanzamento ±15%)."""

    TIPO_TOLLERANZA = "TOLLERANZA"
    TIPO_MINIMO = "MINIMO"
    TIPO_PROVA = "PROVA"
    TIPO_CHOICES = [
        (TIPO_TOLLERANZA, "Misura con tolleranza ± %"),
        (TIPO_MINIMO, "Misura con valore minimo"),
        (TIPO_PROVA, "Prova funzionale (conforme / non conforme)"),
    ]

    processo = models.ForeignKey(
        ProcessoQualificato, on_delete=models.CASCADE, related_name="parametri_verifica",
    )
    nome = models.CharField(max_length=150)
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default=TIPO_TOLLERANZA)
    unita = models.CharField(max_length=20, blank=True, default="")
    tolleranza_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    valore_minimo = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    ordine = models.PositiveSmallIntegerField(default=0)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["processo", "ordine", "id"]
        verbose_name = "Parametro verifica macchina (MPQ)"
        verbose_name_plural = "Parametri verifica macchina (MPQ)"

    def __str__(self) -> str:
        return self.nome

    @property
    def criterio(self) -> str:
        if self.tipo == self.TIPO_TOLLERANZA:
            return f"± {numero_breve(self.tolleranza_pct)}%"
        if self.tipo == self.TIPO_MINIMO:
            return f"≥ {numero_breve(self.valore_minimo)} {self.unita}".strip()
        return "conforme / non conforme"


class VerificaMacchina(models.Model):
    """Verifica di qualifica di una macchina (iniziale, periodica, riqualifica)."""

    TIPO_INIZIALE = "INIZIALE"
    TIPO_PERIODICA = "PERIODICA"
    TIPO_RIQUALIFICA = "RIQUALIFICA"
    TIPO_CHOICES = [
        (TIPO_INIZIALE, "Qualifica iniziale"),
        (TIPO_PERIODICA, "Verifica periodica"),
        (TIPO_RIQUALIFICA, "Riqualifica dopo manutenzione"),
    ]
    ESITO_OK = "OK"
    ESITO_KO = "KO"
    ESITO_CHOICES = [(ESITO_OK, "Conforme"), (ESITO_KO, "Non conforme")]

    qualifica = models.ForeignKey(
        QualificaMacchina, on_delete=models.CASCADE, related_name="verifiche",
    )
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default=TIPO_PERIODICA)
    data = models.DateField()
    esito = models.CharField(max_length=2, choices=ESITO_CHOICES, default=ESITO_OK)
    eseguita_da = models.CharField(max_length=150, blank=True, default="")
    documento = models.FileField(
        upload_to=_documento_mpq_upload_to, storage=PrivateAnagraficaStorage(),
        null=True, blank=True, help_text="Rapporto firmato (es. MOD.161).",
    )
    documento_nome_originale = models.CharField(max_length=255, blank=True, default="")
    note = models.TextField(blank=True, default="")
    registrato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]
        verbose_name = "Verifica macchina (MPQ)"
        verbose_name_plural = "Verifiche macchina (MPQ)"

    def __str__(self) -> str:
        return f"{self.qualifica_id} · {self.data} · {self.esito}"


class VerificaMacchinaMisura(models.Model):
    """Riga della verifica: valore nominale/misurato e conformità calcolata."""

    verifica = models.ForeignKey(
        VerificaMacchina, on_delete=models.CASCADE, related_name="misure",
    )
    parametro = models.ForeignKey(
        ParametroVerificaMacchina, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    nome = models.CharField(max_length=150)
    tipo = models.CharField(max_length=12, choices=ParametroVerificaMacchina.TIPO_CHOICES)
    unita = models.CharField(max_length=20, blank=True, default="")
    tolleranza_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    valore_minimo = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    nominale = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    misurato = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    scostamento_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    conforme = models.BooleanField(default=True)

    class Meta:
        ordering = ["verifica", "id"]
        verbose_name = "Misura verifica macchina (MPQ)"
        verbose_name_plural = "Misure verifica macchina (MPQ)"

    def __str__(self) -> str:
        return self.nome

    @property
    def criterio(self) -> str:
        return ParametroVerificaMacchina.criterio.fget(self)

    TIPO_TOLLERANZA = ParametroVerificaMacchina.TIPO_TOLLERANZA
    TIPO_MINIMO = ParametroVerificaMacchina.TIPO_MINIMO

    @property
    def nominale_txt(self) -> str:
        return f"{numero_breve(self.nominale)} {self.unita}".strip() if self.nominale is not None else "—"

    @property
    def misurato_txt(self) -> str:
        return f"{numero_breve(self.misurato)} {self.unita}".strip() if self.misurato is not None else "—"

    @property
    def scostamento_txt(self) -> str:
        return f"{numero_breve(self.scostamento_pct)}%" if self.scostamento_pct is not None else "—"
