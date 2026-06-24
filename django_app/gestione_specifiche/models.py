"""Modelli dell'app gestione_specifiche (BUILD_SPEC §5).

Principio di retention: nulla viene cancellato fisicamente. Lo storico è dato
dalla catena revisioni, dagli stati terminali (S4/S6/S7/S8) e dall'audit
immutabile `EventoSpecifica` (con snapshot metadati nel payload).

Macchina a stati su `Specifica.stato` (FSMField, protected) — le transizioni
@transition sono definite in `state_machine.py` come metodi iniettati (F2).
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django_fsm import FSMField

from . import constants as C
from .storage import specifica_allegato_storage, upload_to_specifica


class Specifica(models.Model):
    """Specifica/comunicazione/piano di qualità — entità principale del flusso."""

    codice = models.CharField("Codice", max_length=100, db_index=True)
    revisione = models.CharField("Revisione", max_length=30, blank=True, default="")
    titolo = models.CharField("Titolo", max_length=300)
    tipo = models.CharField(
        "Tipo", max_length=20, choices=C.TIPO_CHOICES, default=C.TIPO_SPECIFICA
    )
    fonte = models.CharField(
        "Fonte", max_length=20, choices=C.FONTE_CHOICES, default=C.FONTE_CLIENTE
    )
    # Riferimento cliente (per fonte=cliente) — usato dai filtri elenco (F7).
    cliente = models.CharField("Cliente", max_length=200, blank=True, default="", db_index=True)
    # TAG di processo a livello specifica (classificazione AI/umana, filtro F7).
    tag = models.CharField("TAG processo", max_length=120, blank=True, default="", db_index=True)

    stato = FSMField(
        "Stato", max_length=30, choices=C.STATO_CHOICES,
        default=C.STATO_BOZZA, protected=True, db_index=True,
    )
    # Stato salvato prima di sospensione (S5) o errore tecnico (S9), per ripristino.
    stato_precedente = models.CharField("Stato precedente", max_length=30, blank=True, default="")

    data_inserimento = models.DateTimeField("Data inserimento", auto_now_add=True)
    data_verifica = models.DateField("Data verifica periodica", null=True, blank=True, db_index=True)
    note = models.TextField("Note", blank=True, default="")

    revisione_precedente = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="revisioni_successive", verbose_name="Revisione precedente",
    )
    master = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="duplicati", verbose_name="Specifica master (per duplicati)",
    )

    allegato = models.FileField(
        "Allegato", upload_to=upload_to_specifica, storage=specifica_allegato_storage,
        null=True, blank=True, max_length=255,
    )

    # Hook nullable per agganci futuri al resto del HUB (decisione F0 #9) — NO FK.
    commessa_ref = models.CharField("Rif. commessa", max_length=100, blank=True, default="", db_index=True)
    famiglia_ref = models.CharField("Rif. famiglia", max_length=100, blank=True, default="", db_index=True)

    created_at = models.DateTimeField("Creato il", auto_now_add=True)
    updated_at = models.DateTimeField("Aggiornato il", auto_now=True)

    class Meta:
        verbose_name = "Specifica"
        verbose_name_plural = "Specifiche"
        ordering = ["-data_inserimento", "codice"]
        indexes = [
            models.Index(fields=["codice"], name="gs_spec_codice_idx"),
            models.Index(fields=["stato"], name="gs_spec_stato_idx"),
            models.Index(fields=["tipo", "stato"], name="gs_spec_tipo_stato_idx"),
            models.Index(fields=["data_verifica"], name="gs_spec_dataverif_idx"),
        ]

    def __str__(self) -> str:
        rev = f" rev.{self.revisione}" if self.revisione else ""
        return f"{self.codice}{rev} — {self.titolo}"

    @property
    def is_attiva(self) -> bool:
        return self.stato in C.STATI_ATTIVI

    def snapshot_metadati(self) -> dict:
        """Snapshot metadati per il payload audit (ricostruzione punto-nel-tempo)."""
        return {
            "codice": self.codice,
            "revisione": self.revisione,
            "titolo": self.titolo,
            "tipo": self.tipo,
            "fonte": self.fonte,
            "cliente": self.cliente,
            "stato": self.stato,
            "data_verifica": self.data_verifica.isoformat() if self.data_verifica else None,
        }


class MOD133(models.Model):
    """Modulo MOD.133 di flow-down requisiti, 1:1 con la specifica."""

    specifica = models.OneToOneField(
        Specifica, on_delete=models.CASCADE, related_name="mod133", verbose_name="Specifica"
    )
    compilatore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mod133_compilati", verbose_name="Compilatore",
    )
    approvatore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mod133_approvati", verbose_name="Approvatore",
    )
    data_chiusura_compilazione = models.DateTimeField("Chiusura compilazione", null=True, blank=True)
    data_approvazione = models.DateTimeField("Data approvazione", null=True, blank=True)
    esito = models.CharField(
        "Esito", max_length=20, choices=C.ESITO_CHOICES, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "MOD.133"
        verbose_name_plural = "MOD.133"

    def __str__(self) -> str:
        return f"MOD.133 — {self.specifica.codice}"


class RigaMOD133(models.Model):
    """Riga di flow-down del MOD.133 (griglia requisiti/impatti)."""

    mod133 = models.ForeignKey(
        MOD133, on_delete=models.CASCADE, related_name="righe", verbose_name="MOD.133"
    )
    ordine = models.PositiveSmallIntegerField("Ordine", default=0)
    rif_paragrafo = models.CharField("Rif. paragrafo specifica", max_length=100, blank=True, default="")
    argomento = models.CharField("Argomento", max_length=300, blank=True, default="")
    descrizione_modifiche = models.TextField("Descrizione modifiche", blank=True, default="")
    descrizione_impatto = models.TextField("Descrizione impatto", blank=True, default="")
    rif_doc_cn = models.CharField("Rif. documento CN", max_length=100, blank=True, default="")
    rif_paragrafo_cn = models.CharField("Rif. paragrafo CN", max_length=100, blank=True, default="")
    tag_processo = models.CharField("TAG processo", max_length=120, blank=True, default="")
    impatto_documenti = models.BooleanField("Impatto documenti", default=False)
    impatto_operativo = models.BooleanField("Impatto operativo", default=False)
    genera_ofi = models.BooleanField("Genera OFI", default=False)
    # Rif. al registro OFI/MOD.174: registro inesistente nel portale (BLOCKER B1)
    # → numero OFI legacy come intero nullable; sostituibile con FK additiva in futuro.
    ofi = models.PositiveIntegerField("Numero OFI (MOD.174)", null=True, blank=True)

    class Meta:
        verbose_name = "Riga MOD.133"
        verbose_name_plural = "Righe MOD.133"
        ordering = ["mod133", "ordine", "id"]

    def __str__(self) -> str:
        return f"Riga {self.ordine} — {self.argomento or self.rif_paragrafo}"


class AzioneOFI(models.Model):
    """Sotto-flusso di modifica documento CN generato da una riga MOD.133 (F5)."""

    riga_mod133 = models.ForeignKey(
        RigaMOD133, on_delete=models.CASCADE, related_name="azioni_ofi", verbose_name="Riga MOD.133"
    )
    # Numero OFI nel registro MOD.174 (vedi nota su RigaMOD133.ofi / BLOCKER B1).
    ofi = models.PositiveIntegerField("Numero OFI (MOD.174)", null=True, blank=True)
    # Registro documenti CN inesistente → CharField col codice documento.
    documento_cn = models.CharField("Documento CN", max_length=150, blank=True, default="")
    tipo_azione = models.CharField("Tipo azione", max_length=100, blank=True, default="")
    stato = models.CharField(
        "Stato azione", max_length=20, choices=C.AZIONE_OFI_STATO_CHOICES, default=C.AZIONE_OFI_BOZZA
    )
    modo_approvazione = models.CharField(
        "Modo approvazione", max_length=30, choices=C.MODO_APPROVAZIONE_CHOICES,
    )
    approvatore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="azioni_ofi_approvate", verbose_name="Approvatore",
    )
    data_approvazione = models.DateTimeField("Data approvazione", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Azione OFI"
        verbose_name_plural = "Azioni OFI"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        # Default del modo approvazione dalla configurazione (decisione F0 #2).
        if not self.modo_approvazione:
            cfg = getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}
            self.modo_approvazione = cfg.get("APPROVAZIONE_DOC_CN_MODE", C.APPROV_CAR_FLOW)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Azione OFI {self.ofi or '—'} su {self.documento_cn or 'doc CN'}"


class Distribuzione(models.Model):
    """Distribuzione tracciata di una specifica verso reparti/canali (F6)."""

    specifica = models.ForeignKey(
        Specifica, on_delete=models.CASCADE, related_name="distribuzioni", verbose_name="Specifica"
    )
    canale = models.CharField("Canale", max_length=20, choices=C.CANALE_CHOICES)
    destinatari = models.ManyToManyField(
        "anagrafica.Reparto", blank=True, related_name="distribuzioni_specifiche",
        verbose_name="Reparti destinatari",
    )
    presa_visione_richiesta = models.BooleanField("Presa visione richiesta", default=False)
    cartacea = models.BooleanField("Copia cartacea", default=False)
    n_copie_distribuite = models.PositiveSmallIntegerField("Copie distribuite", default=0)
    n_copie_ritirate = models.PositiveSmallIntegerField("Copie ritirate", default=0)
    deroga_giustificazione = models.TextField("Giustificazione deroga copie", blank=True, default="")
    data_distribuzione = models.DateTimeField("Data distribuzione", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Distribuzione"
        verbose_name_plural = "Distribuzioni"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Distribuzione {self.get_canale_display()} — {self.specifica.codice}"


class EventoSpecifica(models.Model):
    """Audit immutabile delle transizioni/eventi di una specifica (§5).

    Solo create: update e delete sono impediti a livello di modello.
    """

    specifica = models.ForeignKey(
        Specifica, on_delete=models.CASCADE, related_name="eventi", verbose_name="Specifica"
    )
    stato_da = models.CharField("Stato da", max_length=30, blank=True, default="")
    stato_a = models.CharField("Stato a", max_length=30)
    attore = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="eventi_specifiche", verbose_name="Attore",
    )
    timestamp = models.DateTimeField("Timestamp", auto_now_add=True)
    trigger = models.CharField("Trigger", max_length=60, blank=True, default="")
    payload = models.JSONField("Payload", default=dict, blank=True)

    class Meta:
        verbose_name = "Evento specifica (audit)"
        verbose_name_plural = "Eventi specifica (audit)"
        ordering = ["specifica", "timestamp", "id"]
        indexes = [
            models.Index(fields=["specifica", "timestamp"], name="gs_evt_spec_ts_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("EventoSpecifica è immutabile: update non consentito.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("EventoSpecifica è immutabile: delete non consentito.")

    def __str__(self) -> str:
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.specifica_id}: {self.stato_da}→{self.stato_a}"


class ConfigPresaVisione(models.Model):
    """Configurazione presa visione per (tipo documento × reparto) — decisione F0 #3.

    `reparto` nullo = regola di default per quel tipo documento (tutti i reparti).
    """

    tipo_documento = models.CharField("Tipo documento", max_length=20, choices=C.TIPO_CHOICES)
    reparto = models.ForeignKey(
        "anagrafica.Reparto", null=True, blank=True, on_delete=models.CASCADE,
        related_name="config_presa_visione", verbose_name="Reparto (vuoto = tutti)",
    )
    richiesta = models.BooleanField("Presa visione richiesta", default=False)

    class Meta:
        verbose_name = "Config presa visione"
        verbose_name_plural = "Config presa visione"
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_documento", "reparto"], name="gs_configpv_tipo_reparto_uniq"
            ),
        ]

    def __str__(self) -> str:
        rep = self.reparto.nome if self.reparto else "TUTTI"
        return f"{self.get_tipo_documento_display()} / {rep}: {'sì' if self.richiesta else 'no'}"
