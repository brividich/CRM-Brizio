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
