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
