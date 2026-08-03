from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ChecklistTaskTemplate(models.Model):
    """Mansione riutilizzabile del template di chiusura (configurazione)."""

    ordine = models.PositiveIntegerField(default=100)
    descrizione = models.TextField()
    reparto = models.CharField(max_length=150, blank=True, default="")
    responsabile = models.ForeignKey(
        "core.AnagraficaDipendente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklist_task_templates",
        help_text="Dipendente che dovrà eseguire e confermare la mansione a ogni chiusura.",
    )
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name = "Mansione checklist chiusura"
        verbose_name_plural = "Mansioni checklist chiusura"

    def __str__(self) -> str:
        return f"[{self.ordine}] {self.descrizione[:60]}"


class ChiusuraEvento(models.Model):
    """Occorrenza storicizzata di una chiusura aziendale (es. ferie estive 2026)."""

    STATO_APERTA = "aperta"
    STATO_CHIUSA = "chiusa"
    STATO_CHOICES = [
        (STATO_APERTA, "Aperta"),
        (STATO_CHIUSA, "Chiusa / archiviata"),
    ]

    nome = models.CharField(max_length=200)
    data_inizio = models.DateField()
    data_fine = models.DateField(null=True, blank=True)
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_APERTA, db_index=True)
    note = models.TextField(blank=True, default="")
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_inizio", "-id"]
        verbose_name = "Evento chiusura aziendale"
        verbose_name_plural = "Eventi chiusura aziendale"

    def __str__(self) -> str:
        return f"{self.nome} ({self.data_inizio:%d/%m/%Y})"

    @property
    def voci_totali(self) -> int:
        return self.voci.count()

    @property
    def voci_confermate(self) -> int:
        return self.voci.filter(confermato=True).count()

    @property
    def percentuale_completamento(self) -> int:
        totali = self.voci_totali
        if not totali:
            return 0
        return round(self.voci_confermate * 100 / totali)


class ChiusuraVoce(models.Model):
    """Istanza di una mansione per un evento di chiusura specifico (snapshot editabile)."""

    evento = models.ForeignKey(ChiusuraEvento, on_delete=models.CASCADE, related_name="voci")
    template = models.ForeignKey(
        ChecklistTaskTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="voci_generate",
    )
    ordine = models.PositiveIntegerField(default=100)
    descrizione = models.TextField()
    responsabile = models.ForeignKey(
        "core.AnagraficaDipendente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklist_voci_assegnate",
    )
    confermato = models.BooleanField(default=False)
    confermato_da = models.ForeignKey(
        "core.AnagraficaDipendente", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    confermato_il = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["ordine", "id"]
        verbose_name = "Voce checklist chiusura"
        verbose_name_plural = "Voci checklist chiusura"

    def __str__(self) -> str:
        return f"{self.evento.nome} - [{self.ordine}] {self.descrizione[:60]}"

    def conferma(self, dipendente, note: str = "") -> None:
        self.confermato = True
        self.confermato_da = dipendente
        self.confermato_il = timezone.now()
        if note:
            self.note = note
        self.save(update_fields=["confermato", "confermato_da", "confermato_il", "note"])

    def annulla_conferma(self) -> None:
        self.confermato = False
        self.confermato_da = None
        self.confermato_il = None
        self.save(update_fields=["confermato", "confermato_da", "confermato_il"])


class ChiusuraProposta(models.Model):
    """Proposta di aggiunta di una voce alla checklist, inviata da un responsabile."""

    STATO_IN_ATTESA = "in_attesa"
    STATO_APPROVATA = "approvata"
    STATO_RIFIUTATA = "rifiutata"
    STATO_CHOICES = [
        (STATO_IN_ATTESA, "In attesa"),
        (STATO_APPROVATA, "Approvata"),
        (STATO_RIFIUTATA, "Rifiutata"),
    ]

    evento = models.ForeignKey(
        ChiusuraEvento, on_delete=models.SET_NULL, null=True, blank=True, related_name="proposte",
    )
    descrizione = models.TextField()
    responsabile_suggerito = models.ForeignKey(
        "core.AnagraficaDipendente", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    proposto_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="checklist_proposte",
    )
    proposto_il = models.DateTimeField(auto_now_add=True)
    stato = models.CharField(max_length=10, choices=STATO_CHOICES, default=STATO_IN_ATTESA, db_index=True)
    note_admin = models.TextField(blank=True, default="")
    aggiungi_al_template = models.BooleanField(
        default=False, help_text="Se approvata, crea anche una mansione permanente in configurazione.",
    )
    gestito_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    gestito_il = models.DateTimeField(null=True, blank=True)
    voce_generata = models.ForeignKey(
        ChiusuraVoce, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    template_generato = models.ForeignKey(
        ChecklistTaskTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-proposto_il"]
        verbose_name = "Proposta voce checklist chiusura"
        verbose_name_plural = "Proposte voci checklist chiusura"

    def __str__(self) -> str:
        return f"Proposta #{self.pk} ({self.stato}): {self.descrizione[:60]}"
