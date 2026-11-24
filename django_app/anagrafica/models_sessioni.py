"""Sessioni formative (specifica della Qualità v1.0 del 23/11/2026).

Una richiesta approvata (RAM di assegnazione o RAC) apre una sessione formativa: il documento che
raccoglie, competenza per competenza, come la persona l'ha acquisita e chi l'ha valutata. La
sessione ha una sola richiesta di origine e si chiude con due firme: chi ha approvato (RDD per le
mansioni, MSO per le competenze) e la persona. Solo alla chiusura cambiano i livelli nella skill
matrix.

Ogni riga è una competenza per la persona. Le modalità sono modi di raccogliere l'evidenza, non
livelli:

- **P, pregressa**: esperienza precedente verificata (descrizione, data della verifica);
- **A, affiancamento**: tutor, periodo, ore e registro MOD.040 caricato;
- **C, corso**: corso o docente/ente e una verifica tra attestato, test e conferma del responsabile.

Una competenza che la persona ha già al livello richiesto entra «già presente» e non va rivalutata.
Il registro degli eventi è di sola aggiunta.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from .models_skillmatrix import LivelloSkm

__all__ = ["SessioneFormativa", "SessionePartecipante", "SessioneRiga", "SessioneEvento", "ContatoreMatricola"]


def _cartella_firme(istanza, nome: str) -> str:
    """Non più usata dai campi (la firma è del partecipante): resta per le migrazioni già scritte."""
    return f"anagrafica/sessioni_formative/{istanza.codice}/firma_{nome}"


def _cartella_firme_partecipante(istanza, nome: str) -> str:
    return f"anagrafica/sessioni_formative/{istanza.sessione.codice}/firma_{istanza.legacy_anagrafica_id}_{nome}"


def _cartella_registri(istanza, nome: str) -> str:
    return f"anagrafica/sessioni_formative/{istanza.sessione.codice}/mod040_{istanza.pk or 'nuova'}_{nome}"


class SessioneFormativa(models.Model):
    STATO_APERTA = "aperta"
    STATO_IN_CORSO = "in_corso"
    STATO_POSITIVA = "positiva"
    STATO_NEGATIVA = "negativa"
    STATO_CHOICES = [
        (STATO_APERTA, "Aperta"),
        (STATO_IN_CORSO, "In corso"),
        (STATO_POSITIVA, "Chiusa positiva"),
        (STATO_NEGATIVA, "Chiusa negativa"),
    ]
    STATI_APERTI = (STATO_APERTA, STATO_IN_CORSO)

    codice = models.CharField(max_length=20, unique=True)
    richiesta = models.OneToOneField(
        "anagrafica.RichiestaCompetenze", on_delete=models.PROTECT, related_name="sessione",
    )
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_APERTA, db_index=True)

    aperta_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    aperta_da_nome = models.CharField(max_length=160, blank=True, default="")
    aperta_il = models.DateTimeField(auto_now_add=True)

    firma_approvatore_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    firma_approvatore_nome = models.CharField(max_length=160, blank=True, default="")
    firma_approvatore_il = models.DateTimeField(null=True, blank=True)
    benestare_mod040 = models.BooleanField(
        default=False, help_text="Chi firma come approvatore ha visto i registri MOD.040 delle righe in affiancamento.",
    )

    chiusa_da_nome = models.CharField(max_length=160, blank=True, default="")
    chiusa_il = models.DateTimeField(null=True, blank=True)
    motivo_negativo = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-aperta_il", "-pk"]
        verbose_name = "Sessione formativa"
        verbose_name_plural = "Sessioni formative"

    def __str__(self) -> str:
        return self.codice

    @property
    def aperta(self) -> bool:
        return self.stato in self.STATI_APERTI


class SessionePartecipante(models.Model):
    """Una persona della sessione e la sua firma di chiusura (una sola persona, o un gruppo per un corso collettivo)."""

    FIRMA_PORTALE = "portale"
    FIRMA_CARTA = "carta"
    FIRMA_CHOICES = [(FIRMA_PORTALE, "Nel portale"), (FIRMA_CARTA, "Su carta, registrata")]

    sessione = models.ForeignKey(SessioneFormativa, on_delete=models.CASCADE, related_name="partecipanti")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    firma_modo = models.CharField(max_length=8, choices=FIRMA_CHOICES, blank=True, default="")
    firma_il = models.DateField(null=True, blank=True)
    firma_registrata_da = models.CharField(max_length=160, blank=True, default="")
    firma_registrata_il = models.DateTimeField(null=True, blank=True)
    firma_file = models.FileField(upload_to=_cartella_firme_partecipante, blank=True, max_length=300)

    class Meta:
        ordering = ["sessione", "pk"]
        constraints = [models.UniqueConstraint(fields=["sessione", "legacy_anagrafica_id"],
                                               name="anag_sessione_partecipante_unico")]
        verbose_name = "Partecipante di una sessione formativa"
        verbose_name_plural = "Partecipanti delle sessioni formative"

    def __str__(self) -> str:
        return f"{self.sessione_id}: {self.legacy_anagrafica_id}"

    @property
    def firmato(self) -> bool:
        return bool(self.firma_modo)


class SessioneRiga(models.Model):
    MODO_PREGRESSA = "P"
    MODO_AFFIANCAMENTO = "A"
    MODO_CORSO = "C"
    MODO_CHOICES = [(MODO_PREGRESSA, "Pregressa"), (MODO_AFFIANCAMENTO, "Affiancamento"), (MODO_CORSO, "Corso")]

    STATO_DA_ASSEGNARE = "da_assegnare"
    STATO_IN_ACQUISIZIONE = "in_acquisizione"
    STATO_POSITIVA = "positiva"
    STATO_GIA_PRESENTE = "gia_presente"
    STATO_CHOICES = [
        (STATO_DA_ASSEGNARE, "Da assegnare"),
        (STATO_IN_ACQUISIZIONE, "In acquisizione"),
        (STATO_POSITIVA, "Valutata positiva"),
        (STATO_GIA_PRESENTE, "Già presente"),
    ]
    STATI_FATTI = (STATO_POSITIVA, STATO_GIA_PRESENTE)

    VERIFICA_ATTESTATO = "attestato"
    VERIFICA_TEST = "test"
    VERIFICA_CONFERMA = "conferma"
    VERIFICA_CHOICES = [
        (VERIFICA_ATTESTATO, "Attestato"),
        (VERIFICA_TEST, "Test"),
        (VERIFICA_CONFERMA, "Conferma del responsabile"),
    ]

    sessione = models.ForeignKey(SessioneFormativa, on_delete=models.CASCADE, related_name="righe")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    voce = models.ForeignKey(
        "anagrafica.VoceMacchinaCatalogo", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        help_text="Competenza della mansione (sessioni da una richiesta di assegnazione).",
    )
    catalogo = models.ForeignKey(
        "anagrafica.CompetenzaCatalogo", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    competenza_nome = models.CharField(max_length=150)
    area = models.ForeignKey(
        "anagrafica.AreaAziendale", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Reparto il cui responsabile valuta la riga.",
    )
    ordine = models.PositiveIntegerField(default=0)
    livello_richiesto = models.CharField(max_length=1, choices=LivelloSkm.choices)
    livello_oggi = models.CharField(max_length=1, choices=LivelloSkm.choices, blank=True, default="")

    stato = models.CharField(max_length=16, choices=STATO_CHOICES, default=STATO_DA_ASSEGNARE)
    modalita = models.CharField(max_length=1, choices=MODO_CHOICES, blank=True, default="")
    livello_raggiunto = models.CharField(max_length=1, choices=LivelloSkm.choices, blank=True, default="")
    valutato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    valutato_da_nome = models.CharField(max_length=160, blank=True, default="")
    valutato_il = models.DateTimeField(null=True, blank=True)
    nota = models.TextField(blank=True, default="")

    # P — pregressa
    descrizione = models.TextField(blank=True, default="", help_text="Esperienza e come è stata verificata.")
    data_verifica = models.DateField(null=True, blank=True)
    # A — affiancamento
    tutor_nome = models.CharField(max_length=160, blank=True, default="")
    dal = models.DateField(null=True, blank=True)
    al = models.DateField(null=True, blank=True)
    ore = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    registro_mod040 = models.FileField(upload_to=_cartella_registri, blank=True, max_length=300)
    # C — corso
    corso = models.ForeignKey(
        "anagrafica.TrainingCourse", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    edizione = models.ForeignKey(
        "anagrafica.TrainingSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Edizione del corso a cui la persona è iscritta: data, docente ed esito vengono da lì.",
    )
    docente_ente = models.CharField(max_length=200, blank=True, default="")
    data_corso = models.DateField(null=True, blank=True)
    verifica = models.CharField(max_length=10, choices=VERIFICA_CHOICES, blank=True, default="")

    class Meta:
        ordering = ["sessione", "ordine", "pk"]
        verbose_name = "Riga di sessione formativa"
        verbose_name_plural = "Righe di sessione formativa"

    def __str__(self) -> str:
        return f"{self.sessione_id}: {self.competenza_nome}"

    @property
    def fatta(self) -> bool:
        return self.stato in self.STATI_FATTI


class SessioneEvento(models.Model):
    """Registro di sola aggiunta: chi ha fatto cosa sulla sessione, con il valore prima e dopo."""

    sessione = models.ForeignKey(SessioneFormativa, on_delete=models.PROTECT, related_name="eventi")
    riga = models.ForeignKey(SessioneRiga, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    quando = models.DateTimeField(auto_now_add=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    utente_nome = models.CharField(max_length=160, blank=True, default="")
    azione = models.CharField(max_length=60)
    prima = models.CharField(max_length=160, blank=True, default="")
    dopo = models.CharField(max_length=160, blank=True, default="")
    nota = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["quando", "pk"]
        verbose_name = "Evento di una sessione formativa"
        verbose_name_plural = "Eventi delle sessioni formative"

    def __str__(self) -> str:
        return f"{self.sessione_id}: {self.azione}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Il registro delle sessioni è di sola aggiunta: una riga non si modifica.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Il registro delle sessioni è di sola aggiunta: una riga non si cancella.")


class ContatoreMatricola(models.Model):
    """Numerazione della matricola per prefisso (specifica: CNO operatori, T impiegati tecnici, A amministrativi).

    Spento finché la Qualità non decide il numero di partenza: con il contatore spento la sessione
    d'ingresso si chiude senza matricola, e la storia lo dice.
    """

    prefisso = models.CharField(max_length=6, unique=True)
    inquadramento = models.CharField(max_length=16, blank=True, default="")
    ultimo = models.PositiveIntegerField(default=0, help_text="Ultimo numero usato: la prossima matricola è il successivo.")
    cifre = models.PositiveSmallIntegerField(default=4, help_text="Cifre del numero, con gli zeri davanti.")
    attivo = models.BooleanField(default=False)
    aggiornato_da = models.CharField(max_length=160, blank=True, default="")
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["prefisso"]
        verbose_name = "Contatore delle matricole"
        verbose_name_plural = "Contatori delle matricole"

    def __str__(self) -> str:
        return f"{self.prefisso}: {self.ultimo}"

    def prossima(self) -> str:
        return f"{self.prefisso}{self.ultimo + 1:0{self.cifre}d}"
