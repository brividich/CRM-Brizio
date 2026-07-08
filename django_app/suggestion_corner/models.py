"""Modelli del modulo Suggestion Corner (SMS — Sistema di Miglioramento/Segnalazione).

Vedi docs/superpowers/specs/2026-07-08-suggestion-corner-design.md e
docs/BUILD_SPEC_suggestion_corner.md.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django_fsm import FSMField, transition

logger = logging.getLogger("suggestion_corner")


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

    class Stato(models.TextChoices):
        INSERITA = "INSERITA", "Inserita"
        DA_CLASSIFICARE = "DA_CLASSIFICARE", "Da classificare"
        CLASSIFICATA = "CLASSIFICATA", "Classificata"
        PLAN_DEFINITO = "PLAN_DEFINITO", "Plan definito"
        DO_IN_CORSO = "DO_IN_CORSO", "Do in corso"
        DO_COMPLETATO = "DO_COMPLETATO", "Do completato"
        CHECK_IN_CORSO = "CHECK_IN_CORSO", "Check in corso"
        CHECK_COMPLETATO = "CHECK_COMPLETATO", "Check completato"
        ACT_INSERITO = "ACT_INSERITO", "Act inserito"
        CHIUSA = "CHIUSA", "Chiusa"

    # Identificazione / provenienza
    legacy_sharepoint_id = models.IntegerField(null=True, blank=True, unique=True, db_index=True)
    da_portale = models.BooleanField(default=True)  # True = nuovo, False = migrato
    anonima = models.BooleanField(default=False)

    data_segnalazione = models.DateField(default=timezone.localdate)
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

    # --- Validazione di dominio -------------------------------------------
    def clean(self):
        super().clean()
        if (
            self.incaricato_id
            and self.controllore_id
            and self.incaricato_id == self.controllore_id
        ):
            raise ValidationError(
                {"controllore": "Il controllore deve essere diverso dall'incaricato."}
            )

    def save(self, *args, **kwargs):
        # Audit ISO 27001: logga un eventuale bypass della regola incaricato≠controllore
        if (
            self.incaricato_id
            and self.controllore_id
            and self.incaricato_id == self.controllore_id
        ):
            logger.warning(
                "SuggestionCorner#%s salvata con incaricato==controllore (id=%s): "
                "bypass regola di segregazione.",
                self.pk,
                self.incaricato_id,
            )
        super().save(*args, **kwargs)

    # --- Macchina a stati (§2) --------------------------------------------
    # Le transizioni cambiano `stato` (FSMField protected). Lo storico
    # `SuggestionCornerStorico` è creato centralmente dal signal
    # post_transition (state_machine.py); ogni transizione prepara
    # attore/payload via `_prep_evento`.

    def _prep_evento(self, attore=None, **payload):
        self._evento_attore = attore
        self._evento_payload = payload

    @transition(field=stato, source=Stato.INSERITA, target=Stato.DA_CLASSIFICARE)
    def notifica_sms_team(self, attore=None):
        """INSERITA→DA_CLASSIFICARE. La mail al team SMS è sessione 5."""
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.DA_CLASSIFICARE, target=Stato.CLASSIFICATA)
    def classifica(self, stato_sms, attore=None):
        """DA_CLASSIFICARE→CLASSIFICATA. Registra l'esito SMS (SI/NO)."""
        if stato_sms not in (self.StatoSMS.SMS_SI, self.StatoSMS.SMS_NO):
            raise ValidationError("stato_sms deve essere SMS_SI o SMS_NO.")
        self.stato_sms = stato_sms
        self._prep_evento(attore, stato_sms=str(stato_sms))

    @transition(field=stato, source=Stato.CLASSIFICATA, target=Stato.PLAN_DEFINITO)
    def definisci_plan(self, incaricato, controllore, data_limite_esecuzione,
                       data_limite_controllo, plan_testo="", attore=None):
        """CLASSIFICATA→PLAN_DEFINITO. incaricato≠controllore obbligatorio."""
        if incaricato is not None and incaricato == controllore:
            raise ValidationError("Il controllore deve essere diverso dall'incaricato.")
        self.incaricato = incaricato
        self.controllore = controllore
        self.data_limite_esecuzione = data_limite_esecuzione
        self.data_limite_controllo = data_limite_controllo
        self.plan_testo = plan_testo
        self.plan_eseguito = True
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.PLAN_DEFINITO, target=Stato.DO_IN_CORSO)
    def avvia_do(self, attore=None):
        """PLAN_DEFINITO→DO_IN_CORSO."""
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.DO_IN_CORSO, target=Stato.DO_COMPLETATO)
    def completa_do(self, esito_do, do_testo="", attore=None):
        """DO_IN_CORSO→DO_COMPLETATO. Registra esito (SI/NO) e data. Regola
        'chi completa deve essere self.incaricato' enforced lato view (sessione 3)."""
        if esito_do not in (self.EsitoAttivita.SI, self.EsitoAttivita.NO):
            raise ValidationError("esito_do deve essere SI o NO.")
        self.do_eseguito = True
        self.data_esecuzione_do = timezone.localdate()
        self.esito_do = esito_do
        self.do_testo = do_testo
        self._prep_evento(attore, esito_do=str(esito_do))

    @transition(field=stato, source=Stato.DO_COMPLETATO, target=Stato.CHECK_IN_CORSO,
                conditions=[lambda self: self.esito_do == "SI"])
    def avvia_check(self, attore=None):
        """DO_COMPLETATO→CHECK_IN_CORSO (solo se esito_do==SI)."""
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.DO_COMPLETATO, target=Stato.DO_IN_CORSO,
                conditions=[lambda self: self.esito_do == "NO"])
    def do_da_rifare(self, nuova_data_limite_esecuzione, attore=None):
        """DO_COMPLETATO→DO_IN_CORSO (solo se esito_do==NO). Nuova scadenza,
        reset dei campi DO per la riesecuzione."""
        self.data_limite_esecuzione = nuova_data_limite_esecuzione
        self.do_eseguito = False
        self.esito_do = ""
        self.data_esecuzione_do = None
        self.sollecito_do_30 = False
        self.sollecito_do_15 = False
        self.sollecito_do_5 = False
        self.escalation_do_inviata = False
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.CHECK_IN_CORSO, target=Stato.CHECK_COMPLETATO)
    def check_positivo(self, check_testo="", attore=None):
        """CHECK_IN_CORSO→CHECK_COMPLETATO. Verifica positiva."""
        self.esito_check = self.EsitoCheck.POSITIVO
        self.check_eseguito = True
        self.data_esecuzione_check = timezone.localdate()
        self.check_testo = check_testo
        self._prep_evento(attore, esito_check="POSITIVO")

    @transition(field=stato, source=Stato.CHECK_IN_CORSO, target=Stato.DO_IN_CORSO)
    def check_negativo(self, check_testo="", attore=None):
        """CHECK_IN_CORSO→DO_IN_CORSO. Verifica negativa: riapre il DO."""
        self.esito_check = self.EsitoCheck.NEGATIVO
        self.check_testo = check_testo
        # riapertura DO
        self.do_eseguito = False
        self.esito_do = ""
        self.data_esecuzione_do = None
        self.check_eseguito = False
        self.data_limite_esecuzione = None
        self.sollecito_do_30 = False
        self.sollecito_do_15 = False
        self.sollecito_do_5 = False
        self.escalation_do_inviata = False
        self.sollecito_check_30 = False
        self.sollecito_check_15 = False
        self.sollecito_check_5 = False
        self.escalation_check_inviata = False
        self._prep_evento(attore, esito_check="NEGATIVO")

    @transition(field=stato, source=Stato.CHECK_IN_CORSO, target=Stato.CHECK_IN_CORSO)
    def check_rinviato(self, nuova_data_limite_controllo, attore=None):
        """CHECK_IN_CORSO→CHECK_IN_CORSO (self-loop). Rinvio con nuova scadenza."""
        self.esito_check = self.EsitoCheck.RINVIATO
        self.data_limite_controllo = nuova_data_limite_controllo
        self.sollecito_check_30 = False
        self.sollecito_check_15 = False
        self.sollecito_check_5 = False
        self.escalation_check_inviata = False
        self._prep_evento(attore, esito_check="RINVIATO")

    @transition(field=stato, source=Stato.CHECK_COMPLETATO, target=Stato.ACT_INSERITO,
                conditions=[lambda self: self.vuoi_inserire_act])
    def inserisci_act(self, attore=None):
        """CHECK_COMPLETATO→ACT_INSERITO (solo se vuoi_inserire_act)."""
        self.act_eseguito = True
        self._prep_evento(attore)

    @transition(field=stato, source=[Stato.CHECK_COMPLETATO, Stato.ACT_INSERITO],
                target=Stato.CHIUSA)
    def chiudi(self, attore=None):
        """{CHECK_COMPLETATO, ACT_INSERITO}→CHIUSA."""
        self._prep_evento(attore)


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
        "anagrafica.ProcessoQualificato", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="suggestion_mapping",
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Mappatura processo"
        verbose_name_plural = "Mappature processi (Suggestion Corner)"
        ordering = ["valore_libero"]

    def __str__(self) -> str:
        return f"{self.valore_libero} → {self.processo or '(default)'}"
