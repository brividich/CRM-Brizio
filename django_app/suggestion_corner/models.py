"""Modelli del modulo Suggestion Corner (SMS — Sistema di Miglioramento/Segnalazione).

Vedi docs/superpowers/specs/2026-07-08-suggestion-corner-design.md e
docs/BUILD_SPEC_suggestion_corner.md.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_fsm import FSMField


class SuggestionCorner(models.Model):
    class StatoSMS(models.TextChoices):
        DA_GESTIRE = "DA_GESTIRE", "Da gestire"
        SMS_SI = "SMS_SI", "SMS Sì"
        SMS_NO = "SMS_NO", "SMS No"

    class EsitoAttivita(models.TextChoices):
        SI = "SI", "Sì"
        NO = "NO", "No"

    class EsitoCheck(models.TextChoices):
        POSITIVO = "POSITIVO", "Positivo"
        NEGATIVO = "NEGATIVO", "Negativo"
        RINVIATO = "RINVIATO", "Rinviato"

    # Identificazione / provenienza
    legacy_sharepoint_id = models.IntegerField(null=True, blank=True, unique=True, db_index=True)
    da_portale = models.BooleanField(default=True)  # True = nuovo, False = migrato
    anonima = models.BooleanField(default=False)

    data_segnalazione = models.DateField(auto_now_add=True)
    reparto_provenienza = models.ForeignKey(
        "anagrafica.Reparto", on_delete=models.PROTECT,
        related_name="segnalazioni_provenienza",
    )
    reparto_destinazione = models.ForeignKey(
        "anagrafica.Reparto", on_delete=models.PROTECT, null=True, blank=True,
        related_name="segnalazioni_destinazione",
    )
    processo = models.ForeignKey(
        "anagrafica.ProcessoQualificato", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="segnalazioni",
    )
    processo_libero = models.CharField(max_length=255, blank=True)

    opportunity = models.TextField()

    # PLAN
    plan_testo = models.TextField(blank=True)
    plan_eseguito = models.BooleanField(default=False)
    incaricato = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="suggestioncorner_do",
    )
    controllore = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="suggestioncorner_check",
    )
    data_limite_esecuzione = models.DateField(null=True, blank=True)
    data_limite_controllo = models.DateField(null=True, blank=True)

    # DO
    do_testo = models.TextField(blank=True)
    do_eseguito = models.BooleanField(default=False)
    data_esecuzione_do = models.DateField(null=True, blank=True)
    esito_do = models.CharField(max_length=8, choices=EsitoAttivita.choices, blank=True)

    # CHECK
    check_testo = models.TextField(blank=True)
    check_eseguito = models.BooleanField(default=False)
    data_esecuzione_check = models.DateField(null=True, blank=True)
    esito_check = models.CharField(max_length=10, choices=EsitoCheck.choices, blank=True)

    # ACT
    vuoi_inserire_act = models.BooleanField(default=False)
    act_testo = models.TextField(blank=True)
    act_eseguito = models.BooleanField(default=False)
    nuova_segnalazione_da_act = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="generata_da",
    )

    # Stato FSM (transizioni in sessione 2)
    stato = FSMField(default="INSERITA", protected=True, max_length=30, db_index=True)
    stato_sms = models.CharField(
        max_length=10, choices=StatoSMS.choices, default=StatoSMS.DA_GESTIRE,
    )

    # Reminder tracking (§3) — flag per soglia, la scadenza è calcolata a runtime
    sollecito_do_30 = models.BooleanField(default=False)
    sollecito_do_15 = models.BooleanField(default=False)
    sollecito_do_5 = models.BooleanField(default=False)
    sollecito_check_30 = models.BooleanField(default=False)
    sollecito_check_15 = models.BooleanField(default=False)
    sollecito_check_5 = models.BooleanField(default=False)
    escalation_do_inviata = models.BooleanField(default=False)
    escalation_check_inviata = models.BooleanField(default=False)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        verbose_name = "Segnalazione Suggestion Corner"
        verbose_name_plural = "Segnalazioni Suggestion Corner"
        ordering = ["-data_segnalazione", "-id"]

    def __str__(self) -> str:
        return f"SC#{self.pk} — {self.opportunity[:40]}"

    @property
    def scaduto_do(self) -> bool:
        return bool(
            self.data_limite_esecuzione
            and not self.do_eseguito
            and self.data_limite_esecuzione < timezone.now().date()
        )

    @property
    def scaduto_check(self) -> bool:
        return bool(
            self.data_limite_controllo
            and not self.check_eseguito
            and self.data_limite_controllo < timezone.now().date()
        )


class SuggestionCornerAllegato(models.Model):
    segnalazione = models.ForeignKey(
        SuggestionCorner, on_delete=models.CASCADE, related_name="allegati",
    )
    file = models.FileField(upload_to="suggestion_corner/%Y/", blank=True)
    link_esterno = models.URLField(blank=True, max_length=500)
    caricato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    caricato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Allegato segnalazione"
        verbose_name_plural = "Allegati segnalazione"

    def __str__(self) -> str:
        return self.file.name or self.link_esterno or f"Allegato #{self.pk}"


class SuggestionCornerStorico(models.Model):
    segnalazione = models.ForeignKey(
        SuggestionCorner, on_delete=models.CASCADE, related_name="storico",
    )
    stato_precedente = models.CharField(max_length=30)
    stato_nuovo = models.CharField(max_length=30)
    campo_modificato = models.CharField(max_length=50, blank=True)
    valore_precedente = models.TextField(blank=True)
    valore_nuovo = models.TextField(blank=True)
    autore = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Voce storico segnalazione"
        verbose_name_plural = "Storico segnalazione"
        ordering = ["-timestamp", "-id"]

    def __str__(self) -> str:
        return f"SC#{self.segnalazione_id}: {self.stato_precedente}→{self.stato_nuovo}"


class SuggestionCornerConfig(models.Model):
    giorni_sollecito_1 = models.PositiveIntegerField(default=30)
    giorni_sollecito_2 = models.PositiveIntegerField(default=15)
    giorni_sollecito_3 = models.PositiveIntegerField(default=5)
    giorni_escalation_oltre_scadenza = models.PositiveIntegerField(default=7)
    email_responsabile_escalation = models.EmailField(blank=True)
    sms_team_group_name = models.CharField(max_length=100, default="SMS_TEAM")

    class Meta:
        verbose_name = "Configurazione Suggestion Corner"
        verbose_name_plural = "Configurazione Suggestion Corner"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "SuggestionCornerConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return "Configurazione Suggestion Corner"


class SuggestionCornerProcessoMapping(models.Model):
    """Δ2 — normalizzazione: aggancia un valore `processo_libero` a un
    `ProcessoQualificato` reale (o lo marca come default), curabile da admin."""
    valore_libero = models.CharField(max_length=255, unique=True)
    processo = models.ForeignKey(
        "anagrafica.ProcessoQualificato", on_delete=models.CASCADE, null=True, blank=True,
        related_name="suggestion_mapping",
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Mappatura processo"
        verbose_name_plural = "Mappature processi (Suggestion Corner)"
        ordering = ["valore_libero"]

    def __str__(self) -> str:
        return f"{self.valore_libero} → {self.processo or '(default)'}"
