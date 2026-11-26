"""E-learning professionale (prompt 05, rilascio 2): tracciamento lato server e registro.

- ``TrainingElearningSessione``: una sessione di fruizione del player. Il tempo si
  accredita solo da heartbeat lato server (limite ≥ 30 s, pausa per inattività,
  una sessione attiva per iscrizione): mai sommando valori inviati dal browser.
- ``TrainingElearningSlideView``: tempo effettivo per slide e slide «completata».
- ``TrainingElearningCompletamento``: la riga che garantisce **a livello di
  database** un solo completamento per iscrizione (OneToOne su iscrizione e su
  record) e che fotografa i requisiti verificati: è la riga del registro di audit.

File importato da ``anagrafica/models.py`` (``from .models_elearning import *``).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


def _storage_privato():
    from .storage import PrivateAnagraficaStorage
    return PrivateAnagraficaStorage()

__all__ = ["TrainingElearningSessione", "TrainingElearningSlideView", "TrainingElearningCompletamento"]


class TrainingElearningSessione(models.Model):
    enrollment = models.ForeignKey(
        "anagrafica.TrainingElearningEnrollment", on_delete=models.CASCADE, related_name="sessioni",
    )
    avviata_il = models.DateTimeField(auto_now_add=True)
    ultimo_beat_il = models.DateTimeField()
    slide_corrente = models.ForeignKey(
        "anagrafica.TrainingSlide", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    secondi_accreditati = models.PositiveIntegerField(default=0)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ua_hash = models.CharField(max_length=64, blank=True, default="")
    chiusa = models.BooleanField(default=False)

    class Meta:
        ordering = ["-avviata_il"]
        verbose_name = "Sessione e-learning"
        verbose_name_plural = "Sessioni e-learning"
        indexes = [models.Index(fields=["enrollment", "chiusa"])]

    def __str__(self) -> str:
        return f"Sessione #{self.pk} iscrizione {self.enrollment_id}"


class TrainingElearningSlideView(models.Model):
    enrollment = models.ForeignKey(
        "anagrafica.TrainingElearningEnrollment", on_delete=models.CASCADE, related_name="slide_viste",
    )
    slide = models.ForeignKey("anagrafica.TrainingSlide", on_delete=models.CASCADE, related_name="viste")
    prima_vista = models.DateTimeField(auto_now_add=True)
    ultima_vista = models.DateTimeField(auto_now=True)
    secondi = models.PositiveIntegerField(default=0)
    video_secondi = models.PositiveIntegerField(default=0, help_text="Secondi di video guardati davvero (non saltati).")
    video_durata = models.PositiveIntegerField(default=0, help_text="Durata del video letta dal browser.")
    completata = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Slide vista"
        verbose_name_plural = "Slide viste"
        constraints = [models.UniqueConstraint(fields=["enrollment", "slide"], name="uniq_elearning_slide_vista")]


class TrainingElearningCompletamento(models.Model):
    """Un solo completamento per iscrizione (ciclo), con la prova di cosa è stato verificato."""

    enrollment = models.OneToOneField(
        "anagrafica.TrainingElearningEnrollment", on_delete=models.PROTECT, related_name="completamento",
    )
    record = models.OneToOneField(
        "anagrafica.TrainingEmployeeRecord", on_delete=models.PROTECT, related_name="completamento_elearning",
    )
    tentativo = models.ForeignKey(
        "anagrafica.TrainingQuizAttempt", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
    )
    verifica_json = models.JSONField(default=dict)
    sha256 = models.CharField(max_length=64)
    creato_il = models.DateTimeField(auto_now_add=True)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-creato_il"]
        verbose_name = "Completamento e-learning (registro)"
        verbose_name_plural = "Completamenti e-learning (registro)"

    def __str__(self) -> str:
        return f"Completamento #{self.pk} record {self.record_id}"


class TrainingElearningAvviso(models.Model):
    """Promemoria, sollecito o digest già inviato: la ``chiave`` univoca impedisce i doppioni.

    Una riga per soglia della scaletta (es. «14 giorni prima» del ciclo 2 di quel
    corso per quella persona) o per digest settimanale di un responsabile. Il job
    può girare più volte al giorno, o saltare un giorno, senza mandare due volte
    lo stesso avviso.
    """

    TIPO_CHOICES = [
        ("PRIMA", "Promemoria prima della scadenza"),
        ("SOLLECITO", "Sollecito dopo la scadenza"),
        ("DIGEST", "Digest settimanale al responsabile"),
    ]

    chiave = models.CharField(max_length=160, unique=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    corso = models.ForeignKey(
        "anagrafica.TrainingCourse", null=True, blank=True, on_delete=models.CASCADE, related_name="+",
    )
    legacy_anagrafica_id = models.IntegerField(null=True, blank=True, db_index=True)
    ciclo = models.PositiveSmallIntegerField(default=1)
    giorni = models.SmallIntegerField(default=0, help_text="Soglia della scaletta (giorni prima o dopo la scadenza).")
    responsabile_legacy_id = models.IntegerField(null=True, blank=True)
    email_inviata = models.BooleanField(default=False)
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creato_il"]
        verbose_name = "Avviso e-learning inviato"
        verbose_name_plural = "Avvisi e-learning inviati"

    def __str__(self) -> str:
        return self.chiave


class TrainingElearningGradimento(models.Model):
    """Questionario di gradimento compilato dal discente dopo il completamento.

    Uno per completamento (record). Le domande si fotografano con le risposte:
    se HR cambia il questionario, le risposte vecchie restano leggibili. Il
    cruscotto mostra solo medie e commenti senza nome."""

    record = models.OneToOneField(
        "anagrafica.TrainingEmployeeRecord", on_delete=models.CASCADE, related_name="gradimento_elearning",
    )
    corso = models.ForeignKey("anagrafica.TrainingCourse", on_delete=models.CASCADE, related_name="+")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    domande_json = models.JSONField(default=list)
    voti_json = models.JSONField(default=list, help_text="Un voto da 1 a 5 per domanda, nello stesso ordine.")
    media = models.DecimalField(max_digits=3, decimal_places=2)
    commento = models.TextField(blank=True, default="")
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creato_il"]
        verbose_name = "Gradimento e-learning"
        verbose_name_plural = "Gradimenti e-learning"
        indexes = [models.Index(fields=["corso", "creato_il"])]

    def __str__(self) -> str:
        return f"Gradimento record {self.record_id}: {self.media}"


class TrainingElearningModulo(models.Model):
    """Modulo di un corso online: un gruppo di slide (lezioni) con un titolo."""

    corso = models.ForeignKey("anagrafica.TrainingCourse", on_delete=models.CASCADE, related_name="moduli_elearning")
    ordine = models.PositiveSmallIntegerField(default=1)
    titolo = models.CharField(max_length=200)
    obbligatorio = models.BooleanField(default=True, help_text="Fa parte del percorso guidato per il quiz. "
                                                               "Se no, è solo materiale da consultare.")
    ALTERNATIVA_CHOICES = [("", "Per tutti"), ("VIDEO", "Solo percorso video"), ("SLIDE", "Solo percorso slide")]
    alternativa = models.CharField(
        max_length=5, choices=ALTERNATIVA_CHOICES, blank=True, default="",
        help_text="Con almeno un modulo «Solo percorso video» e uno «Solo percorso slide» nel percorso, "
                  "il discente sceglie all'inizio se guardare il video o seguire le slide.")
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["corso", "ordine", "id"]
        verbose_name = "Modulo e-learning"
        verbose_name_plural = "Moduli e-learning"

    def __str__(self) -> str:
        return f"{self.corso_id} · {self.ordine}. {self.titolo}"


class TrainingElearningImport(models.Model):
    """Import di slide da PowerPoint/PDF eseguito in background (django-q).

    La conversione con LibreOffice può durare minuti: la richiesta web salva il
    file e accoda il lavoro; la pagina dell'autore mostra lo stato. Il file di
    origine si cancella a lavoro finito."""

    IN_CODA, IN_CORSO, COMPLETATO, ERRORE = "IN_CODA", "IN_CORSO", "COMPLETATO", "ERRORE"
    STATO_CHOICES = [(IN_CODA, "In coda"), (IN_CORSO, "In corso"), (COMPLETATO, "Completato"), (ERRORE, "Errore")]

    corso = models.ForeignKey("anagrafica.TrainingCourse", on_delete=models.CASCADE, related_name="+")
    file = models.FileField(upload_to="elearning/import/", storage=_storage_privato, blank=True)
    nome_file = models.CharField(max_length=255)
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=IN_CODA)
    n_slide = models.PositiveSmallIntegerField(default=0)
    errore = models.CharField(max_length=500, blank=True, default="")
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="+")
    creato_il = models.DateTimeField(auto_now_add=True)
    avviato_il = models.DateTimeField(null=True, blank=True)
    finito_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creato_il"]
        verbose_name = "Import slide e-learning"
        verbose_name_plural = "Import slide e-learning"

    def __str__(self) -> str:
        return f"Import {self.nome_file} ({self.stato})"

    @property
    def in_lavorazione(self) -> bool:
        return self.stato in (self.IN_CODA, self.IN_CORSO)


class TrainingElearningLinkAperto(models.Model):
    """Link aperto di un corso e-learning: chi non ha un utente del portale (es. l'officina)
    segue slide, video e quiz senza login e alla fine scrive nome e cognome.

    Un link per corso; il token si rigenera (il vecchio smette di funzionare) e si spegne."""

    corso = models.OneToOneField("anagrafica.TrainingCourse", on_delete=models.CASCADE, related_name="link_aperto")
    token = models.CharField(max_length=64, unique=True)
    attivo = models.BooleanField(default=True)
    scade_il = models.DateField(null=True, blank=True, help_text="Ultimo giorno valido; vuoto = senza scadenza.")
    chiedi_pin = models.BooleanField(default=False, help_text="Chi ha un PIN delle postazioni condivise deve scriverlo "
                                                              "alla registrazione (chi non ce l'ha passa con la matricola).")
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="+")
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Link aperto e-learning"
        verbose_name_plural = "Link aperti e-learning"

    def __str__(self) -> str:
        return f"Link aperto corso {self.corso_id} ({'attivo' if self.attivo else 'spento'})"


def _codice_ripresa() -> str:
    import secrets
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente 0/O, 1/I: si detta al telefono
    return "".join(secrets.choice(alfabeto) for _ in range(8))


class TrainingElearningPartecipazioneAperta(models.Model):
    """Chi sta seguendo un corso dal link aperto: nasce alla registrazione, prima delle slide.

    Tiene sul server avanzamento e tempo (non solo nel browser), così l'HR vede chi sta
    facendo il corso e la persona può riprendere da un altro telefono con il codice."""

    corso = models.ForeignKey("anagrafica.TrainingCourse", on_delete=models.CASCADE, related_name="partecipazioni_aperte")
    codice = models.CharField(max_length=12, unique=True, default=_codice_ripresa)
    nome = models.CharField(max_length=100)
    cognome = models.CharField(max_length=100)
    matricola = models.CharField(max_length=40, blank=True, default="")
    reparto = models.CharField(max_length=120, blank=True, default="", help_text="Dal QR di reparto, se usato.")
    legacy_anagrafica_id = models.IntegerField(null=True, blank=True, db_index=True)
    nota_abbinamento = models.CharField(max_length=300, blank=True, default="")
    registrato_il = models.DateTimeField(auto_now_add=True)
    ultimo_accesso_il = models.DateTimeField(null=True, blank=True)
    secondi = models.PositiveIntegerField(default=0, help_text="Tempo effettivo misurato dal server.")
    slide_viste = models.JSONField(default=dict, blank=True, help_text="{ordine: timestamp della prima apertura}")
    video_visti = models.JSONField(default=dict, blank=True, help_text="{slide_id: secondi guardati}")
    percorso = models.CharField(max_length=5, blank=True, default="", help_text="VIDEO o SLIDE, se il corso li offre a scelta.")
    completata_il = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-registrato_il"]
        indexes = [models.Index(fields=["corso", "registrato_il"])]
        verbose_name = "Partecipazione dal link aperto"
        verbose_name_plural = "Partecipazioni dal link aperto"

    def __str__(self) -> str:
        return f"{self.cognome} {self.nome} · {self.corso_id}"


class TrainingElearningRispostaAperta(models.Model):
    """Un quiz inviato dal link aperto, con il nome scritto a mano.

    L'abbinamento alla persona dell'anagrafica è automatico quando nome e cognome
    corrispondono a un solo dipendente attivo; altrimenti resta «Da abbinare» per l'HR.
    Il completamento (``TrainingEmployeeRecord``) nasce solo da un quiz superato e abbinato."""

    AUTO, MANUALE, DA_ABBINARE, SCARTATA = "AUTO", "MANUALE", "DA_ABBINARE", "SCARTATA"
    STATO_CHOICES = [
        (AUTO, "Abbinata in automatico"),
        (MANUALE, "Abbinata a mano"),
        (DA_ABBINARE, "Da abbinare"),
        (SCARTATA, "Scartata"),
    ]

    corso = models.ForeignKey("anagrafica.TrainingCourse", on_delete=models.CASCADE, related_name="risposte_aperte")
    nome = models.CharField(max_length=100)
    cognome = models.CharField(max_length=100)
    matricola = models.CharField(max_length=40, blank=True, default="",
                                 help_text="Matricola scritta dalla persona (es. T138, A012, CNO 1234).")
    partecipazione = models.ForeignKey(TrainingElearningPartecipazioneAperta, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="risposte")
    punteggio_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    n_corrette = models.PositiveSmallIntegerField(default=0)
    n_totali = models.PositiveSmallIntegerField(default=0)
    superato = models.BooleanField(default=False)
    risposte_json = models.JSONField(default=dict)
    versione_corso = models.CharField(max_length=40, blank=True, default="")
    avviato_il = models.DateTimeField(null=True, blank=True)
    inviato_il = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ua_hash = models.CharField(max_length=64, blank=True, default="")
    stato = models.CharField(max_length=12, choices=STATO_CHOICES, default=DA_ABBINARE, db_index=True)
    legacy_anagrafica_id = models.IntegerField(null=True, blank=True, db_index=True)
    record = models.ForeignKey("anagrafica.TrainingEmployeeRecord", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+")
    abbinata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    abbinata_il = models.DateTimeField(null=True, blank=True)
    nota = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-inviato_il"]
        verbose_name = "Risposta da link aperto"
        verbose_name_plural = "Risposte da link aperto"

    def __str__(self) -> str:
        return f"{self.cognome} {self.nome} · corso {self.corso_id} · {self.get_stato_display()}"
