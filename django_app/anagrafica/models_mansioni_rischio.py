"""Override individuali delle mansioni di rischio e sicurezza operativa.

Le mansioni di rischio sono il catalogo ``Mansione`` (DVR e medico competente).
Quelle di una persona sono la mansione di rischio scritta in anagrafica più
quelle ricavate dalle mansioni che svolge (Mansionario), con **override
individuali** motivati (``DipendenteMansioneRischioOverride``) per i casi reali:
addetto antincendio, preposto, esclusione su indicazione del medico competente.
Vedi ``services/mansionario.py``.

Il vecchio catalogo separato ``MansioneRischio`` e il suo collegamento
``MansioneLavorativaRischio`` sono stati assorbiti nel catalogo ``Mansione``
(Mansionario fase 6, migrazioni anagrafica 0174-0176: nessun dato perso).

La **periodicità** delle visite non sta qui: la decide il medico competente
(``TipoVisitaMedica.durata_mesi`` e protocollo individuale
``RequisitoVisitaDipendente``).

Nello stesso file: timeline sicurezza del dipendente (eventi non clinici),
deroghe operative per visita mancante e configurazione del comportamento.

File importato da ``anagrafica/models.py`` tramite
``from .models_mansioni_rischio import *``.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


__all__ = [
    "DipendenteMansioneRischioOverride",
    "EventoSicurezzaDipendente",
    "DerogaOperativaVisita",
    "ConfigSicurezzaOperativa",
]


class DipendenteMansioneRischioOverride(models.Model):
    """Aggiunta o esclusione individuale di una mansione di rischio.

    Non si cancella mai: la revoca chiude l'override (``attivo=False``) e ne
    lascia la traccia. ``attivo`` è denormalizzato apposta: l'indice unique
    filtrato di SQL Server accetta solo condizioni positive.
    """

    AZIONE_AGGIUNGI = "ADD"
    AZIONE_ESCLUDI = "EXCLUDE"
    AZIONE_CHOICES = [
        (AZIONE_AGGIUNGI, "Aggiunta individuale"),
        (AZIONE_ESCLUDI, "Esclusione individuale"),
    ]

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    mansione_rischio = models.ForeignKey(
        "anagrafica.Mansione", on_delete=models.PROTECT, related_name="override_dipendenti",
        verbose_name="Mansione di rischio",
    )
    azione = models.CharField(max_length=8, choices=AZIONE_CHOICES)
    motivo = models.CharField(max_length=500)
    data_inizio = models.DateField()
    data_fine = models.DateField(null=True, blank=True)
    attivo = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revocato_il = models.DateTimeField(null=True, blank=True)
    revocato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    revoca_motivo = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-attivo", "-data_inizio", "-pk"]
        verbose_name = "Override mansione di rischio"
        verbose_name_plural = "Override mansioni di rischio"
        indexes = [models.Index(fields=["legacy_anagrafica_id", "attivo"])]
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_anagrafica_id", "mansione_rischio"],
                condition=Q(attivo=True), name="uniq_override_mansrischio_attivo",
            ),
            models.CheckConstraint(
                condition=Q(data_fine__isnull=True) | Q(data_fine__gte=models.F("data_inizio")),
                name="ck_override_mansrischio_date",
            ),
            models.CheckConstraint(condition=~Q(motivo=""), name="ck_override_mansrischio_motivo"),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.get_azione_display()}: {self.mansione_rischio}"

    def clean(self):
        if not (self.motivo or "").strip():
            raise ValidationError({"motivo": "Il motivo è obbligatorio."})
        if self.data_fine and self.data_inizio and self.data_fine < self.data_inizio:
            raise ValidationError({"data_fine": "La data di fine precede quella di inizio."})

    def vale_il(self, giorno) -> bool:
        return (
            self.attivo
            and self.data_inizio <= giorno
            and (self.data_fine is None or self.data_fine >= giorno)
        )


class EventoSicurezzaDipendente(models.Model):
    """Timeline sicurezza del dipendente: chi, quando, perché.

    Il ``payload`` è **non clinico** per costruzione: codici, id, etichette di
    mansione/adempimento. Mai esiti di idoneità, prescrizioni o referti — la
    timeline è leggibile da chi gestisce l'anagrafica, non solo dal sanitario.
    """

    TIPO_CHOICES = [
        ("ASSEGNAZIONE_REGISTRATA", "Spostamento registrato"),
        ("ASSEGNAZIONE_ANNULLATA", "Spostamento annullato"),
        ("OVERRIDE_AGGIUNTO", "Override mansione di rischio"),
        ("OVERRIDE_REVOCATO", "Override revocato"),
        ("PIANO_AGGIORNATO", "Piano di adeguamento aggiornato"),
        ("ADEMPIMENTO_CHIUSO", "Adempimento chiuso"),
        ("ADEMPIMENTO_ANNULLATO", "Adempimento annullato"),
        ("ADEMPIMENTO_NON_PIU_DOVUTO", "Adempimento non più dovuto"),
        ("ADEMPIMENTO_RIAPERTO", "Adempimento riaperto"),
        ("STATO_OPERATIVO", "Stato operativo"),
        ("DEROGA_CONCESSA", "Deroga concessa"),
        ("DEROGA_REVOCATA", "Deroga revocata"),
        ("MIGRAZIONE", "Migrazione dati"),
    ]

    legacy_anagrafica_id = models.IntegerField()
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    descrizione = models.CharField(max_length=300)
    occorso_il = models.DateTimeField(default=timezone.now)
    data_effetto = models.DateField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    actor_display = models.CharField(max_length=150, blank=True, default="")
    oggetto_tipo = models.CharField(max_length=60, blank=True, default="")
    oggetto_id = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-occorso_il", "-pk"]
        verbose_name = "Evento sicurezza dipendente"
        verbose_name_plural = "Eventi sicurezza dipendente"
        indexes = [models.Index(fields=["legacy_anagrafica_id", "-occorso_il"])]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] {self.get_tipo_display()}: {self.descrizione}"


class DerogaOperativaVisita(models.Model):
    """Deroga motivata e a termine allo stato «visita mancante»."""

    legacy_anagrafica_id = models.IntegerField(db_index=True)
    adempimento = models.ForeignKey(
        "anagrafica.AdempimentoCambioMansione", null=True, blank=True,
        on_delete=models.PROTECT, related_name="deroghe",
    )
    motivo = models.CharField(max_length=500)
    autorizzato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+",
    )
    autorizzato_il = models.DateTimeField(default=timezone.now)
    valida_fino = models.DateField()
    attivo = models.BooleanField(default=True)
    revocata_il = models.DateTimeField(null=True, blank=True)
    revocata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    revoca_motivo = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-autorizzato_il"]
        verbose_name = "Deroga operativa visita"
        verbose_name_plural = "Deroghe operative visita"
        constraints = [
            models.CheckConstraint(condition=~Q(motivo=""), name="ck_deroga_visita_motivo"),
        ]

    def __str__(self) -> str:
        return f"[{self.legacy_anagrafica_id}] deroga fino al {self.valida_fino:%d/%m/%Y}"

    def vale_il(self, giorno) -> bool:
        return self.attivo and self.valida_fino >= giorno


class ConfigSicurezzaOperativa(models.Model):
    """Singleton: comportamento dello stato operativo al cambio mansione."""

    MODALITA_SOLO_AVVISO = "SOLO_AVVISO"
    MODALITA_DEROGA = "DEROGA_AMMESSA"
    MODALITA_BLOCCO = "BLOCCO"
    MODALITA_CHOICES = [
        (MODALITA_SOLO_AVVISO, "Solo avviso"),
        (MODALITA_DEROGA, "Non idoneo a operare, salvo deroga motivata"),
        (MODALITA_BLOCCO, "Non idoneo a operare, nessuna deroga"),
    ]

    # Decisione di Brizio (10/10/2026): non idoneo a operare salvo deroga
    # motivata, al massimo 30 giorni (configurabile), rinnovabile solo con una
    # motivazione nuova.
    modalita_visita_mancante = models.CharField(
        max_length=20, choices=MODALITA_CHOICES, default=MODALITA_DEROGA,
        help_text="Cosa succede se la decorrenza arriva senza la visita del cambio mansione.",
    )
    deroga_max_giorni = models.PositiveSmallIntegerField(
        default=30, help_text="Durata massima di una deroga; il rinnovo richiede una motivazione nuova.",
    )
    aggiornata_il = models.DateTimeField(auto_now=True)
    aggiornata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = "Configurazione sicurezza operativa"
        verbose_name_plural = "Configurazione sicurezza operativa"

    def __str__(self) -> str:
        return f"Sicurezza operativa ({self.get_modalita_visita_mancante_display()})"

    @classmethod
    def load(cls) -> "ConfigSicurezzaOperativa":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
