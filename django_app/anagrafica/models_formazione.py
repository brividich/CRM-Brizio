"""Modelli formazione HR — NOVICROM HUB.

File separato importato da anagrafica/models.py tramite `from .models_formazione import *`.
Non spostare, non rinominare senza aggiornare l'import nel file principale.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from .storage import PrivateAnagraficaStorage

__all__ = [
    "AnagraficaFormazionePermission",
    "TrainingPlan",
    "TrainingCourse",
    "TrainingCourseVersion",
    "TrainingCompletionRule",
    "TrainingCourseDependency",
    "TrainingCourseModule",
    "TrainingRequirementRule",
    "TrainingInstructor",
    "TrainingAssignment",
    "TrainingSession",
    "TrainingLesson",
    "TrainingEnrollment",
    "TrainingEnrollmentLesson",
    "TrainingLessonAttendance",
    "TrainingEmployeeRecord",
    "TrainingCertificate",
    "TrainingDeadline",
    "TrainingExportLog",
    "TrainingAttachment",
    # E-learning (micro-corsi interni: slide + quiz)
    "TrainingSlide",
    "TrainingQuizQuestion",
    "TrainingQuizOption",
    "TrainingElearningEnrollment",
    "TrainingQuizAttempt",
    "ElearningConfig",
]


# ─────────────────────────────────────────────────────────────
# PERMESSO ACCESSO (Singleton)
# ─────────────────────────────────────────────────────────────

class AnagraficaFormazionePermission(models.Model):
    """Singleton — chi può accedere/gestire la sezione formazione.
    Pattern identico a AnagraficaVisiteMedichePermission.
    """

    ACCESSO_TUTTI = "TUTTI"
    ACCESSO_ADMIN = "ADMIN"
    ACCESSO_RUOLI = "RUOLI"

    ACCESSO_CHOICES = [
        (ACCESSO_TUTTI, "Tutti gli utenti autenticati"),
        (ACCESSO_ADMIN, "Solo amministratori"),
        (ACCESSO_RUOLI, "Ruoli ACL specifici"),
    ]

    accesso_visualizzazione = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    accesso_modifica        = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    accesso_export          = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    accesso_validazione     = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    accesso_report_firma    = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default=ACCESSO_ADMIN)
    ruoli_autorizzati_json  = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Permesso accesso formazione"
        verbose_name_plural = "Permessi accesso formazione"

    def __str__(self) -> str:
        return f"Permessi formazione ({self.get_accesso_visualizzazione_display()})"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_instance(cls) -> "AnagraficaFormazionePermission":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"accesso_visualizzazione": cls.ACCESSO_ADMIN})
        return obj


# ─────────────────────────────────────────────────────────────
# ATTESTATO — configurazione template (singleton, da Impostazioni HR)
# ─────────────────────────────────────────────────────────────

class AttestatoFormazioneConfig(models.Model):
    """Singleton — testi e opzioni del template attestato di formazione.

    L'attestato si autogenera dal record di completamento: questo modello
    permette di personalizzare le parti fisse (intestazioni, formule, etichette
    firma, nota legale, logo) dalle Impostazioni Anagrafica HR, senza toccare il
    template. I default replicano i testi originali del foglio.
    """

    NOTA_LEGALE_DEFAULT = (
        "Documento valido ai fini della tracciabilità formativa interna, anche in "
        "relazione agli obblighi di informazione, formazione e addestramento "
        "previsti dal D.Lgs. 81/2008."
    )

    intestazione_eyebrow     = models.CharField(max_length=80, default="Formazione interna")
    sezione_label            = models.CharField(max_length=120, default="NOVICROM HUB · Attestazione formativa")
    titolo_partecipazione    = models.CharField(max_length=120, default="Attestato di partecipazione")
    titolo_frequenza         = models.CharField(max_length=120, default="Attestato di frequenza")
    titolo_qualifica         = models.CharField(max_length=120, default="Attestato di qualifica")
    formula_attestazione     = models.CharField(max_length=200, default="Si attesta che")
    firma_responsabile_label = models.CharField(max_length=80, default="Il Responsabile del corso")
    firma_dipendente_label   = models.CharField(max_length=80, default="Il Dipendente")
    responsabile_default     = models.CharField(
        max_length=200, blank=True,
        help_text="Nome stampato sotto la firma del responsabile quando il corso non ha un docente registrato.",
    )
    mostra_dati_personali    = models.BooleanField(
        default=True,
        help_text="Mostra C.F., luogo e data di nascita sull'attestato (utile per D.Lgs. 81/2008). "
                  "Disattiva per minimizzazione GDPR.",
    )
    nota_legale              = models.TextField(default=NOTA_LEGALE_DEFAULT)
    logo_url                 = models.URLField(
        blank=True,
        help_text="URL del logo in intestazione. Vuoto = logo NOVICROM HUB predefinito.",
    )
    pie_organizzazione       = models.CharField(
        max_length=200, default="NOVICROM HUB · Portale interno · Costruzioni Novicrom S.r.l.",
    )

    # ── Archiviazione automatica nel box documenti del dipendente ──────────
    # Nome della cartella virtuale (uguale per tutti i dipendenti) in cui
    # confluiscono gli attestati. Creata on-demand se non esiste.
    CARTELLA_ATTESTATI_NOME = "Attestati formazione"

    auto_salva_attestato = models.BooleanField(
        default=False,
        help_text="Salva automaticamente l'attestato PDF nel box documenti del dipendente "
                  "alla chiusura del corso (quando l'iscrizione passa a «Completato»).",
    )
    cartella_attestati = models.ForeignKey(
        "anagrafica.CartellaDocumentoDipendente",
        null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
        help_text="Cartella del box documenti in cui archiviare gli attestati. "
                  "Vuoto = usa/crea la cartella predefinita «Attestati formazione».",
    )
    rigenera_se_esiste = models.BooleanField(
        default=False,
        help_text="Se attivo, rigenera e sovrascrive l'attestato già archiviato per lo stesso "
                  "completamento. Se disattivo, l'archiviazione è idempotente (non duplica).",
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = "Impostazioni attestato formazione"
        verbose_name_plural = "Impostazioni attestato formazione"

    def __str__(self) -> str:
        return "Impostazioni attestato formazione"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_instance(cls) -> "AttestatoFormazioneConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AttestatoProtocolloCounter(models.Model):
    """Contatore progressivo annuale del numero di protocollo degli attestati.

    Una riga per anno; ``ultimo`` è l'ultimo numero assegnato. L'allocazione del
    prossimo numero avviene in transazione con ``select_for_update`` per essere
    sicura in concorrenza (vedi ``services.attestato_pdf.assegna_numero_protocollo``).
    """

    PREFISSO = "ATT"

    anno   = models.PositiveSmallIntegerField(unique=True, db_index=True)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Contatore protocollo attestati"
        verbose_name_plural = "Contatori protocollo attestati"

    def __str__(self) -> str:
        return f"{self.PREFISSO}-{self.anno}: {self.ultimo}"


# ─────────────────────────────────────────────────────────────
# PIANO FORMATIVO
# ─────────────────────────────────────────────────────────────

class TrainingPlan(models.Model):
    """Macro-contenitore di corsi (es. 'Sistemi Informatici', 'Sicurezza', 'ESG')."""

    CATEGORIA_CHOICES = [
        ("OBBLIGATORIA", "Obbligatoria"),
        ("CONSIGLIATA",  "Consigliata"),
        ("FACOLTATIVA",  "Facoltativa"),
    ]

    STATO_CHOICES = [
        ("BOZZA",      "Bozza"),
        ("ATTIVO",     "Attivo"),
        ("ARCHIVIATO", "Archiviato"),
    ]

    codice             = models.CharField(max_length=20, unique=True)
    nome               = models.CharField(max_length=200)
    categoria          = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default="CONSIGLIATA")
    stato              = models.CharField(max_length=15, choices=STATO_CHOICES, default="ATTIVO")
    descrizione        = models.TextField(blank=True)
    note               = models.TextField(blank=True)
    ore_totali_stimate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    costo_stimato      = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    provider_esterno   = models.BooleanField(default=False)
    is_active          = models.BooleanField(default=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)
    created_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "Piano formativo"
        verbose_name_plural = "Piani formativi"
        indexes = [models.Index(fields=["categoria", "is_active"])]

    def __str__(self) -> str:
        return f"[{self.codice}] {self.nome}"


# ─────────────────────────────────────────────────────────────
# CORSO
# ─────────────────────────────────────────────────────────────

class TrainingCourse(models.Model):
    """Corso formativo, appartenente a un piano."""

    STATO_CHOICES = [
        ("BOZZA",      "Bozza"),
        ("ATTIVO",     "Attivo"),
        ("ARCHIVIATO", "Archiviato"),
    ]

    FONTE_OBBLIGO_CHOICES = [
        ("LEGGE",    "Norma di legge"),
        ("ACCORDO",  "Accordo Stato-Regioni"),
        ("CLIENTE",  "Specifica cliente"),
        ("NORMA",    "Norma di sistema (ISO, EN, AS…)"),
        ("INTERNO",  "Decisione interna"),
    ]

    piano              = models.ForeignKey(TrainingPlan, on_delete=models.PROTECT, related_name="corsi")
    categoria          = models.ForeignKey(
        "anagrafica.CategoriaCorso", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="corsi",
        help_text="Categoria che lega il corso ai fattori di rischio. Null = nessuna derivazione.",
    )
    # La qualifica è l'àncora (competency management): un corso RILASCIA/RINNOVA
    # una qualifica. Così corso, sessioni e completamenti restano collegati alla
    # qualifica invece di esistere in parallelo. Null = corso non legato a qualifica.
    qualifica          = models.ForeignKey(
        "anagrafica.TipoQualifica", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="corsi",
        help_text="Qualifica/abilitazione rilasciata o rinnovata da questo corso.",
    )
    codice             = models.CharField(max_length=30, unique=True)
    titolo             = models.CharField(max_length=300)
    descrizione        = models.TextField(blank=True)
    durata_ore_teorica = models.DecimalField(max_digits=7, decimal_places=2)
    validita_mesi      = models.PositiveSmallIntegerField(
        default=0,
        help_text="0 = una tantum, altrimenti durata in mesi prima del rinnovo",
    )
    obbligatorio   = models.BooleanField(default=False)
    # ── Diritto soggettivo alla formazione (CCNL) ────────────────────────────
    # Il CCNL riconosce un monte ore di formazione — tipicamente non tecnico/
    # professionale — maturato su una finestra di 3 anni (24h). La formazione
    # dovuta per legge o Accordo Stato-Regioni (sicurezza) non vi concorre: è un
    # obbligo distinto, non un beneficio. Questo flag è indipendente da
    # `obbligatorio`/`fonte_obbligo` (che restano il driver di filtri/idoneità/
    # export già in uso) proprio perché un corso può essere "obbligatorio" per
    # motivi che non sono di sicurezza (cliente, norma di sistema, decisione
    # interna) e in quel caso può comunque concorrere al monte ore CCNL.
    obbligatoria_ccnl = models.BooleanField(
        default=False,
        verbose_name="Formazione obbligatoria (CCNL)",
        help_text="Esclusa dal monte ore facoltativo del CCNL (24h ogni 3 anni). "
                  "Spuntare per la formazione sicurezza da legge o Accordo Stato-Regioni; "
                  "le altre concorrono al monte ore del dipendente.",
    )
    # ── Origine dell'obbligo (catena dell'evidenza, anello 1) ────────────────
    # Da dove nasce il dovere di erogare il corso. Storicamente il riferimento
    # finiva dentro il titolo come testo libero ("Rif. 9070Q", "AWPS004Q rev. B"),
    # quindi non interrogabile: in audit la domanda "mostrami tutti i corsi che
    # discendono dall'Accordo Stato-Regioni" non aveva risposta.
    # Campi NON bloccanti: i corsi storici restano validi senza compilarli.
    fonte_obbligo     = models.CharField(
        max_length=12, choices=FONTE_OBBLIGO_CHOICES, blank=True, default="", db_index=True,
        help_text="Da cosa discende l'obbligo di questo corso. Lasciare vuoto se non pertinente.",
    )
    riferimento_fonte = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Estremi della fonte: es. «D.Lgs 81/08», «Accordo Stato-Regioni 21/12/2011», «Avio 9070Q».",
    )
    articolo_fonte    = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Punto specifico, se utile: es. «art. 37 c. 2», «§ 4.3».",
    )
    # ── E-learning (micro-corso interno: slide sequenziali + quiz finale) ─────
    # Un corso e-learning si fruisce in autonomia dal portale: niente sessione
    # d'aula, niente registro presenze. Gli altri corsi restano "d'aula".
    is_elearning          = models.BooleanField(
        default=False, db_index=True,
        help_text="Micro-corso e-learning: slide sequenziali + quiz finale, fruibile in autonomia.",
    )
    quiz_punteggio_minimo = models.PositiveSmallIntegerField(
        default=70,
        help_text="Percentuale minima di risposte corrette per superare il quiz finale (solo e-learning).",
    )
    costo_unitario = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    stato          = models.CharField(max_length=15, choices=STATO_CHOICES, default="BOZZA")
    note           = models.TextField(blank=True)
    versione       = models.CharField(max_length=10, default="1.0")
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    created_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["titolo"]
        verbose_name = "Corso formativo"
        verbose_name_plural = "Corsi formativi"
        indexes = [
            models.Index(fields=["piano", "stato"]),
            models.Index(fields=["obbligatorio", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"[{self.codice}] {self.titolo}"


# ─────────────────────────────────────────────────────────────
# VERSIONE CORSO
# ─────────────────────────────────────────────────────────────

class TrainingCourseVersion(models.Model):
    """Snapshot versionato di un corso.
    Permette modifiche al corso senza alterare lo storico delle sessioni già tenute.
    """

    corso                  = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="versioni")
    version_label          = models.CharField(max_length=10, help_text="Es. '1.0', '2.1'")
    titolo_snapshot        = models.CharField(max_length=300, blank=True)
    durata_ore_snapshot    = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    validita_mesi_snapshot = models.PositiveSmallIntegerField(null=True, blank=True)
    data_inizio_validita   = models.DateField(null=True, blank=True)
    data_fine_validita     = models.DateField(null=True, blank=True)
    note                   = models.TextField(blank=True)
    is_active              = models.BooleanField(default=True)
    revised_by             = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("corso", "version_label")]
        verbose_name = "Versione corso"
        verbose_name_plural = "Versioni corso"

    def __str__(self) -> str:
        return f"{self.corso.codice} v{self.version_label}"


# ─────────────────────────────────────────────────────────────
# REGOLA DI SUPERAMENTO
# ─────────────────────────────────────────────────────────────

class TrainingCompletionRule(models.Model):
    """Regola configurabile di superamento per un corso. OneToOne su TrainingCourse."""

    corso   = models.OneToOneField(TrainingCourse, on_delete=models.CASCADE, related_name="regola_superamento")
    version = models.ForeignKey(
        TrainingCourseVersion, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    ore_minime_percentuale      = models.PositiveSmallIntegerField(
        default=80,
        help_text="Percentuale minima di ore frequentate rispetto al totale",
    )
    presenza_minima_percentuale = models.PositiveSmallIntegerField(
        default=80,
        help_text="Percentuale minima di presenze alle lezioni",
    )
    richiede_esame_finale   = models.BooleanField(default=False)
    richiede_firma_presenza = models.BooleanField(default=True)
    richiede_attestato      = models.BooleanField(default=False)
    richiede_validazione_hr = models.BooleanField(default=False)
    # Valutazione di efficacia (catena dell'evidenza, anello 8): ISO 45001 §7.2 e
    # ISO 9001 §7.2 non chiedono di aver erogato la formazione, chiedono di
    # sapere se ha prodotto competenza. 0 = non richiesta.
    valutazione_efficacia_mesi = models.PositiveSmallIntegerField(
        default=0,
        help_text="Dopo quanti mesi dal completamento va verificato sul campo se la "
                  "formazione è stata efficace. 0 = valutazione non richiesta.",
    )
    rule_json               = models.JSONField(default=dict, blank=True, help_text="Estensioni future regola")
    valid_from              = models.DateField(null=True, blank=True)
    valid_to                = models.DateField(null=True, blank=True)
    is_active               = models.BooleanField(default=True)
    note                    = models.TextField(blank=True)

    class Meta:
        verbose_name = "Regola di superamento"
        verbose_name_plural = "Regole di superamento"

    def __str__(self) -> str:
        return f"Regola superamento — {self.corso.codice}"


# ─────────────────────────────────────────────────────────────
# PREREQUISITI CORSO
# ─────────────────────────────────────────────────────────────

class TrainingCourseDependency(models.Model):
    """Prerequisito: il corso 'prerequisito' deve essere completato prima di 'corso_principale'."""

    corso_principale = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="prerequisiti")
    prerequisito     = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="sblocca_corsi")
    obbligatorio     = models.BooleanField(default=True)

    class Meta:
        unique_together = [("corso_principale", "prerequisito")]
        verbose_name = "Prerequisito corso"
        verbose_name_plural = "Prerequisiti corso"

    def __str__(self) -> str:
        return f"{self.prerequisito.codice} → {self.corso_principale.codice}"


# ─────────────────────────────────────────────────────────────
# COMPOSIZIONE CORSO (moduli / sotto-corsi)
# ─────────────────────────────────────────────────────────────

class TrainingCourseModule(models.Model):
    """Un corso può essere composto da sotto-moduli (altri corsi)."""

    corso_padre  = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="moduli")
    corso_modulo = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="usato_come_modulo")
    ordine       = models.PositiveSmallIntegerField(default=0)
    obbligatorio = models.BooleanField(default=True)

    class Meta:
        unique_together = [("corso_padre", "corso_modulo")]
        ordering = ["ordine"]
        verbose_name = "Modulo corso"
        verbose_name_plural = "Moduli corso"

    def __str__(self) -> str:
        return f"{self.corso_padre.codice} → modulo {self.corso_modulo.codice}"


# ─────────────────────────────────────────────────────────────
# PROGRAMMA DIDATTICO (catena dell'evidenza, anello 3)
# ─────────────────────────────────────────────────────────────
# Per la formazione dei lavoratori i contenuti minimi sono normati: senza un
# programma dichiarato non si dimostra di averli coperti. Il programma vive su
# due livelli, come deve:
#   - sul CORSO è il previsto, valido nel tempo;
#   - sulla SESSIONE è ciò che quell'edizione ha davvero erogato. Viene copiato
#     dal corso alla creazione (non collegato) e resta modificabile: se il corso
#     cambia domani, l'edizione continua a documentare com'era allora. È la
#     stessa logica degli snapshot già usati per docente e titolo.

class TrainingCourseArgomento(models.Model):
    """Voce del programma didattico previsto dal corso."""

    corso        = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="programma")
    ordine       = models.PositiveSmallIntegerField(default=0)
    argomento    = models.CharField(max_length=300)
    ore_previste = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    riferimento  = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Punto della fonte che impone il contenuto: es. «Allegato A, punto 3».",
    )

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name = "Argomento del corso"
        verbose_name_plural = "Programma del corso"

    def __str__(self) -> str:
        return f"{self.corso.codice} · {self.argomento[:60]}"


class TrainingSessionArgomento(models.Model):
    """Programma effettivo dell'edizione: copia del corso, poi modificabile.

    ``origine`` resta solo come traccia della provenienza: se l'argomento del
    corso viene cancellato, la riga dell'edizione sopravvive (SET_NULL) perché
    documenta un fatto già accaduto.
    """

    sessione     = models.ForeignKey("anagrafica.TrainingSession", on_delete=models.CASCADE, related_name="programma")
    ordine       = models.PositiveSmallIntegerField(default=0)
    argomento    = models.CharField(max_length=300)
    ore_previste = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    riferimento  = models.CharField(max_length=200, blank=True, default="")
    origine      = models.ForeignKey(
        TrainingCourseArgomento, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    aggiunto     = models.BooleanField(
        default=False,
        help_text="Vero se l'edizione ha integrato un argomento non previsto dal corso.",
    )

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name = "Argomento dell'edizione"
        verbose_name_plural = "Programma dell'edizione"

    def __str__(self) -> str:
        return f"{self.sessione.codice_sessione} · {self.argomento[:60]}"


# ─────────────────────────────────────────────────────────────
# REGOLA OBBLIGATORIETÀ (D4)
# ─────────────────────────────────────────────────────────────

class TrainingRequirementRule(models.Model):
    """Regola di obbligatorietà formativa per corso/piano e per target (mansione, area, ruolo, singolo).
    Almeno uno dei target deve essere valorizzato (vincolo verificato a livello form).
    """

    # Oggetto della regola: corso singolo OPPURE intero piano
    corso = models.ForeignKey(
        TrainingCourse, null=True, blank=True,
        on_delete=models.CASCADE, related_name="regole_obbligo",
    )
    piano = models.ForeignKey(
        TrainingPlan, null=True, blank=True,
        on_delete=models.CASCADE, related_name="regole_obbligo",
    )

    # Target della regola (uno o più possono essere valorizzati)
    mansione = models.ForeignKey(
        "anagrafica.Mansione", null=True, blank=True,
        on_delete=models.CASCADE, related_name="regole_formazione",
    )
    area = models.ForeignKey(
        "anagrafica.AreaAziendale", null=True, blank=True,
        on_delete=models.CASCADE, related_name="regole_formazione",
    )
    ruolo_operativo = models.ForeignKey(
        "anagrafica.RuoloOperativo", null=True, blank=True,
        on_delete=models.CASCADE, related_name="regole_formazione",
    )
    legacy_anagrafica_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="Se valorizzato: regola per singolo dipendente",
    )

    is_mandatory            = models.BooleanField(default=True)
    override_frequenza_mesi = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Sovrascrive la frequenza del corso. Null = usa la frequenza del corso.",
    )
    data_inizio_validita = models.DateField(null=True, blank=True)
    data_fine_validita   = models.DateField(null=True, blank=True)
    priority             = models.PositiveSmallIntegerField(default=0, help_text="Priorità relativa della regola")
    note                 = models.TextField(blank=True)
    is_active            = models.BooleanField(default=True)
    created_by           = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Regola di obbligatorietà"
        verbose_name_plural = "Regole di obbligatorietà"
        indexes = [
            models.Index(fields=["mansione", "is_active"]),
            models.Index(fields=["area", "is_active"]),
            models.Index(fields=["ruolo_operativo", "is_active"]),
            models.Index(fields=["legacy_anagrafica_id", "is_active"]),
        ]

    def __str__(self) -> str:
        target = self.corso or self.piano
        return f"Regola obbligo — {target}"


# ─────────────────────────────────────────────────────────────
# AZIENDA FORMATIVA (provider / ente di formazione)
# ─────────────────────────────────────────────────────────────
# I docenti esterni non arrivano mai da soli: arrivano da un ente, e in verifica
# ispettiva la domanda è sull'ente (accreditamento, contatti, chi ha erogato
# cosa). Finora l'ente viveva come testo libero in `ragione_sociale`, quindi
# ogni docente ne riscriveva una variante. Qui diventa un'entità con i suoi
# docenti associati; `ragione_sociale` resta come dato storico dei record già
# inseriti e come ripiego per il docente senza ente.

class TrainingProvider(models.Model):
    """Ente di formazione / azienda formativa a cui appartengono i docenti."""

    nome           = models.CharField(max_length=300, unique=True, verbose_name="Ragione sociale")
    partita_iva    = models.CharField(max_length=20, blank=True, verbose_name="Partita IVA / C.F.")
    email          = models.EmailField(blank=True)
    telefono       = models.CharField(max_length=30, blank=True)
    sito_web       = models.CharField(max_length=200, blank=True)
    indirizzo      = models.CharField(max_length=300, blank=True)
    accreditamento = models.CharField(
        max_length=200, blank=True,
        help_text="Estremi di accreditamento / albo (es. accreditamento regionale, n° iscrizione)",
    )
    note       = models.TextField(blank=True)
    is_active  = models.BooleanField(default=True, verbose_name="Attiva")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Azienda formativa"
        verbose_name_plural = "Aziende formative"

    def __str__(self) -> str:
        return self.nome


# ─────────────────────────────────────────────────────────────
# DOCENTE / FORMATORE (D5)
# ─────────────────────────────────────────────────────────────

class TrainingInstructor(models.Model):
    """Catalogo docenti/formatori interni ed esterni."""

    TIPO_CHOICES = [
        ("INTERNO", "Interno"),
        ("ESTERNO", "Esterno / Provider"),
    ]

    tipo                 = models.CharField(max_length=10, choices=TIPO_CHOICES, default="ESTERNO")
    nome                 = models.CharField(max_length=200)
    azienda              = models.ForeignKey(
        TrainingProvider, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="istruttori",
        verbose_name="Azienda formativa",
        help_text="Ente di formazione di appartenenza (tipicamente per i docenti esterni)",
    )
    ragione_sociale      = models.CharField(
        max_length=300, blank=True,
        help_text="Ragione sociale libera: usata solo se l'azienda formativa non è a catalogo",
    )
    email                = models.EmailField(blank=True)
    telefono             = models.CharField(max_length=30, blank=True)
    legacy_anagrafica_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="Se interno: legacy_anagrafica_id del dipendente",
    )
    qualification_notes = models.TextField(blank=True)
    is_active           = models.BooleanField(default=True)
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Docente / Formatore"
        verbose_name_plural = "Docenti / Formatori"

    @property
    def ente(self) -> str:
        """Ente di appartenenza: l'azienda a catalogo, altrimenti il testo libero."""
        if self.azienda_id:
            return self.azienda.nome
        return self.ragione_sociale or ""

    def __str__(self) -> str:
        return self.nome


# ─────────────────────────────────────────────────────────────
# DOCUMENTI DI ENTE E DOCENTE (qualifica del formatore)
# ─────────────────────────────────────────────────────────────
# In verifica ispettiva l'accreditamento dell'ente e la qualifica del docente
# vanno **mostrati**, non citati: finora vivevano come testo in
# `accreditamento` e `qualification_notes`. Un unico modello per i due
# soggetti — sono la stessa cosa (una carta che prova un titolo) e così la
# view di download, con il suo ACL e il suo audit, resta una sola.


def _training_provider_doc_upload_to(instance, filename: str) -> str:
    if instance.azienda_id:
        owner = f"enti/{instance.azienda_id}"
    else:
        owner = f"docenti/{instance.docente_id or 'tmp'}"
    suffix = Path(filename or "").suffix.lower()[:20] or ".bin"
    stem = Path(filename or "").stem[:80] or "documento"
    now = timezone.now()
    return (
        f"anagrafica/formazione/{owner}/documenti/"
        f"{now.strftime('%Y%m')}/{now.strftime('%Y%m%d_%H%M%S')}_{stem}{suffix}"
    )


class TrainingProviderDocument(models.Model):
    """Documento di un ente di formazione o di un docente.

    Esattamente uno fra ``azienda`` e ``docente`` è valorizzato (vincolo di
    database): il documento appartiene a un soggetto solo. Storage privato
    fuori webroot come gli altri documenti HR; si scarica solo dalla view
    protetta ``anagrafica:formazione_ente_documento_download``.

    ``data_scadenza`` è facoltativa ma è il motivo per cui questi documenti
    stanno nel portale invece che in una cartella: un accreditamento scade, e
    un ente che forma con l'accreditamento scaduto è un rilievo.
    """

    class Tipo(models.TextChoices):
        ACCREDITAMENTO = "ACCREDITAMENTO", "Accreditamento / iscrizione albo"
        CONTRATTO = "CONTRATTO", "Contratto / convenzione"
        CV = "CV", "Curriculum del docente"
        QUALIFICA = "QUALIFICA", "Attestato di qualifica del docente"
        ASSICURAZIONE = "ASSICURAZIONE", "Polizza assicurativa"
        ALTRO = "ALTRO", "Altro"

    azienda = models.ForeignKey(
        TrainingProvider, null=True, blank=True,
        on_delete=models.CASCADE, related_name="documenti",
    )
    docente = models.ForeignKey(
        "anagrafica.TrainingInstructor", null=True, blank=True,
        on_delete=models.CASCADE, related_name="documenti",
    )
    tipo = models.CharField(
        max_length=20, choices=Tipo.choices, default=Tipo.ACCREDITAMENTO, db_index=True,
    )
    file = models.FileField(
        upload_to=_training_provider_doc_upload_to,
        storage=PrivateAnagraficaStorage(),
    )
    nome_originale   = models.CharField(max_length=255, blank=True, default="")
    tipo_mime        = models.CharField(max_length=100, blank=True, default="")
    dimensione_bytes = models.PositiveIntegerField(default=0)
    descrizione      = models.CharField(max_length=300, blank=True, default="")
    data_scadenza    = models.DateField(
        null=True, blank=True,
        help_text="Se il documento scade (accreditamento, polizza, qualifica a termine).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_by_display = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Documento ente/docente"
        verbose_name_plural = "Documenti enti e docenti"
        indexes = [
            models.Index(fields=["azienda", "tipo"]),
            models.Index(fields=["docente", "tipo"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(azienda__isnull=False, docente__isnull=True)
                    | models.Q(azienda__isnull=True, docente__isnull=False)
                ),
                name="training_provider_doc_un_solo_proprietario",
            ),
        ]

    @property
    def stato_scadenza(self) -> str:
        """"", "VALIDO", "IN_SCADENZA" (<=60gg) o "SCADUTO"."""
        if not self.data_scadenza:
            return ""
        giorni = (self.data_scadenza - timezone.localdate()).days
        if giorni < 0:
            return "SCADUTO"
        if giorni <= 60:
            return "IN_SCADENZA"
        return "VALIDO"

    def __str__(self) -> str:
        owner = self.azienda.nome if self.azienda_id else (self.docente.nome if self.docente_id else "—")
        return f"[{self.get_tipo_display()}] {owner}"


# ─────────────────────────────────────────────────────────────
# ASSEGNAZIONE CORSO A DIPENDENTE
# ─────────────────────────────────────────────────────────────

class TrainingAssignment(models.Model):
    """Assegnazione esplicita di un corso a un dipendente da parte di HR.
    Distinto da TrainingEnrollment (iscrizione a una sessione specifica).
    """

    STATO_CHOICES = [
        ("ASSEGNATO",  "Assegnato"),
        ("IN_CORSO",   "In corso"),
        ("COMPLETATO", "Completato"),
        ("SCADUTO",    "Scaduto"),
        ("RIMANDATO",  "Rimandato"),
        ("ESONERATO",  "Esonerato"),
    ]

    corso                = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="assegnazioni")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    piano                = models.ForeignKey(
        TrainingPlan, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assegnazioni",
    )
    requirement_rule = models.ForeignKey(
        TrainingRequirementRule, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assegnazioni",
    )
    stato             = models.CharField(max_length=15, choices=STATO_CHOICES, default="ASSEGNATO")
    data_assegnazione = models.DateField(auto_now_add=True)
    due_date          = models.DateField(null=True, blank=True, help_text="Entro quando completare")
    note              = models.TextField(blank=True)
    assigned_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("corso", "legacy_anagrafica_id")]
        verbose_name = "Assegnazione corso"
        verbose_name_plural = "Assegnazioni corsi"
        indexes = [models.Index(fields=["legacy_anagrafica_id", "stato"])]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.corso.codice} ({self.stato})"


# ─────────────────────────────────────────────────────────────
# SESSIONE FORMATIVA
# ─────────────────────────────────────────────────────────────

class TrainingSession(models.Model):
    """Una sessione (edizione) di un corso: data, luogo, docente."""

    STATO_CHOICES = [
        ("PIANIFICATA", "Pianificata"),
        ("IN_CORSO",    "In corso"),
        ("COMPLETATA",  "Completata"),
        ("ANNULLATA",   "Annullata"),
    ]
    MODALITA_CHOICES = [
        ("IN_SEDE",  "In sede"),
        ("REMOTO",   "Remoto / Online"),
        ("ESTERNO",  "Esterno (provider)"),
        ("MISTO",    "Misto"),
    ]

    corso           = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="sessioni")
    codice_sessione = models.CharField(max_length=40, unique=True)
    stato           = models.CharField(max_length=15, choices=STATO_CHOICES, default="PIANIFICATA")
    modalita        = models.CharField(max_length=10, choices=MODALITA_CHOICES, default="IN_SEDE")
    data_inizio     = models.DateField()
    data_fine       = models.DateField()
    sede            = models.CharField(max_length=200, blank=True, help_text="Aula, indirizzo o link remoto")
    edizione        = models.CharField(
        max_length=80, blank=True, default="", db_index=True,
        help_text="Etichetta libera che collega più sessioni della stessa erogazione del corso: "
                  "un corso diviso in più gruppi per motivi logistici (stesso programma, iscritti "
                  "diversi), o lo stesso corso ripetuto nel tempo. Vuota = sessione autonoma, "
                  "non collegata ad altre. Vedi services.formazione_pianificazione.dividi_in_gruppi.",
    )
    docente         = models.ForeignKey(
        TrainingInstructor, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sessioni",
    )
    docente_nome    = models.CharField(max_length=200, blank=True, help_text="Snapshot nome docente per stabilità storica")
    note            = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    created_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-data_inizio"]
        verbose_name = "Sessione formativa"
        verbose_name_plural = "Sessioni formative"
        indexes = [
            models.Index(fields=["corso", "stato"]),
            models.Index(fields=["data_inizio", "data_fine"]),
            models.Index(fields=["corso", "edizione"]),
        ]

    @property
    def ore_pianificate(self) -> float:
        """Monte ore formative della sessione = somma delle durate nette delle lezioni."""
        return round(sum(lz.durata_ore for lz in self.lezioni.all()), 2)

    def sessioni_gemelle(self):
        """Le altre sessioni della stessa ``edizione`` (stesso corso), sé esclusa.

        Vuoto se la sessione non appartiene a un'edizione, o se è l'unico gruppo.
        Ordinate per data così l'ordinale "Gruppo N" mostrato in UI è stabile.
        """
        if not self.edizione:
            return TrainingSession.objects.none()
        return (
            TrainingSession.objects.filter(corso_id=self.corso_id, edizione=self.edizione)
            .exclude(pk=self.pk)
            .order_by("data_inizio", "id")
        )

    def __str__(self) -> str:
        return f"[{self.codice_sessione}] {self.corso.titolo} — {self.data_inizio}"


# ─────────────────────────────────────────────────────────────
# LEZIONE
# ─────────────────────────────────────────────────────────────

class TrainingLesson(models.Model):
    """Singola lezione di una sessione."""

    sessione     = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name="lezioni")
    numero       = models.PositiveSmallIntegerField(default=1)
    data         = models.DateField()
    ora_inizio   = models.TimeField()
    ora_fine     = models.TimeField()
    pausa_minuti = models.PositiveSmallIntegerField(
        default=0,
        help_text="Minuti di interruzione non formativa (pausa pranzo, intervalli) da scalare "
                  "dalla durata. Es. 08:00–17:00 con 60' di pausa = 8 ore formative.",
    )
    argomento    = models.CharField(max_length=500)
    # Quali voci del programma dell'edizione sono state coperte in questa
    # giornata: è il collegamento che permette di confrontare previsto ed
    # erogato, cioè la domanda che segue subito «cosa insegna il corso».
    argomenti_svolti = models.ManyToManyField(
        TrainingSessionArgomento, blank=True, related_name="lezioni",
        verbose_name="Argomenti del programma svolti",
    )
    docente      = models.ForeignKey(
        TrainingInstructor, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lezioni",
    )
    docente_nome = models.CharField(max_length=200, blank=True, help_text="Snapshot nome docente per stabilità storica")
    note         = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["data", "ora_inizio"]
        unique_together = [("sessione", "numero")]
        verbose_name = "Lezione"
        verbose_name_plural = "Lezioni"

    @property
    def durata_ore_lorde(self) -> float:
        """Ore dalla presenza in aula (ora_fine - ora_inizio), pausa inclusa."""
        from datetime import datetime, date as _date
        dt_inizio = datetime.combine(_date.today(), self.ora_inizio)
        dt_fine   = datetime.combine(_date.today(), self.ora_fine)
        return round((dt_fine - dt_inizio).total_seconds() / 3600, 2)

    @property
    def durata_ore(self) -> float:
        """Ore **formative** della lezione: durata in aula meno la pausa.

        È il valore usato ovunque (monte ore sessione, percentuale di presenza,
        registro, attestato): una giornata 08:00–17:00 con 60' di pausa pranzo
        vale 8 ore, non 9. Non scende mai sotto zero.
        """
        return round(max(0.0, self.durata_ore_lorde - (self.pausa_minuti or 0) / 60), 2)

    def __str__(self) -> str:
        return f"Lezione {self.numero} — {self.sessione.codice_sessione} — {self.data}"


# ─────────────────────────────────────────────────────────────
# ISCRIZIONE (Enrollment)
# ─────────────────────────────────────────────────────────────

class TrainingEnrollment(models.Model):
    """Iscrizione di un dipendente a una sessione formativa."""

    STATO_CHOICES = [
        ("ISCRITTO",   "Iscritto"),
        ("IN_CORSO",   "In corso"),
        ("COMPLETATO", "Completato"),
        ("NON_IDONEO", "Non idoneo"),
        ("ASSENTE",    "Assente"),
        ("RITIRATO",   "Ritirato"),
    ]

    MODALITA_VERIFICA_CHOICES = [
        ("TEST",         "Test scritto"),
        ("ORALE",        "Colloquio orale"),
        ("PRATICA",      "Prova pratica"),
        ("OSSERVAZIONE", "Osservazione sul campo"),
    ]

    sessione             = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name="iscrizioni")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    assignment           = models.ForeignKey(
        TrainingAssignment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="iscrizioni",
    )
    stato                = models.CharField(max_length=15, choices=STATO_CHOICES, default="ISCRITTO")
    ore_frequentate      = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    percentuale_presenza = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    idoneo               = models.BooleanField(null=True, blank=True)
    esito_esame          = models.CharField(max_length=100, blank=True)
    # Verifica finale di apprendimento (Accordo Stato-Regioni 2025): obbligatoria per i
    # corsi la cui regola di superamento ha richiede_esame_finale=True. Null = non registrata.
    verifica_superata    = models.BooleanField(null=True, blank=True)
    data_verifica        = models.DateField(null=True, blank=True)
    # Evidenza della verifica (catena dell'evidenza, anello 7). Prima c'era solo
    # il segno di spunta: per l'e-learning il quiz conserva punteggio e risposte,
    # per l'aula non restava nulla. Un flag non dimostra un apprendimento.
    modalita_verifica    = models.CharField(
        max_length=12, choices=MODALITA_VERIFICA_CHOICES, blank=True, default="",
        help_text="Come è stato verificato l'apprendimento.",
    )
    punteggio            = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Punteggio conseguito, in percentuale.",
    )
    punteggio_minimo     = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Soglia applicata a questa verifica. Serve a rileggere l'esito "
                  "anni dopo con il criterio di allora, non con quello di oggi.",
    )
    data_completamento   = models.DateField(null=True, blank=True)
    note                 = models.TextField(blank=True)
    iscritto_da          = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("sessione", "legacy_anagrafica_id")]
        verbose_name = "Iscrizione"
        verbose_name_plural = "Iscrizioni"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "stato"]),
            models.Index(fields=["legacy_anagrafica_id", "data_completamento"]),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] → {self.sessione.codice_sessione} ({self.stato})"


# ─────────────────────────────────────────────────────────────
# ASSEGNAZIONE TURNO (iscritto × lezione)
# ─────────────────────────────────────────────────────────────

class TrainingEnrollmentLesson(models.Model):
    """Assegnazione di un iscritto a una specifica lezione/turno della sua sessione.

    Una sessione può erogare lo stesso contenuto in più lezioni-turno (es. mattina
    e pomeriggio, per la gestione dei turni di lavoro): questo modello dice **a quale
    turno** partecipa ciascun iscritto. Le presenze restano a livello di
    :class:`TrainingLessonAttendance`.

    **Backward-compatible**: se per un'iscrizione non esiste alcuna riga, l'iscritto è
    considerato assegnato a *tutte* le lezioni della sessione (comportamento storico,
    nessun dato pregresso da migrare). Invariante applicativa (non vincolata a DB):
    ``lezione.sessione_id == enrollment.sessione_id``.
    """

    enrollment = models.ForeignKey(
        TrainingEnrollment, on_delete=models.CASCADE, related_name="turni",
    )
    lezione = models.ForeignKey(
        TrainingLesson, on_delete=models.CASCADE, related_name="assegnazioni",
    )
    assegnato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("enrollment", "lezione")]
        verbose_name = "Assegnazione turno"
        verbose_name_plural = "Assegnazioni turni"
        indexes = [models.Index(fields=["lezione"])]

    def __str__(self) -> str:
        return f"iscr.{self.enrollment_id} → lez.{self.lezione_id}"


# ─────────────────────────────────────────────────────────────
# PRESENZE LEZIONE
# ─────────────────────────────────────────────────────────────

class TrainingLessonAttendance(models.Model):
    """Presenza di un dipendente a una singola lezione."""

    STATO_PRESENZA_CHOICES = [
        ("PRESENTE",        "Presente"),
        ("ASSENTE_GIUST",   "Assente giustificato"),
        ("ASSENTE_INGIUST", "Assente ingiustificato"),
        ("PARZIALE",        "Presenza parziale"),
    ]

    SIGNATURE_STATUS_CHOICES = [
        ("NESSUNA",  "Nessuna firma"),
        ("PENDENTE", "Firma pendente"),
        ("FIRMATO",  "Firmato"),
        ("RIFIUTATO","Rifiutato"),
    ]

    SIGNATURE_METHOD_CHOICES = [
        ("CARTACEO", "Foglio cartaceo"),
        ("DIGITALE", "Firma digitale"),
        ("UPLOAD",   "Upload scan"),
    ]

    lezione              = models.ForeignKey(TrainingLesson, on_delete=models.CASCADE, related_name="presenze")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    enrollment           = models.ForeignKey(
        TrainingEnrollment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="presenze_lezione",
    )
    stato_presenza   = models.CharField(max_length=15, choices=STATO_PRESENZA_CHOICES, default="PRESENTE")
    ore_effettive    = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    firma_ingresso   = models.BooleanField(default=False)
    firma_uscita     = models.BooleanField(default=False)
    signature_status = models.CharField(max_length=10, choices=SIGNATURE_STATUS_CHOICES, default="NESSUNA")
    signature_method = models.CharField(max_length=10, choices=SIGNATURE_METHOD_CHOICES, blank=True)
    signed_at        = models.DateTimeField(null=True, blank=True)
    signature_file   = models.ForeignKey(
        "anagrafica.DocumentoDipendente", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="firme_presenze_formazione",
    )
    uploaded_signed_register = models.ForeignKey(
        "anagrafica.DocumentoDipendente", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="registri_firma_formazione",
    )
    note         = models.TextField(blank=True)
    registrato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("lezione", "legacy_anagrafica_id")]
        verbose_name = "Presenza lezione"
        verbose_name_plural = "Presenze lezioni"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "lezione"]),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] — {self.lezione} — {self.stato_presenza}"


# ─────────────────────────────────────────────────────────────
# RECORD COMPLETAMENTO (storico dipendente × corso)
# ─────────────────────────────────────────────────────────────

class TrainingEmployeeRecord(models.Model):
    """Record storico di completamento corso per dipendente.

    I campi snapshot_ garantiscono integrità storica anche se corso/sessione/piano
    cambiano in seguito. Compilare alla creazione; non aggiornare mai i snapshot.
    """

    corso    = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="record_completamenti")
    sessione = models.ForeignKey(
        TrainingSession, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="record_completamenti",
    )
    enrollment = models.OneToOneField(
        TrainingEnrollment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="record_completamento",
    )
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    data_completamento   = models.DateField()
    ore_frequentate      = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    percentuale_presenza = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    idoneo               = models.BooleanField(default=True)
    data_scadenza        = models.DateField(
        null=True, blank=True,
        help_text="Null se corso una tantum (validita_mesi=0)",
    )
    validato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    validato_il = models.DateField(null=True, blank=True)
    note        = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    # Numero di protocollo dell'attestato (progressivo per anno, es. ATT-2026-0001).
    # Assegnato in modo lazy alla prima emissione/archiviazione dell'attestato e poi
    # stabile (vedi services.attestato_pdf.assegna_numero_protocollo). Vuoto = non
    # ancora emesso.
    numero_protocollo = models.CharField(max_length=20, blank=True, default="", db_index=True)

    # ── Snapshot storici ─────────────────────────────────────
    # Compilare alla creazione del record — non aggiornare mai.
    course_code_snapshot               = models.CharField(max_length=30, blank=True)
    course_title_snapshot              = models.CharField(max_length=300, blank=True)
    course_version_snapshot            = models.CharField(max_length=10, blank=True)
    plan_code_snapshot                 = models.CharField(max_length=20, blank=True)
    plan_name_snapshot                 = models.CharField(max_length=200, blank=True)
    duration_hours_snapshot            = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    validity_months_snapshot           = models.PositiveSmallIntegerField(null=True, blank=True)
    completion_rule_snapshot_json      = models.JSONField(default=dict, blank=True)
    session_code_snapshot              = models.CharField(max_length=40, blank=True)
    teacher_name_snapshot              = models.CharField(max_length=200, blank=True)
    completion_calculation_snapshot_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-data_completamento"]
        verbose_name = "Record completamento"
        verbose_name_plural = "Record completamenti"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "corso"]),
            models.Index(fields=["legacy_anagrafica_id", "data_scadenza"]),
            models.Index(fields=["data_scadenza"]),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.corso.codice} — {self.data_completamento}"


# ─────────────────────────────────────────────────────────────
# FOGLIO FIRME EMESSO (catena dell'evidenza, anello 6)
# ─────────────────────────────────────────────────────────────
# Il registro cartaceo resta l'unico documento che un ispettore accetta senza
# discutere. L'idea è farlo diventare anche il modo di compilare il portale,
# invece di essere una seconda cosa da fare dopo.
#
# Perché serve un record e non basta ristampare al volo: al momento della
# stampa l'elenco viene CONGELATO. Se dopo si aggiunge un iscritto, l'ordine
# delle righe cambierebbe e la riga 7 del foglio scansionato non sarebbe più la
# stessa persona della riga 7 ricalcolata. Il foglio emesso è un fatto storico.
#
# La geometria delle celle firma viene registrata alla generazione: rende il
# riconoscimento della scansione una misura su rettangoli di posizione nota,
# invece di un problema di lettura della scrittura.

class TrainingSignatureSheet(models.Model):
    """Foglio firme emesso per una giornata: elenco congelato + geometria."""

    STATO_CHOICES = [
        ("EMESSO",    "Emesso"),
        ("ACQUISITO", "Scansione acquisita"),
        ("ANNULLATO", "Annullato"),
    ]

    lezione    = models.ForeignKey(
        "anagrafica.TrainingLesson", on_delete=models.CASCADE, related_name="fogli_firme",
    )
    token      = models.CharField(
        max_length=16, unique=True, db_index=True,
        help_text="Identificativo stampato nel QR: riaggancia la scansione alla giornata "
                  "senza che nessuno debba sceglierla a mano.",
    )
    stato      = models.CharField(max_length=10, choices=STATO_CHOICES, default="EMESSO")
    righe      = models.JSONField(
        default=list, blank=True,
        help_text="Elenco congelato alla stampa: [{n, legacy_id, nome}]. È ciò che "
                  "rende la riga 7 della scansione la stessa persona di allora.",
    )
    geometria  = models.JSONField(
        default=dict, blank=True,
        help_text="Posizione in mm delle celle firma sulla pagina, dall'angolo in alto "
                  "a sinistra. Serve a leggere la scansione senza interpretare la scrittura.",
    )
    emesso_il  = models.DateTimeField(auto_now_add=True)
    emesso_da  = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    scansione  = models.ForeignKey(
        "anagrafica.TrainingAttachment", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="fogli_firme",
    )
    acquisito_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-emesso_il", "-id"]
        verbose_name = "Foglio firme emesso"
        verbose_name_plural = "Fogli firme emessi"
        indexes = [models.Index(fields=["lezione", "stato"])]

    def __str__(self) -> str:
        return f"Foglio {self.token} — lezione {self.lezione_id}"

    @property
    def n_righe(self) -> int:
        return len(self.righe or [])


class TrainingScanLog(models.Model):
    """Registro delle scansioni caricate: cosa è arrivato, dov'è finito, com'è andata.

    Nasce dal caso che conta davvero, cioè quando la lettura **fallisce**. Senza
    registro, il file caricato spariva e restava solo un messaggio d'errore a
    schermo: nessun modo di guardare cosa fosse arrivato davvero, e la persona
    che aveva scansionato doveva rifare tutto per farlo vedere a qualcuno.

    Perciò il file viene archiviato *sempre*, riuscita o fallita che sia la
    lettura, e qui resta scritto il percorso. Su un esito riuscito serve a
    confrontare la proposta con l'originale; su un errore è l'unica cosa che
    permetta di capire perché.

    Non sostituisce l'allegato «registro firmato» della giornata: quello è la
    prova documentale scelta da una persona, questo è la traccia tecnica di
    cosa ha masticato il portale.
    """

    ESITO_CHOICES = [
        ("OK",       "Letto"),
        ("ERRORE",   "Errore di lettura"),
        ("RIFIUTATO", "Foglio non riconosciuto"),
    ]
    ORIGINE_CHOICES = [
        ("WEB",      "Caricamento dalla pagina"),
        ("CARTELLA", "Cartella di acquisizione"),
    ]

    lezione = models.ForeignKey(
        "anagrafica.TrainingLesson", null=True, blank=True,
        on_delete=models.CASCADE, related_name="scansioni_log",
        help_text="Vuoto quando il foglio non è stato riconosciuto: il file resta "
                  "comunque archiviato e ispezionabile.",
    )
    foglio = models.ForeignKey(
        "anagrafica.TrainingSignatureSheet", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="letture",
    )

    nome_file = models.CharField(max_length=255, blank=True, default="")
    percorso  = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Dove è stato archiviato il file caricato, relativo allo storage "
                  "privato dell'anagrafica.",
    )
    dimensione = models.PositiveIntegerField(default=0, help_text="Byte del file caricato.")

    token_digitato = models.CharField(max_length=16, blank=True, default="")
    token_letto    = models.CharField(
        max_length=16, blank=True, default="",
        help_text="Token decodificato dal QR. Vuoto se il codice non è stato letto "
                  "e l'operatore ha digitato a mano.",
    )

    esito     = models.CharField(max_length=10, choices=ESITO_CHOICES, default="OK")
    origine   = models.CharField(max_length=10, choices=ORIGINE_CHOICES, default="WEB")
    messaggio = models.TextField(
        blank=True, default="",
        help_text="Motivo dell'errore, nelle stesse parole mostrate a chi ha caricato.",
    )

    n_righe   = models.PositiveIntegerField(default=0)
    n_firmati = models.PositiveIntegerField(default=0)
    n_dubbie  = models.PositiveIntegerField(default=0)
    inclinazione = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Gradi di rotazione rilevati nella scansione.",
    )

    creato_il = models.DateTimeField(auto_now_add=True, db_index=True)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-creato_il", "-id"]
        verbose_name = "Lettura di scansione"
        verbose_name_plural = "Registro letture scansioni"
        indexes = [
            models.Index(fields=["esito", "-creato_il"]),
            models.Index(fields=["lezione", "-creato_il"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_esito_display()} — {self.nome_file or 'senza nome'} ({self.creato_il:%d-%m-%Y %H:%M})"

    presenze_scritte = models.PositiveIntegerField(
        default=0,
        help_text="Presenze registrate automaticamente da questa lettura. Zero quando "
                  "la conferma è rimasta a una persona, che è il comportamento normale.",
    )

    @property
    def riuscita(self) -> bool:
        return self.esito == "OK"

    @property
    def dimensione_leggibile(self) -> str:
        n = self.dimensione or 0
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.0f} KB"
        return f"{n / (1024 * 1024):.1f} MB"


class TrainingScanIntakeConfig(models.Model):
    """Singleton — cartella di acquisizione delle scansioni e regole di conferma.

    Il gesto che questa configurazione elimina è banale e per questo pesante:
    aprire il portale, cercare la giornata, caricare il file. Con una cartella
    di rete la fotocopiatrice ci scrive dentro da sola e il portale se lo
    prende — chi ha fatto il corso non tocca un computer.

    La conferma resta **umana per default**, e non per prudenza formale: la
    presenza a un corso è un atto con valore legale, e una misura di pixel non
    è una firma. L'automatismo si accende consapevolmente da qui, e anche
    acceso si ferma davanti alle celle dubbie — quelle dove il segno è troppo
    debole per decidere — perché è esattamente lì che serve un occhio.

    Pattern identico ad :class:`AttestatoFormazioneConfig`: una sola riga (pk=1).
    """

    CARTELLA_DEFAULT = r"\\pclogsys\PortaleNovicrom\scansioni\formazione"

    attiva = models.BooleanField(
        default=False,
        help_text="Se spenta, il lavoro periodico non guarda la cartella. La lettura "
                  "dalla pagina continua a funzionare comunque.",
    )
    cartella = models.CharField(
        max_length=500, blank=True, default=CARTELLA_DEFAULT,
        help_text="Percorso UNC della cartella dove la fotocopiatrice deposita le "
                  "scansioni. Deve essere raggiungibile dall'utente con cui gira "
                  "l'applicazione: una lettera di unità mappata non è visibile a un servizio.",
    )
    sposta_elaborati = models.BooleanField(
        default=True,
        help_text="Sposta i file letti in «elaborati» e quelli non riusciti in «errori», "
                  "così la cartella di ingresso resta pulita e nulla viene riletto due volte.",
    )
    max_file_per_giro = models.PositiveIntegerField(
        default=25,
        help_text="Quanti file al massimo elaborare a ogni passaggio: un arretrato "
                  "enorme non deve bloccare il lavoro periodico.",
    )

    conferma_automatica = models.BooleanField(
        default=False,
        help_text="Se accesa, una lettura pulita registra le presenze da sé senza "
                  "attendere conferma. Da valutare con attenzione: la presenza a un "
                  "corso è un atto con valore legale.",
    )
    auto_solo_senza_dubbie = models.BooleanField(
        default=True,
        help_text="Con la conferma automatica accesa, ferma comunque i fogli che hanno "
                  "celle dubbie. Toglierla significa accettare che un segno incerto "
                  "diventi una presenza senza che nessuno l'abbia guardato.",
    )
    auto_solo_se_tutti_firmati = models.BooleanField(
        default=False,
        help_text="Registra da sé solo se ogni iscritto atteso risulta firmato. Utile "
                  "per accorgersi dei fogli letti a metà.",
    )

    ultima_esecuzione = models.DateTimeField(null=True, blank=True)
    ultimo_esito = models.TextField(
        blank=True, default="",
        help_text="Riepilogo dell'ultimo passaggio, per capire dalla pagina se il "
                  "meccanismo sta girando davvero.",
    )

    class Meta:
        verbose_name = "Acquisizione scansioni da cartella"
        verbose_name_plural = "Acquisizione scansioni da cartella"

    def __str__(self) -> str:
        return "Acquisizione scansioni" + ("" if self.attiva else " (spenta)")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ─────────────────────────────────────────────────────────────
# VALUTAZIONE DI EFFICACIA (catena dell'evidenza, anello 8)
# ─────────────────────────────────────────────────────────────
# Il modulo sapeva raccontare benissimo *che* la formazione era stata erogata.
# Non diceva nulla su *cosa avesse prodotto*. È la differenza fra «abbiamo fatto
# il corso» e «le persone sono competenti», ed è ciò che ISO 45001 §7.2 e
# ISO 9001 §7.2 chiedono per nome.
#
# È una FK e non un uno-a-uno di proposito: dopo un esito «non efficace» si
# concorda un'azione e si rivaluta. Le due valutazioni sono entrambe storia.

class TrainingEfficacia(models.Model):
    """Verifica sul campo, a distanza di mesi, che la formazione abbia prodotto
    competenza. Nasce «attesa» al completamento e viene compilata dal preposto."""

    ESITO_CHOICES = [
        ("EFFICACE",     "Efficace"),
        ("PARZIALE",     "Parzialmente efficace"),
        ("NON_EFFICACE", "Non efficace"),
    ]

    record       = models.ForeignKey(
        "anagrafica.TrainingEmployeeRecord", on_delete=models.CASCADE,
        related_name="valutazioni_efficacia",
    )
    # Denormalizzato dal record: la valutazione si cerca per persona, e la
    # ricerca deve restare diretta anche quando il record verrà archiviato.
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    attesa_dal   = models.DateField(
        db_index=True,
        help_text="Data dalla quale la valutazione è dovuta (completamento + mesi previsti).",
    )
    valutata_il  = models.DateField(null=True, blank=True)
    valutata_da  = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    valutatore_nome = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Snapshot di chi ha valutato: resta leggibile anche se l'utenza sparisce.",
    )
    esito        = models.CharField(max_length=14, choices=ESITO_CHOICES, blank=True, default="")
    azione       = models.TextField(
        blank=True,
        help_text="Cosa si è deciso di fare quando l'esito non è pieno: affiancamento, "
                  "ripetizione, cambio mansione.",
    )
    note         = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["attesa_dal", "id"]
        verbose_name = "Valutazione di efficacia"
        verbose_name_plural = "Valutazioni di efficacia"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "attesa_dal"]),
            models.Index(fields=["esito"]),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] efficacia attesa dal {self.attesa_dal}"

    @property
    def in_attesa(self) -> bool:
        return not self.valutata_il

    @property
    def scaduta(self) -> bool:
        """Dovuta e non ancora compilata: è la riga che deve comparire nei solleciti."""
        from django.utils import timezone as _tz

        return self.in_attesa and self.attesa_dal <= _tz.localdate()


# ─────────────────────────────────────────────────────────────
# ATTESTATO / CERTIFICATO
# ─────────────────────────────────────────────────────────────

class TrainingCertificate(models.Model):
    """Attestato di completamento, collegato a un record completamento."""

    record               = models.OneToOneField(TrainingEmployeeRecord, on_delete=models.CASCADE, related_name="attestato")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    numero_attestato     = models.CharField(max_length=100, blank=True)
    data_rilascio        = models.DateField()
    rilasciato_da        = models.CharField(max_length=200, blank=True)
    file_attestato       = models.ForeignKey(
        "anagrafica.DocumentoDipendente", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="certificati_formazione",
    )
    note       = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = "Attestato formazione"
        verbose_name_plural = "Attestati formazione"
        indexes = [models.Index(fields=["legacy_anagrafica_id"])]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] Attestato — {self.data_rilascio}"


# ─────────────────────────────────────────────────────────────
# SCADENZARIO FORMAZIONE (cache ricalcolabile — D9)
# ─────────────────────────────────────────────────────────────

class TrainingDeadline(models.Model):
    """Cache calcolata delle scadenze formazione per dipendente × corso.

    NON modificare manualmente — è un dato derivato.
    Il ricalcolo avviene tramite management command `refresh_training_deadlines`
    o il service `training_deadline_service.refresh_deadlines()`.
    I signal su TrainingEmployeeRecord settano solo `needs_refresh=True`.
    """

    STATO_SCADENZA_CHOICES = [
        ("VALIDO",          "Valido"),
        ("IN_SCADENZA_30",  "In scadenza ≤30gg"),
        ("IN_SCADENZA_90",  "In scadenza ≤90gg"),
        ("SCADUTO",         "Scaduto"),
        ("MAI_FREQUENTATO", "Mai frequentato"),
        ("UNA_TANTUM",      "Completato (una tantum)"),
    ]

    corso                = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="scadenze")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    requirement_rule     = models.ForeignKey(
        TrainingRequirementRule, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="scadenze",
    )
    assignment = models.ForeignKey(
        TrainingAssignment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="scadenza",
    )
    ultimo_completamento = models.ForeignKey(
        TrainingEmployeeRecord, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    data_ultimo_completamento = models.DateField(null=True, blank=True)
    data_scadenza             = models.DateField(null=True, blank=True, db_index=True)
    stato_scadenza            = models.CharField(
        max_length=20, choices=STATO_SCADENZA_CHOICES, default="MAI_FREQUENTATO",
    )
    giorni_alla_scadenza      = models.IntegerField(null=True, blank=True)
    is_required               = models.BooleanField(default=False)
    reason_snapshot           = models.JSONField(default=dict, blank=True)
    last_recalculation_source = models.CharField(max_length=100, blank=True)
    needs_refresh             = models.BooleanField(default=False, db_index=True)
    ricalcolato_il            = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("corso", "legacy_anagrafica_id")]
        verbose_name = "Scadenza formazione"
        verbose_name_plural = "Scadenze formazione"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "stato_scadenza"]),
            models.Index(fields=["data_scadenza"]),
            models.Index(fields=["stato_scadenza"]),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.corso.codice} — {self.stato_scadenza}"


# ─────────────────────────────────────────────────────────────
# LOG EXPORT
# ─────────────────────────────────────────────────────────────

class TrainingExportLog(models.Model):
    """Audit trail degli export Excel/PDF generati dalla sezione formazione."""

    TIPO_EXPORT_CHOICES = [
        ("PIANI",        "Elenco piani formativi"),
        ("CORSI",        "Elenco corsi"),
        ("ISCRITTI",     "Iscritti sessione"),
        ("PRESENZE",     "Presenze lezione"),
        ("STORICO_DIP",  "Storico dipendente"),
        ("SCADENZARIO",  "Scadenzario formazione"),
        ("MATRICE",      "Matrice dipendente × corso"),
        ("KPI",          "Report KPI direzionale"),
        ("REPORT_FIRMA", "Report firma lezione PDF"),
        ("ATTESTATO",    "Attestato di completamento"),
    ]

    tipo            = models.CharField(max_length=20, choices=TIPO_EXPORT_CHOICES)
    filtri_json     = models.JSONField(default=dict, blank=True)
    righe_esportate = models.PositiveIntegerField(default=0)
    generato_da     = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    generato_il = models.DateTimeField(auto_now_add=True)
    ip_address  = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-generato_il"]
        verbose_name = "Log export formazione"
        verbose_name_plural = "Log export formazione"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.generato_il}"


# ─────────────────────────────────────────────────────────────
# ALLEGATO SESSIONE / LEZIONE (registro firme firmato, materiale)
# ─────────────────────────────────────────────────────────────

def _training_attachment_upload_to(instance, filename: str) -> str:
    sess_id = instance.sessione_id or "tmp"
    livello = f"lez{instance.lezione_id}" if instance.lezione_id else "sessione"
    suffix = Path(filename or "").suffix.lower()[:20] or ".bin"
    stem = Path(filename or "").stem[:80] or "registro"
    now = timezone.now()
    return (
        f"anagrafica/formazione/sessioni/{sess_id}/allegati/"
        f"{now.strftime('%Y%m')}/{now.strftime('%Y%m%d_%H%M%S')}_{livello}_{stem}{suffix}"
    )


class TrainingAttachment(models.Model):
    """Allegato di una sessione o di una singola lezione.

    Uso principale: ricaricare il **registro firme firmato** (scansione del
    foglio presenze raccolto in aula) a livello di lezione (``lezione`` valorizzato)
    oppure dell'intera sessione (``lezione=None``). Storage privato fuori webroot
    (:class:`PrivateAnagraficaStorage`), scaricabile solo dalla view protetta
    ``anagrafica:formazione_allegato_download`` con ACL formazione + audit.

    Il foglio firme contiene dati personali (nominativi + firme): conservarlo come
    gli altri documenti HR, non esporlo su URL pubblico.
    """

    class Tipo(models.TextChoices):
        REGISTRO_FIRMATO = "REGISTRO_FIRMATO", "Registro firme firmato"
        MATERIALE = "MATERIALE", "Materiale didattico"
        ALTRO = "ALTRO", "Altro"

    sessione = models.ForeignKey(
        TrainingSession, on_delete=models.CASCADE, related_name="allegati",
    )
    lezione = models.ForeignKey(
        TrainingLesson, null=True, blank=True,
        on_delete=models.CASCADE, related_name="allegati",
        help_text="Lezione di riferimento. Vuoto = allegato a livello di sessione.",
    )
    tipo = models.CharField(
        max_length=20, choices=Tipo.choices, default=Tipo.REGISTRO_FIRMATO, db_index=True,
    )
    file = models.FileField(
        upload_to=_training_attachment_upload_to,
        storage=PrivateAnagraficaStorage(),
    )
    nome_originale   = models.CharField(max_length=255, blank=True, default="")
    tipo_mime        = models.CharField(max_length=100, blank=True, default="")
    dimensione_bytes = models.PositiveIntegerField(default=0)
    descrizione      = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_by_display = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Allegato formazione"
        verbose_name_plural = "Allegati formazione"
        indexes = [
            models.Index(fields=["sessione", "lezione"]),
            models.Index(fields=["tipo"]),
        ]

    def __str__(self) -> str:
        liv = f"lezione {self.lezione.numero}" if self.lezione_id else "sessione"
        return f"[{self.get_tipo_display()}] {self.sessione.codice_sessione} — {liv}"


# ═════════════════════════════════════════════════════════════
# E-LEARNING — MICRO-CORSI INTERNI (slide sequenziali + quiz finale)
# ═════════════════════════════════════════════════════════════
# Modalità self-service, layer sopra TrainingCourse (corso con is_elearning=True).
# Niente sessione/aula/presenze: le slide e le domande sono DATI, create da un
# autore (anche non tecnico) dall'admin o dalla UI. Il completamento conforme
# viene storicizzato su TrainingEmployeeRecord (audit qualità), riusando la
# tabella già esistente invece di duplicarla.


def _training_slide_upload_to(instance, filename: str) -> str:
    corso_id = instance.corso_id or "tmp"
    suffix = Path(filename or "").suffix.lower()[:8] or ".png"
    now = timezone.now()
    return (
        f"anagrafica/formazione/corsi/{corso_id}/slides/"
        f"{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond}{suffix}"
    )


class TrainingSlide(models.Model):
    """Slide di un micro-corso e-learning.

    Le slide sono **dati** (non template hardcoded): un autore non tecnico le crea
    e le ordina. Due tipi:
    - **testo**: contenuto in Markdown reso lato server (``services.elearning_markdown``);
    - **immagine**: una pagina importata da PowerPoint/PDF (``services.elearning_import``)
      servita inline dalla view protetta ``formazione_slide_image``.
    Se ``immagine`` è valorizzata la slide è di tipo immagine; ``titolo`` resta come
    didascalia/etichetta di navigazione."""

    corso      = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="slides")
    ordine     = models.PositiveSmallIntegerField(default=1, help_text="Posizione nella sequenza (1 = prima slide).")
    titolo     = models.CharField(max_length=300)
    contenuto  = models.TextField(blank=True, help_text="Contenuto in Markdown, reso lato server.")
    immagine   = models.ImageField(
        upload_to=_training_slide_upload_to, storage=PrivateAnagraficaStorage(),
        null=True, blank=True,
        help_text="Slide-immagine (pagina importata da PPTX/PDF). Se valorizzata sostituisce il contenuto Markdown.",
    )
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        # Niente unique_together su (corso, ordine): semplifica il riordino e evita
        # i vincoli di indice univoco filtrato su SQL Server.
        ordering = ["corso", "ordine", "id"]
        verbose_name = "Slide e-learning"
        verbose_name_plural = "Slide e-learning"
        indexes = [models.Index(fields=["corso", "ordine"])]

    @property
    def is_immagine(self) -> bool:
        return bool(self.immagine)

    def __str__(self) -> str:
        return f"{self.corso.codice} · slide {self.ordine}: {self.titolo}"


class TrainingQuizQuestion(models.Model):
    """Domanda del quiz finale di un micro-corso e-learning."""

    corso      = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="quiz_domande")
    ordine     = models.PositiveSmallIntegerField(default=1)
    testo      = models.TextField()
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["corso", "ordine", "id"]
        verbose_name = "Domanda quiz"
        verbose_name_plural = "Domande quiz"
        indexes = [models.Index(fields=["corso", "ordine"])]

    def __str__(self) -> str:
        return f"{self.corso.codice} · domanda {self.ordine}"


class TrainingQuizOption(models.Model):
    """Opzione di risposta di una domanda del quiz (almeno una corretta per domanda)."""

    domanda  = models.ForeignKey(TrainingQuizQuestion, on_delete=models.CASCADE, related_name="opzioni")
    ordine   = models.PositiveSmallIntegerField(default=1)
    testo    = models.CharField(max_length=500)
    corretta = models.BooleanField(default=False)

    class Meta:
        ordering = ["domanda", "ordine", "id"]
        verbose_name = "Opzione quiz"
        verbose_name_plural = "Opzioni quiz"
        indexes = [models.Index(fields=["domanda"])]

    def __str__(self) -> str:
        return f"{self.testo[:40]}{' ✓' if self.corretta else ''}"


class TrainingElearningEnrollment(models.Model):
    """Iscrizione di un dipendente a un micro-corso e-learning (self-service).

    Distinta da :class:`TrainingEnrollment` (iscrizione a una *sessione d'aula*).
    Traccia l'avanzamento sulle slide e il miglior esito del quiz. Il completamento
    storicizzato per l'audit resta su :class:`TrainingEmployeeRecord`.

    Identità discente = ``legacy_anagrafica_id`` (convenzione del modulo formazione)."""

    STATO_CHOICES = [
        ("ISCRITTO",     "Iscritto"),
        ("IN_CORSO",     "In corso"),
        ("COMPLETATO",   "Completato"),
        ("NON_SUPERATO", "Non superato"),
    ]

    corso                = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="iscrizioni_elearning")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    stato                = models.CharField(max_length=15, choices=STATO_CHOICES, default="ISCRITTO")
    data_iscrizione      = models.DateTimeField(auto_now_add=True)
    ultima_slide_ordine  = models.PositiveSmallIntegerField(default=0, help_text="Avanzamento: ultima slide vista.")
    n_slide_totali       = models.PositiveSmallIntegerField(default=0)
    best_punteggio_pct   = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    n_tentativi          = models.PositiveSmallIntegerField(default=0)
    data_completamento   = models.DateField(null=True, blank=True)
    record_completamento = models.ForeignKey(
        TrainingEmployeeRecord, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("corso", "legacy_anagrafica_id")]
        verbose_name = "Iscrizione e-learning"
        verbose_name_plural = "Iscrizioni e-learning"
        indexes = [models.Index(fields=["legacy_anagrafica_id", "stato"])]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.corso.codice} ({self.stato})"


class TrainingQuizAttempt(models.Model):
    """Tentativo (invio) del quiz finale di un micro-corso e-learning.

    Storicizza ogni invio (audit qualità: chi, quando, esito, punteggio, risposte).
    Il primo tentativo conforme genera un :class:`TrainingEmployeeRecord` collegato."""

    corso                = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="quiz_tentativi")
    enrollment           = models.ForeignKey(
        TrainingElearningEnrollment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tentativi",
    )
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    iniziato_il          = models.DateTimeField(null=True, blank=True)
    inviato_il           = models.DateTimeField(auto_now_add=True)
    punteggio_pct        = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    n_corrette           = models.PositiveSmallIntegerField(default=0)
    n_totali             = models.PositiveSmallIntegerField(default=0)
    superato             = models.BooleanField(default=False)
    # Snapshot domande/opzioni scelte (audit: l'esito resta verificabile anche se il
    # quiz viene poi modificato).
    risposte_json        = models.JSONField(default=dict, blank=True)
    record               = models.ForeignKey(
        TrainingEmployeeRecord, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="quiz_tentativi",
    )
    utente               = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-inviato_il"]
        verbose_name = "Tentativo quiz"
        verbose_name_plural = "Tentativi quiz"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "corso"]),
            models.Index(fields=["corso", "superato"]),
        ]

    def __str__(self) -> str:
        esito = "OK" if self.superato else "KO"
        return f"[{self.legacy_anagrafica_id}] {self.corso.codice} — {self.punteggio_pct}% {esito}"


# ─────────────────────────────────────────────────────────────
# Pulizia file slide-immagine (evita file orfani nello storage)
# ─────────────────────────────────────────────────────────────
from django.db.models.signals import post_delete  # noqa: E402
from django.dispatch import receiver  # noqa: E402


class ElearningConfig(models.Model):
    """Singleton — impostazioni e default dei micro-corsi e-learning.

    Pattern identico ad :class:`AttestatoFormazioneConfig`: una sola riga (pk=1),
    modificabile dalle Impostazioni HR. I default vengono applicati ai nuovi corsi
    e-learning; ``libreoffice_path`` è il fallback per la conversione PowerPoint."""

    quiz_punteggio_minimo_default = models.PositiveSmallIntegerField(
        default=70,
        help_text="Percentuale minima del quiz proposta di default ai nuovi micro-corsi (0–100).",
    )
    validita_mesi_default = models.PositiveSmallIntegerField(
        default=0,
        help_text="Validità in mesi proposta di default (0 = una tantum, nessun rinnovo).",
    )
    max_tentativi_quiz = models.PositiveSmallIntegerField(
        default=0,
        help_text="Numero massimo di tentativi del quiz per dipendente (0 = illimitati).",
    )
    libreoffice_path = models.CharField(
        max_length=400, blank=True, default="",
        help_text="Percorso dell'eseguibile LibreOffice (soffice) per l'import PowerPoint. "
                  "Vuoto = usa LIBREOFFICE_PATH/variabile d'ambiente o auto-rilevamento.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = "Impostazioni e-learning"
        verbose_name_plural = "Impostazioni e-learning"

    def __str__(self) -> str:
        return "Impostazioni e-learning"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_instance(cls) -> "ElearningConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


@receiver(post_delete, sender=TrainingSlide)
def _elimina_file_slide(sender, instance, **kwargs):
    """Rimuove il file immagine dallo storage quando la slide viene eliminata.

    Registrare il signal disabilita anche il fast-delete di Django per TrainingSlide,
    così la pulizia avviene pure quando le slide sono cancellate a cascata (es. corso
    eliminato). Fail-safe: un errore qui non deve bloccare l'eliminazione."""
    if instance.immagine:
        try:
            instance.immagine.delete(save=False)
        except Exception:
            pass
