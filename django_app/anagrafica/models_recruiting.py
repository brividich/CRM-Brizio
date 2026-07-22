"""Recruiting MOD. 05-01 — Valutazione Selezione Risorse (strato additivo).

Modulo *additivo* dentro l'app ``anagrafica``: digitalizza il Mod. 05-01 usato da
HR per tracciare i colloqui di selezione, riusando l'Onboarding strutturato già
presente (``services/onboarding.py``) per la transizione di fine iter.

Scelte strutturali che rispondono alla certificazione UNI/PdR 125 (parità di
genere), che richiede processi di selezione oggettivi e tracciabili:

- i criteri di valutazione sono **righe di tabella** (:class:`RecruitingCriterio`),
  non campi del modello: pesi, rubriche e disattivazione sono decisioni HR
  eseguibili dall'interfaccia, senza migrazione;
- un punteggio può esistere **solo** in relazione a un criterio
  (:class:`CandidatoPunteggio`): età e cittadinanza sono campi scalari di
  :class:`Candidato` e non hanno alcun percorso, nemmeno indiretto, verso il
  calcolo del ponderato;
- ogni cambio di punteggio o di giudizio finale è registrato in
  :class:`CandidatoLog` con autore, istante e valore precedente.

Convenzioni del progetto rispettate (come ``models_mpq``):
- dipendente agganciato via ``legacy_anagrafica_id`` (IntegerField), **nessuna FK**
  al modello dipendente legacy;
- compatibilità SQL Server (mssql-django): nessun indice parziale, nessun
  ``UniqueConstraint`` con ``condition``, nessun campo ``unique`` nullable;
- FK verso gli altri modelli via *string reference* per evitare import ciclici.

Importato in ``anagrafica/models.py`` con ``from .models_recruiting import *``.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

__all__ = [
    "RecruitingCriterio",
    "Candidato",
    "CandidatoPunteggio",
    "CandidatoLog",
    "RecruitingPermission",
]


# Criteri e pesi del Mod. 05-01 originale. Servono solo a *seedare* la tabella
# alla prima migrazione: da lì in poi la fonte di verità è il DB.
CRITERI_SEED = [
    {
        "codice": "sintonia",
        "label": "Sintonia",
        "peso_percentuale": Decimal("20.00"),
        "ordine": 10,
        "descrizione": "Allineamento con il contesto e lo stile di lavoro dell'azienda.",
    },
    {
        "codice": "vicinanza",
        "label": "Vicinanza",
        "peso_percentuale": Decimal("15.00"),
        "ordine": 20,
        "descrizione": "Prossimità logistica alla sede di lavoro.",
    },
    {
        "codice": "esperienze_pregresse",
        "label": "Esperienze pregresse (altro settore)",
        "peso_percentuale": Decimal("25.00"),
        "ordine": 30,
        "descrizione": "Esperienze professionali maturate, anche in settori diversi.",
    },
    {
        "codice": "capacita_relazionali",
        "label": "Capacità relazionali",
        "peso_percentuale": Decimal("20.00"),
        "ordine": 40,
        "descrizione": "Capacità di relazione e collaborazione in squadra.",
    },
    {
        "codice": "competenze_tecniche",
        "label": "Competenze tecniche (da CV)",
        "peso_percentuale": Decimal("20.00"),
        "ordine": 50,
        "descrizione": "Competenze tecniche documentate nel curriculum.",
    },
]


class RecruitingCriterio(models.Model):
    """Criterio di valutazione pesato del colloquio.

    Il peso è configurabile perché la policy HR può cambiare senza che serva una
    migrazione, e perché la disattivazione di un criterio discutibile (es.
    "Vicinanza", possibile proxy indiretto di caratteristiche protette) deve
    essere una scelta HR reversibile, non una modifica di codice.
    """

    codice = models.SlugField(max_length=60, unique=True)
    label = models.CharField(max_length=160)
    descrizione = models.TextField(blank=True, default="")
    rubrica = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Definizione operativa dei livelli 1-5 con esempi. Una rubrica esplicita "
            "rende il criterio difendibile in un audit UNI/PdR 125."
        ),
    )
    peso_percentuale = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    ordine = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "label"]
        verbose_name = "Criterio di valutazione (Recruiting)"
        verbose_name_plural = "Criteri di valutazione (Recruiting)"

    def __str__(self) -> str:
        return f"{self.label} ({self.peso_percentuale}%)"


class Candidato(models.Model):
    """Scheda candidato: anagrafica, esito CV, colloquio 1, colloquio 2, esito.

    Una sola entità per l'intero iter: il secondo colloquio vive sulla stessa
    riga del primo, come nel foglio Excel di partenza.
    """

    # --- Stato dell'iter ---------------------------------------------------
    STATO_NUOVO = "NUOVO"
    STATO_CV_VALUTATO = "CV_VALUTATO"
    STATO_COLLOQUIO_1 = "COLLOQUIO_1"
    STATO_COLLOQUIO_2 = "COLLOQUIO_2"
    STATO_ASSUNTO = "ASSUNTO"
    STATO_IN_DATABASE = "IN_DATABASE"
    STATO_SCARTATO = "SCARTATO"
    STATO_RINUNCIA = "RINUNCIA"

    STATO_CHOICES = [
        (STATO_NUOVO, "Nuovo (CV ricevuto)"),
        (STATO_CV_VALUTATO, "CV valutato"),
        (STATO_COLLOQUIO_1, "Primo colloquio effettuato"),
        (STATO_COLLOQUIO_2, "Secondo colloquio effettuato"),
        (STATO_ASSUNTO, "Assunto"),
        (STATO_IN_DATABASE, "In database per future opportunità"),
        (STATO_SCARTATO, "Non idoneo"),
        (STATO_RINUNCIA, "Rinuncia del candidato"),
    ]
    # Stati che chiudono l'iter: nessuna valutazione ulteriore attesa.
    STATI_CHIUSI = (STATO_ASSUNTO, STATO_IN_DATABASE, STATO_SCARTATO, STATO_RINUNCIA)

    # --- Canale di provenienza del CV --------------------------------------
    CANALE_AUTOCANDIDATURA = "AUTOCANDIDATURA"
    CANALE_AGENZIA = "AGENZIA"
    CANALE_COLLOCAMENTO_MIRATO = "COLLOCAMENTO_MIRATO"
    CANALE_SEGNALAZIONE = "SEGNALAZIONE"
    CANALE_ANNUNCIO = "ANNUNCIO"
    CANALE_SCUOLA = "SCUOLA"
    CANALE_ALTRO = "ALTRO"

    CANALE_CHOICES = [
        (CANALE_AUTOCANDIDATURA, "Autocandidatura"),
        (CANALE_AGENZIA, "Agenzia interinale"),
        (CANALE_COLLOCAMENTO_MIRATO, "Collocamento mirato"),
        (CANALE_SEGNALAZIONE, "Segnalazione"),
        (CANALE_ANNUNCIO, "Annuncio / portale online"),
        (CANALE_SCUOLA, "Scuola / università"),
        (CANALE_ALTRO, "Altro"),
    ]

    CV_OK = "OK"
    CV_KO = "KO"
    CV_CHOICES = [(CV_OK, "OK"), (CV_KO, "Non idoneo")]

    GIUDIZIO_POSITIVO = "POSITIVO"
    GIUDIZIO_NEGATIVO = "NEGATIVO"
    GIUDIZIO_CHOICES = [
        (GIUDIZIO_POSITIVO, "Positivo"),
        (GIUDIZIO_NEGATIVO, "Negativo"),
    ]

    COMUNICAZIONE_SI = "SI"
    COMUNICAZIONE_NO = "NO"
    COMUNICAZIONE_ACADEMY = "ACADEMY"
    COMUNICAZIONE_RINUNCIA = "RINUNCIA"
    COMUNICAZIONE_CHOICES = [
        (COMUNICAZIONE_SI, "Esito comunicato"),
        (COMUNICAZIONE_NO, "Non comunicato"),
        (COMUNICAZIONE_ACADEMY, "Indirizzato ad academy"),
        (COMUNICAZIONE_RINUNCIA, "Rinuncia del candidato"),
    ]

    # --- Anagrafica e provenienza ------------------------------------------
    cognome = models.CharField(max_length=120, db_index=True)
    nome = models.CharField(max_length=120, db_index=True)
    cellulare = models.CharField(max_length=40, blank=True, default="")
    email = models.EmailField(max_length=254, blank=True, default="")
    localita = models.CharField(max_length=120, blank=True, default="")
    provincia = models.CharField(max_length=4, blank=True, default="")

    canale_provenienza = models.CharField(
        max_length=32, choices=CANALE_CHOICES, default=CANALE_AUTOCANDIDATURA, db_index=True,
    )
    canale_dettaglio = models.CharField(
        max_length=160, blank=True, default="",
        help_text="Nome agenzia, portale o segnalatore (se pertinente).",
    )

    mansione_cercata = models.CharField(max_length=160, blank=True, default="", db_index=True)
    azienda_attuale = models.CharField(max_length=160, blank=True, default="")
    mansione_attuale = models.CharField(max_length=160, blank=True, default="")
    livello_contratto_attuale = models.CharField(max_length=120, blank=True, default="")
    occupato_attualmente = models.BooleanField(null=True, blank=True)

    # --- Dati informativi: MAI usati nel calcolo del punteggio -------------
    # Restano in scheda perché HR ne ha bisogno (fasce di tutela, permessi di
    # soggiorno, requisiti di titolo), ma non esiste alcun percorso da questi
    # campi al punteggio ponderato: quello legge solo CandidatoPunteggio.
    eta = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Dato informativo. Non concorre in alcun modo al punteggio.",
    )
    titolo_studio = models.CharField(max_length=160, blank=True, default="")
    cittadinanza = models.CharField(
        max_length=120, blank=True, default="",
        help_text="Dato informativo. Non concorre in alcun modo al punteggio.",
    )

    # --- Esito CV e primo colloquio ----------------------------------------
    data_primo_colloquio = models.DateField(null=True, blank=True, db_index=True)
    cv_esito = models.CharField(max_length=4, choices=CV_CHOICES, blank=True, default="")
    colloquio_effettuato = models.BooleanField(default=False)

    punteggio_ponderato = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        help_text="Media pesata dei criteri attivi. Calcolata dal server, non modificabile a mano.",
    )
    punteggio_aggiornato_il = models.DateTimeField(null=True, blank=True)

    lingua_inglese_livello = models.CharField(max_length=60, blank=True, default="")
    idoneita_tirocinio = models.BooleanField(null=True, blank=True)
    idoneita_apprendistato = models.BooleanField(null=True, blank=True)
    disponibilita = models.CharField(max_length=200, blank=True, default="")
    motivo_cambio_lavoro = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    rischio_abbandono = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Scala 1-10.",
    )
    giudizio_finale = models.CharField(
        max_length=10, choices=GIUDIZIO_CHOICES, blank=True, default="", db_index=True,
    )

    # --- Secondo colloquio --------------------------------------------------
    data_secondo_colloquio = models.DateField(null=True, blank=True)
    note_secondo_colloquio = models.TextField(blank=True, default="")
    comunicazione_esito = models.CharField(
        max_length=12, choices=COMUNICAZIONE_CHOICES, blank=True, default="",
    )
    data_assunzione = models.DateField(null=True, blank=True)

    # --- Esito dell'iter ----------------------------------------------------
    stato = models.CharField(
        max_length=16, choices=STATO_CHOICES, default=STATO_NUOVO, db_index=True,
    )
    legacy_anagrafica_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="Id del dipendente creato in anagrafica quando il candidato viene assunto.",
    )
    onboarding_pratica = models.ForeignKey(
        "anagrafica.OnboardingPratica",
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="candidati_recruiting",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="candidati_creati",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="candidati_aggiornati",
    )

    class Meta:
        ordering = ["-created_at", "cognome", "nome"]
        verbose_name = "Candidato (Recruiting)"
        verbose_name_plural = "Candidati (Recruiting)"
        indexes = [
            models.Index(fields=["stato", "-created_at"], name="recr_cand_stato_idx"),
            models.Index(fields=["cognome", "nome"], name="recr_cand_nome_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.cognome} {self.nome}".strip() or f"Candidato #{self.pk}"

    @property
    def nominativo(self) -> str:
        return f"{self.cognome} {self.nome}".strip()

    @property
    def iter_chiuso(self) -> bool:
        return self.stato in self.STATI_CHIUSI

    @property
    def giorni_tra_colloqui(self) -> int | None:
        """Giorni tra primo e secondo colloquio (None se manca una delle due date)."""
        if not self.data_primo_colloquio or not self.data_secondo_colloquio:
            return None
        return (self.data_secondo_colloquio - self.data_primo_colloquio).days


class CandidatoPunteggio(models.Model):
    """Voto 1-5 di un candidato su un criterio.

    Unica sorgente possibile del punteggio ponderato: nessun campo anagrafico
    del candidato può entrare nel calcolo perché il calcolo legge solo qui.
    """

    candidato = models.ForeignKey(
        Candidato, on_delete=models.CASCADE, related_name="punteggi",
    )
    criterio = models.ForeignKey(
        RecruitingCriterio, on_delete=models.PROTECT, related_name="punteggi",
    )
    valore = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    # Peso al momento della valutazione: se HR ripesa i criteri in seguito, le
    # schede già chiuse restano leggibili con i pesi con cui furono decise.
    peso_snapshot = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["criterio__ordine", "criterio__label"]
        verbose_name = "Punteggio criterio (Recruiting)"
        verbose_name_plural = "Punteggi criteri (Recruiting)"
        constraints = [
            models.UniqueConstraint(
                fields=["candidato", "criterio"], name="recr_punteggio_unico_per_criterio",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.candidato} — {self.criterio.label}: {self.valore}"


class CandidatoLog(models.Model):
    """Traccia di ogni cambio di punteggio o giudizio: chi, quando, valore prima.

    È l'evidenza di tracciabilità delle decisioni richiesta in audit UNI/PdR 125.
    Affianca ``core.audit.log_action``, che resta il registro di sicurezza del
    portale: questo è invece visibile in scheda all'utente HR.
    """

    TIPO_PUNTEGGIO = "PUNTEGGIO"
    TIPO_GIUDIZIO = "GIUDIZIO"
    TIPO_STATO = "STATO"
    TIPO_CHOICES = [
        (TIPO_PUNTEGGIO, "Punteggio criterio"),
        (TIPO_GIUDIZIO, "Giudizio finale"),
        (TIPO_STATO, "Stato dell'iter"),
    ]

    candidato = models.ForeignKey(
        Candidato, on_delete=models.CASCADE, related_name="log_modifiche",
    )
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, db_index=True)
    campo = models.CharField(max_length=120)
    valore_prima = models.CharField(max_length=255, blank=True, default="")
    valore_dopo = models.CharField(max_length=255, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    user_display = models.CharField(max_length=160, blank=True, default="")
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "Modifica tracciata (Recruiting)"
        verbose_name_plural = "Modifiche tracciate (Recruiting)"

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} — {self.campo}: {self.valore_prima} → {self.valore_dopo}"


class RecruitingPermission(models.Model):
    """Singleton: chi può vedere/gestire le schede candidato.

    Stesso schema di ``AnagraficaVisiteMedichePermission`` e stesso default
    restrittivo: le schede contengono età, cittadinanza e note libere che
    possono riportare situazioni familiari o di salute. Non è una sezione da
    lasciare aperta a tutto il gestionale.
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
        verbose_name = "Permessi Recruiting"
        verbose_name_plural = "Permessi Recruiting"

    def __str__(self) -> str:
        return f"Permessi Recruiting ({self.get_accesso_display()})"

    @classmethod
    def get_instance(cls) -> "RecruitingPermission":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"accesso": cls.ACCESSO_ADMIN})
        return obj
