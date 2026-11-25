"""Lezione online di una sessione formativa: slide + test finale, senza corso nuovo.

Una sessione (``TrainingSession``) di un corso già esistente può avere una lezione
online: slide (importate da PowerPoint/PDF, o copiate dal materiale del corso) e un
test a risposta chiusa. Gli iscritti alla sessione la seguono quando possono; chi
supera il test ha presenza e verifica registrate sull'iscrizione alla sessione
(``TrainingEnrollment``), e il completamento passa poi dalla strada di sempre
(gating del corso, record a libretto, attestato).

Tutto sta in tabelle proprie: il motore dei micro-corsi e-learning (slide e quiz
legati al corso) non cambia.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from .storage import PrivateAnagraficaStorage

__all__ = [
    "TrainingSessionOnline", "TrainingSessionSlide", "TrainingSessionQuestion",
    "TrainingSessionOption", "TrainingSessionProgress", "TrainingSessionAttempt",
]


def _slide_upload_to(instance, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()[:8] or ".png"
    now = timezone.now()
    return (f"anagrafica/formazione/sessioni/{instance.sessione_id or 'tmp'}/slides/"
            f"{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond}{suffix}")


class TrainingSessionOnline(models.Model):
    """Impostazioni della lezione online di una sessione (una per sessione)."""

    sessione = models.OneToOneField(
        "anagrafica.TrainingSession", on_delete=models.CASCADE, related_name="lezione_online",
    )
    soglia_pct = models.PositiveSmallIntegerField(
        default=70, help_text="Percentuale minima di risposte giuste per superare il test.")
    max_tentativi = models.PositiveSmallIntegerField(
        default=2, help_text="Tentativi del test per persona (0 = senza limite).")
    secondi_minimi_slide = models.PositiveSmallIntegerField(
        default=20, help_text="Tempo minimo su ogni slide prima di passare alla successiva (0 = nessuno).")
    disponibile_dal = models.DateField(null=True, blank=True)
    scadenza = models.DateField(null=True, blank=True, help_text="Data entro cui completare la lezione.")
    promemoria_giorni = models.PositiveSmallIntegerField(
        default=0, help_text="Giorni prima della scadenza per la notifica di promemoria a chi non ha finito "
                             "(0 = nessuno). Solo notifica nel portale, mai email.")
    materiale_corso = models.BooleanField(
        default=False, help_text="Usa slide, video e domande del corso (sempre aggiornati) invece di quelli propri.")
    mostra_correzioni = models.BooleanField(
        default=True, help_text="A fine test la persona vede le risposte sbagliate con quella giusta.")
    pubblicata_il = models.DateTimeField(null=True, blank=True)
    pubblicata_da_nome = models.CharField(max_length=160, blank=True, default="")
    ultimo_promemoria_il = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lezione online di sessione"
        verbose_name_plural = "Lezioni online di sessione"

    def __str__(self) -> str:
        return f"Lezione online {self.sessione_id}"

    @property
    def pubblicata(self) -> bool:
        return self.pubblicata_il is not None


class TrainingSessionSlide(models.Model):
    sessione = models.ForeignKey("anagrafica.TrainingSession", on_delete=models.CASCADE,
                                 related_name="slide_online")
    ordine = models.PositiveSmallIntegerField(default=1)
    titolo = models.CharField(max_length=300, blank=True, default="")
    immagine = models.ImageField(upload_to=_slide_upload_to, storage=PrivateAnagraficaStorage(),
                                 null=True, blank=True, max_length=300)
    testo = models.TextField(blank=True, default="", help_text="Testo della slide, se non è un'immagine.")
    origine = models.CharField(max_length=255, blank=True, default="", help_text="File o corso di provenienza.")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["sessione", "ordine", "id"]
        indexes = [models.Index(fields=["sessione", "ordine"])]
        verbose_name = "Slide della lezione online"
        verbose_name_plural = "Slide delle lezioni online"

    def __str__(self) -> str:
        return f"{self.sessione_id} · slide {self.ordine}"


class TrainingSessionQuestion(models.Model):
    sessione = models.ForeignKey("anagrafica.TrainingSession", on_delete=models.CASCADE,
                                 related_name="domande_online")
    ordine = models.PositiveSmallIntegerField(default=1)
    testo = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sessione", "ordine", "id"]
        indexes = [models.Index(fields=["sessione", "ordine"])]
        verbose_name = "Domanda della lezione online"
        verbose_name_plural = "Domande delle lezioni online"

    def __str__(self) -> str:
        return f"{self.sessione_id} · domanda {self.ordine}"


class TrainingSessionOption(models.Model):
    domanda = models.ForeignKey(TrainingSessionQuestion, on_delete=models.CASCADE, related_name="opzioni")
    ordine = models.PositiveSmallIntegerField(default=1)
    testo = models.CharField(max_length=500)
    corretta = models.BooleanField(default=False)

    class Meta:
        ordering = ["domanda", "ordine", "id"]
        verbose_name = "Risposta della lezione online"
        verbose_name_plural = "Risposte delle lezioni online"

    def __str__(self) -> str:
        return self.testo[:40]


class TrainingSessionProgress(models.Model):
    """Avanzamento di un iscritto nella lezione online (uno per iscrizione)."""

    enrollment = models.OneToOneField("anagrafica.TrainingEnrollment", on_delete=models.CASCADE,
                                      related_name="avanzamento_online")
    slide_viste = models.PositiveSmallIntegerField(default=0, help_text="Slide completate, in sequenza.")
    slide_corrente = models.PositiveSmallIntegerField(default=0)
    slide_aperta_il = models.DateTimeField(null=True, blank=True)
    secondi = models.PositiveIntegerField(default=0, help_text="Tempo passato sulle slide (dal server).")
    iniziata_il = models.DateTimeField(null=True, blank=True)
    ultimo_accesso_il = models.DateTimeField(null=True, blank=True)
    n_tentativi = models.PositiveSmallIntegerField(default=0)
    tentativi_extra = models.PositiveSmallIntegerField(default=0)
    miglior_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    superata_il = models.DateTimeField(null=True, blank=True)
    link_inviato_il = models.DateTimeField(null=True, blank=True)
    solleciti = models.PositiveSmallIntegerField(default=0)
    ultimo_sollecito_il = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Avanzamento lezione online"
        verbose_name_plural = "Avanzamenti lezioni online"

    def __str__(self) -> str:
        return f"iscr.{self.enrollment_id}: {self.slide_viste} slide, {self.n_tentativi} tentativi"


class TrainingSessionAttempt(models.Model):
    """Ogni consegna del test: chi, quando, esito e risposte (resta anche se il test cambia)."""

    enrollment = models.ForeignKey("anagrafica.TrainingEnrollment", on_delete=models.CASCADE,
                                   related_name="tentativi_online")
    numero = models.PositiveSmallIntegerField(default=1)
    iniziato_il = models.DateTimeField(null=True, blank=True)
    inviato_il = models.DateTimeField(default=timezone.now)
    punteggio_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    n_corrette = models.PositiveSmallIntegerField(default=0)
    n_totali = models.PositiveSmallIntegerField(default=0)
    soglia_pct = models.PositiveSmallIntegerField(default=0)
    superato = models.BooleanField(default=False)
    risposte_json = models.JSONField(default=list, blank=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["enrollment", "-inviato_il"]
        indexes = [models.Index(fields=["enrollment", "superato"])]
        verbose_name = "Tentativo del test online"
        verbose_name_plural = "Tentativi del test online"

    def __str__(self) -> str:
        return f"iscr.{self.enrollment_id} #{self.numero}: {self.punteggio_pct}%"


from django.db.models.signals import post_delete  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(post_delete, sender=TrainingSessionSlide)
def _cancella_file_slide(sender, instance, **kwargs):
    if instance.immagine:
        try:
            instance.immagine.delete(save=False)
        except Exception:  # pragma: no cover - file già sparito
            pass
